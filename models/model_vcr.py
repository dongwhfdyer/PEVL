import torch
from torch import nn
import torch.nn.functional as F
import numpy as np
from functools import partial
from models.vit import VisionTransformer, interpolate_pos_embed
from models.xbert import BertConfig, BertForMaskedLM


class PEVL_VCR(nn.Module):
    def __init__(self,
                 tokenizer=None,
                 config=None,
                 postoken_dict=None,
                 init_deit=True
                 ):
        super().__init__()
        self.config = config
        self.min_pos = tokenizer('@@').input_ids[-1]
        self.max_pos = tokenizer('##').input_ids[-1]
        self.max_epochs = config['schedular']['epochs']
        self.tokenizer = tokenizer
        self.mlm_probability = config['mlm_probability']

        embed_dim = config['embed_dim']

        self.visual_encoder = VisionTransformer(
            img_size=config['image_res'], patch_size=16, embed_dim=768, depth=12, num_heads=12,
            mlp_ratio=4, qkv_bias=True, norm_layer=partial(nn.LayerNorm, eps=1e-6))

        if init_deit:
            checkpoint = torch.hub.load_state_dict_from_url(
                url="https://dl.fbaipublicfiles.com/deit/deit_base_patch16_224-b5f2ef4d.pth",
                map_location="cpu", check_hash=True)
            state_dict = checkpoint["model"]
            pos_embed_reshaped = interpolate_pos_embed(state_dict['pos_embed'], self.visual_encoder)
            state_dict['pos_embed'] = pos_embed_reshaped
            msg = self.visual_encoder.load_state_dict(state_dict, strict=False)
            print(msg)

        vision_width = config['vision_width']
        bert_config = BertConfig.from_json_file(config['bert_config'])

        self.text_encoder = BertForMaskedLM(config=bert_config)
        text_width = self.text_encoder.config.hidden_size
        self.vision_proj = nn.Linear(vision_width, embed_dim)
        self.text_proj = nn.Linear(text_width, embed_dim)

        self.temp = nn.Parameter(torch.ones([]) * config['temp'])
        self.queue_size = config['queue_size']
        self.momentum = config['momentum']
        self.itm_head = nn.Linear(text_width, 2)

        # create momentum models
        self.visual_encoder_m = VisionTransformer(
            img_size=config['image_res'], patch_size=16, embed_dim=768, depth=12, num_heads=12,
            mlp_ratio=4, qkv_bias=True, norm_layer=partial(nn.LayerNorm, eps=1e-6))
        self.vision_proj_m = nn.Linear(vision_width, embed_dim)
        self.text_encoder_m = BertForMaskedLM(config=bert_config)
        self.text_proj_m = nn.Linear(text_width, embed_dim)

        self.model_pairs = [[self.visual_encoder, self.visual_encoder_m],
                            [self.vision_proj, self.vision_proj_m],
                            [self.text_encoder, self.text_encoder_m],
                            [self.text_proj, self.text_proj_m],
                            ]

        self.copy_params()

        # create the queue
        self.register_buffer("image_queue", torch.randn(embed_dim, self.queue_size))
        self.register_buffer("text_queue", torch.randn(embed_dim, self.queue_size))
        self.register_buffer("queue_ptr", torch.zeros(1, dtype=torch.long))

        self.image_queue = nn.functional.normalize(self.image_queue, dim=0)
        self.text_queue = nn.functional.normalize(self.text_queue, dim=0)

        # define exponential decay ratio for position tokens' soft label
        self.exp_decay_ratio = config['exp_decay_ratio']

        # define position tokens' soft label based on exp_decay_ratio
        # there are 512 position tokens
        a = []
        for x in range(512):
            a.append(np.arange(512))
        a = np.array(a)
        for x, y in enumerate(a):
            a[x] = np.abs(a[x] - x)
        a = np.exp(-self.exp_decay_ratio * a)
        pos_tokens_simmartix_dict = {}
        pos_token = [f'[pos_{x}]' for x in range(512)]
        for x, y in zip(pos_token, a):
            pos_tokens_simmartix_dict[x] = y

        # when the number of position tokens are different from 512, you can change 800 to the index of Maximum of them. (In our case,it's the index of '##' )
        t = torch.randn((800, 30522)).fill_(0)
        for x in postoken_dict.keys():
            postoken_vector = pos_tokens_simmartix_dict[x]
            index = postoken_dict[x]
            t[index, self.min_pos + 1:self.max_pos] = torch.Tensor(postoken_vector / np.sum(postoken_vector))

        self.pos_tokens_soft_labels = t

        # define loss weight for position tokens' ordering-aware objective
        self.postoken_weight = config['postoken_temp']

    def forward(self, image=None, text=None, alpha=0, itm_labels=None, mode='pretrain'):
        if mode == 'pretrain':
            with torch.no_grad():
                self.temp.clamp_(0.001, 0.5)
            image_embeds = self.visual_encoder(image)
            image_atts = torch.ones(image_embeds.size()[:-1], dtype=torch.long).to(image.device)
            image_feat = F.normalize(self.vision_proj(image_embeds[:, 0, :]), dim=-1)
            text_output = self.text_encoder.bert(text.input_ids, attention_mask=text.attention_mask,
                                                 return_dict=True, mode='text')
            text_embeds = text_output.last_hidden_state
            text_feat = F.normalize(self.text_proj(text_embeds[:, 0, :]), dim=-1)

            # get momentum features
            with torch.no_grad():
                self._momentum_update()
                image_embeds_m = self.visual_encoder_m(image)
                image_feat_m = F.normalize(self.vision_proj_m(image_embeds_m[:, 0, :]), dim=-1)
                image_feat_all = torch.cat([image_feat_m.t(), self.image_queue.clone().detach()], dim=1)
                text_output_m = self.text_encoder_m.bert(text.input_ids, attention_mask=text.attention_mask,
                                                         return_dict=True, mode='text')
                text_feat_m = F.normalize(self.text_proj_m(text_output_m.last_hidden_state[:, 0, :]), dim=-1)
                text_feat_all = torch.cat([text_feat_m.t(), self.text_queue.clone().detach()], dim=1)

                sim_i2t_m = image_feat_m @ text_feat_all / self.temp
                sim_t2i_m = text_feat_m @ image_feat_all / self.temp

                sim_targets = torch.zeros(sim_i2t_m.size()).to(image.device)
                sim_targets.fill_diagonal_(1)

                sim_i2t_targets = alpha * F.softmax(sim_i2t_m, dim=1) + (1 - alpha) * sim_targets
                sim_t2i_targets = alpha * F.softmax(sim_t2i_m, dim=1) + (1 - alpha) * sim_targets

            sim_i2t = image_feat @ text_feat_all / self.temp
            sim_t2i = text_feat @ image_feat_all / self.temp

            loss_i2t = -torch.sum(F.log_softmax(sim_i2t, dim=1) * sim_i2t_targets, dim=1).mean()
            loss_t2i = -torch.sum(F.log_softmax(sim_t2i, dim=1) * sim_t2i_targets, dim=1).mean()

            loss_ita = (loss_i2t + loss_t2i) / 2

            self._dequeue_and_enqueue(image_feat_m, text_feat_m)

            ###=================================###
            output_pos = self.text_encoder.bert(encoder_embeds=text_embeds,
                                                attention_mask=text.attention_mask,
                                                encoder_hidden_states=image_embeds,
                                                encoder_attention_mask=image_atts,
                                                return_dict=True,
                                                mode='fusion',
                                                )

            vl_embeddings = output_pos.last_hidden_state[:, 0, :]
            itm_labels = torch.as_tensor(itm_labels, dtype=torch.long).to(image.device)
            vl_output = self.itm_head(vl_embeddings)
            loss_itm = F.cross_entropy(vl_output, itm_labels)
            ##================= MLM ========================##    
            input_ids = text.input_ids.clone()
            labels = input_ids.clone()
            probability_matrix = torch.full(labels.shape, self.mlm_probability)
            input_ids_, labels = self.mask(input_ids, self.text_encoder.config.vocab_size, image.device, targets=labels,
                                           probability_matrix=probability_matrix)

            with torch.no_grad():
                logits_m = self.text_encoder_m(input_ids_,
                                               attention_mask=text.attention_mask,
                                               encoder_hidden_states=image_embeds_m,
                                               encoder_attention_mask=image_atts,
                                               return_dict=True,
                                               return_logits=True,
                                               )
            mlm_output = self.text_encoder(input_ids_,
                                           attention_mask=text.attention_mask,
                                           encoder_hidden_states=image_embeds,
                                           encoder_attention_mask=image_atts,
                                           return_dict=True,
                                           labels=labels,
                                           soft_labels=F.softmax(logits_m, dim=-1),
                                           alpha=alpha
                                           )
            loss_mlm = mlm_output.loss
            postokens_softlabels = self.pos_tokens_soft_labels.to(image.device)
            logits = mlm_output.logits
            if True in (labels > self.min_pos) & (labels < self.max_pos) & (labels != -100):
                pos_logits = logits[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)]
                batch_pos_soft_labels = postokens_softlabels[labels[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)]]
                loss_soft = -torch.sum(F.log_softmax(pos_logits, dim=1) * batch_pos_soft_labels, dim=-1).mean() * self.postoken_weight
            else:
                loss_soft = loss_mlm
            return loss_mlm, loss_soft, loss_ita, loss_itm

        elif mode == 'finetuning':
            with torch.no_grad():
                self.temp.clamp_(0.001, 0.5)
            image_embeds = self.visual_encoder(image)
            image_atts = torch.ones(image_embeds.size()[:-1], dtype=torch.long).to(image.device)
            image_feat = F.normalize(self.vision_proj(image_embeds[:, 0, :]), dim=-1)
            text_output = self.text_encoder.bert(text.input_ids, attention_mask=text.attention_mask,
                                                 return_dict=True, mode='text')
            text_embeds = text_output.last_hidden_state
            text_feat = F.normalize(self.text_proj(text_embeds[:, 0, :]), dim=-1)

            # get momentum features
            with torch.no_grad():
                self._momentum_update()
                image_embeds_m = self.visual_encoder_m(image)
                image_feat_m = F.normalize(self.vision_proj_m(image_embeds_m[:, 0, :]), dim=-1)
                image_feat_all = torch.cat([image_feat_m.t(), self.image_queue.clone().detach()], dim=1)
                text_output_m = self.text_encoder_m.bert(text.input_ids, attention_mask=text.attention_mask,
                                                         return_dict=True, mode='text')
                text_feat_m = F.normalize(self.text_proj_m(text_output_m.last_hidden_state[:, 0, :]), dim=-1)
                text_feat_all = torch.cat([text_feat_m.t(), self.text_queue.clone().detach()], dim=1)

                sim_i2t_m = image_feat_m @ text_feat_all / self.temp
                sim_t2i_m = text_feat_m @ image_feat_all / self.temp

                sim_targets = torch.zeros(sim_i2t_m.size()).to(image.device)
                sim_targets.fill_diagonal_(1)

                sim_i2t_targets = alpha * F.softmax(sim_i2t_m, dim=1) + (1 - alpha) * sim_targets
                sim_t2i_targets = alpha * F.softmax(sim_t2i_m, dim=1) + (1 - alpha) * sim_targets

            sim_i2t = image_feat @ text_feat_all / self.temp
            sim_t2i = text_feat @ image_feat_all / self.temp

            loss_i2t = -torch.sum(F.log_softmax(sim_i2t, dim=1) * sim_i2t_targets, dim=1).mean()
            loss_t2i = -torch.sum(F.log_softmax(sim_t2i, dim=1) * sim_t2i_targets, dim=1).mean()

            loss_ita = (loss_i2t + loss_t2i) / 2

            self._dequeue_and_enqueue(image_feat_m, text_feat_m)

            ###=================================###
            output_pos = self.text_encoder.bert(encoder_embeds=text_embeds,
                                                attention_mask=text.attention_mask,
                                                encoder_hidden_states=image_embeds,
                                                encoder_attention_mask=image_atts,
                                                return_dict=True,
                                                mode='fusion',
                                                )

            vl_embeddings = output_pos.last_hidden_state[:, 0, :]
            itm_labels = torch.as_tensor(itm_labels, dtype=torch.long).to(image.device)
            vl_output = self.itm_head(vl_embeddings)
            loss_itm = F.cross_entropy(vl_output, itm_labels)

            return loss_ita, loss_itm

    @torch.no_grad()
    def copy_params(self):
        for model_pair in self.model_pairs:
            for param, param_m in zip(model_pair[0].parameters(), model_pair[1].parameters()):
                param_m.data.copy_(param.data)  # initialize
                param_m.requires_grad = False  # not update by gradient    

    @torch.no_grad()
    def _momentum_update(self):
        for model_pair in self.model_pairs:
            for param, param_m in zip(model_pair[0].parameters(), model_pair[1].parameters()):
                param_m.data = param_m.data * self.momentum + param.data * (1. - self.momentum)

    @torch.no_grad()
    def _dequeue_and_enqueue(self, image_feat, text_feat, ):
        # gather keys before updating queue
        image_feats = concat_all_gather(image_feat)
        text_feats = concat_all_gather(text_feat)
        batch_size = image_feats.shape[0]

        ptr = int(self.queue_ptr)
        assert self.queue_size % batch_size == 0  # for simplicity

        # replace the keys at ptr (dequeue and enqueue)
        self.image_queue[:, ptr:ptr + batch_size] = image_feats.T
        self.text_queue[:, ptr:ptr + batch_size] = text_feats.T

        ptr = (ptr + batch_size) % self.queue_size  # move pointer

        self.queue_ptr[0] = ptr

    def mask(self, input_ids, vocab_size, device, targets=None, masked_indices=None, probability_matrix=None):
        if masked_indices is None:
            masked_indices = torch.bernoulli(probability_matrix).bool()

        masked_indices[input_ids == self.tokenizer.pad_token_id] = False
        masked_indices[input_ids == self.tokenizer.cls_token_id] = False

        if targets is not None:
            targets[~masked_indices] = -100  # We only compute loss on masked tokens

        # 80% of the time, we replace masked input tokens with tokenizer.mask_token ([MASK])
        indices_replaced = torch.bernoulli(torch.full(input_ids.shape, 0.8)).bool() & masked_indices
        input_ids[indices_replaced] = self.tokenizer.mask_token_id

        # 10% of the time, we replace masked input tokens with random word
        indices_random = torch.bernoulli(torch.full(input_ids.shape, 0.5)).bool() & masked_indices & ~indices_replaced
        random_words = torch.randint(vocab_size, input_ids.shape, dtype=torch.long).to(device)
        input_ids[indices_random] = random_words[indices_random]
        # The rest of the time (10% of the time) we keep the masked input tokens unchanged   
        if targets is not None:
            return input_ids, targets
        else:
            return input_ids


@torch.no_grad()
def concat_all_gather(tensor):
    """
    Performs all_gather operation on the provided tensors.
    *** Warning ***: torch.distributed.all_gather has no gradient.
    """
    tensors_gather = [torch.ones_like(tensor)
                      for _ in range(torch.distributed.get_world_size())]
    torch.distributed.all_gather(tensors_gather, tensor, async_op=False)

    output = torch.cat(tensors_gather, dim=0)
    return output


def get_mask_posnum_prob(start, end, epochs):
    step = (start - end) / epochs
    return [start - step * epoch for epoch in range(epochs)]
