import torch
from torch import nn
import torch.nn.functional as F
import numpy as np
from functools import partial
from models.vit import VisionTransformer, interpolate_pos_embed
from models.xbert import BertConfig, BertForMaskedLM


class PEVL_Grounding(nn.Module):
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

        self.visual_encoder = VisionTransformer(  # if the input image is 512x512, patch_size=16, embed_dim=768, depth=12, then the output's shape is (B, (512/16)^2+1, 768)
            img_size=config['image_res'], patch_size=16, embed_dim=768, depth=12, num_heads=12,
            mlp_ratio=4, qkv_bias=True, norm_layer=partial(nn.LayerNorm, eps=1e-6))

        if init_deit:  # False
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

        self.image_queue = nn.functional.normalize(self.image_queue, dim=0)  # shape: (embed_dim, queue_size) (256, 65536)
        self.text_queue = nn.functional.normalize(self.text_queue, dim=0)  # shape: (embed_dim, queue_size) (256, 65536)

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

        # Before running this line below, we already get a matrix with shape (512, 512).
        # It's a symmetric matrix. The diagonal is 0. The value of the matrix is the distance between the row index and the column index.
        a = np.exp(-self.exp_decay_ratio * a)
        # Then we will get the dict. the shape is [512, 512]
        pos_tokens_simmartix_dict = {}
        pos_token = [f'[pos_{x}]' for x in range(512)]
        for x, y in zip(pos_token, a):
            pos_tokens_simmartix_dict[x] = y  # pos_tokens_simmartix_dict's data is the same as the matrix a. The key is the exponent of the matrix a.
        # Now, we are trying to transform the postoken.
        # when the number of position tokens are different from 512, you can change 800 to the index of Maximum of them. (In our case,it's the index of '##' )
        t = torch.randn((800, 30522)).fill_(0)
        for x in postoken_dict.keys():
            postoken_vector = pos_tokens_simmartix_dict[x]
            index = postoken_dict[x]
            t[index, self.min_pos + 1:self.max_pos] = torch.Tensor(postoken_vector / np.sum(postoken_vector))  # min_pos: 205 max_pos: 718 postoken_vector‘s shape is (512,).
        # t's shape is (800, 30522). But many rows are all 0.
        # The rows with all 0 are the position tokens that are not in the postoken_dict.
        # About the column, the first 205 are all 0. The next 513 are the probability of the position tokens. The last 30004 are all 0.
        self.pos_tokens_soft_labels = t

        # define loss weight for position tokens' ordering-aware objective
        self.postoken_weight = config['postoken_temp']

    def forward(self, image, text, alpha=0, mode='pretrain'):
        if mode == 'pretrain':
            with torch.no_grad():
                self.temp.clamp_(0.001, 0.5)
            image_embeds = self.visual_encoder(image) # if the input image is 512x512, patch_size=16, embed_dim=768, depth=12, then the output's shape is (B, (512/16)^2+1, 768)
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
            # forward the positve image-text pair
            output_pos = self.text_encoder.bert(encoder_embeds=text_embeds,
                                                attention_mask=text.attention_mask,
                                                encoder_hidden_states=image_embeds,
                                                encoder_attention_mask=image_atts,
                                                return_dict=True,
                                                mode='fusion',
                                                )
            with torch.no_grad():
                bs = image.size(0)
                weights_i2t = F.softmax(sim_i2t[:, :bs], dim=1)
                weights_t2i = F.softmax(sim_t2i[:, :bs], dim=1)

                weights_i2t.fill_diagonal_(0)
                weights_t2i.fill_diagonal_(0)

                # select a negative image for each text
            image_embeds_neg = []
            for b in range(bs):
                neg_idx = torch.multinomial(weights_t2i[b], 1).item()
                image_embeds_neg.append(image_embeds[neg_idx])
            image_embeds_neg = torch.stack(image_embeds_neg, dim=0)

            # select a negative text for each image
            text_embeds_neg = []
            text_atts_neg = []
            for b in range(bs):
                neg_idx = torch.multinomial(weights_i2t[b], 1).item()
                text_embeds_neg.append(text_embeds[neg_idx])
                text_atts_neg.append(text.attention_mask[neg_idx])
            text_embeds_neg = torch.stack(text_embeds_neg, dim=0)
            text_atts_neg = torch.stack(text_atts_neg, dim=0)

            text_embeds_all = torch.cat([text_embeds, text_embeds_neg], dim=0)
            text_atts_all = torch.cat([text.attention_mask, text_atts_neg], dim=0)

            image_embeds_all = torch.cat([image_embeds_neg, image_embeds], dim=0)
            image_atts_all = torch.cat([image_atts, image_atts], dim=0)

            output_neg = self.text_encoder.bert(encoder_embeds=text_embeds_all,
                                                attention_mask=text_atts_all,
                                                encoder_hidden_states=image_embeds_all,
                                                encoder_attention_mask=image_atts_all,
                                                return_dict=True,
                                                mode='fusion',
                                                )

            vl_embeddings = torch.cat([output_pos.last_hidden_state[:, 0, :], output_neg.last_hidden_state[:, 0, :]], dim=0)
            vl_output = self.itm_head(vl_embeddings)

            itm_labels = torch.cat([torch.ones(bs, dtype=torch.long), torch.zeros(2 * bs, dtype=torch.long)],
                                   dim=0).to(image.device)

            vl_output = F.softmax(vl_output, dim=1)

            loss_itm = F.cross_entropy(vl_output, itm_labels)

            ##================= GMLM ========================##       
            input_ids = text.input_ids.clone()
            labels = input_ids.clone()
            probability_matrix = torch.full(labels.shape, self.mlm_probability)
            input_ids, labels, _ = self.postoken_mask(input_ids, self.text_encoder.config.vocab_size, \
                                                      image.device, 0, targets=labels,
                                                      probability_matrix=probability_matrix)
            with torch.no_grad():
                logits_m = self.text_encoder_m(input_ids,
                                               attention_mask=text.attention_mask,
                                               encoder_hidden_states=image_embeds_m,
                                               encoder_attention_mask=image_atts,
                                               return_dict=True,
                                               return_logits=True,
                                               )

            mlm_output = self.text_encoder(input_ids,
                                           attention_mask=text.attention_mask,
                                           encoder_hidden_states=image_embeds,
                                           encoder_attention_mask=image_atts,
                                           return_dict=True,
                                           labels=labels,
                                           soft_labels=F.softmax(logits_m, dim=-1),
                                           alpha=alpha
                                           )

            postokens_softlabels = self.pos_tokens_soft_labels.to(image.device)
            logits = mlm_output.logits

            pos_logits = logits[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)]
            batch_pos_soft_labels = postokens_softlabels[labels[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)]]
            loss_soft = -torch.sum(F.log_softmax(pos_logits, dim=1) * batch_pos_soft_labels, dim=-1).mean() * self.postoken_weight

            return loss_soft, loss_ita, loss_itm

        elif mode == 'finetune':
            # if the input image is 512x512, patch_size=16, embed_dim=768, depth=12, then the output's shape is (B, (512/16)^2+1, 768)
            image_embeds = self.visual_encoder(image)  # image: (bs, 3, imgsiz, imgsiz) image_embeds: (bs, seq_len, dim)
            image_atts = torch.ones(image_embeds.size()[:-1], dtype=torch.long).to(image.device) # (bs, seq_len) All elements are 1

            ##================= GMLM ========================##       
            input_ids = text.input_ids.clone()
            labels = input_ids.clone()
            probability_matrix = torch.full(labels.shape, self.mlm_probability)  # (bs, sentence_len)
            input_ids, labels, _ = self.postoken_mask(input_ids, targets=labels, probability_matrix=probability_matrix) # These three tensor's shape is (bs, sentence_len).

            mlm_output = self.text_encoder(input_ids, # (bs, sentence_len)
                                           attention_mask=text.attention_mask, # (bs, sentence_len)
                                           encoder_hidden_states=image_embeds, # (bs, seq_len, dim)
                                           encoder_attention_mask=image_atts, # (bs, seq_len)
                                           return_dict=True,
                                           labels=labels, ) # (bs, sentence_len)

            postokens_softlabels = self.pos_tokens_soft_labels.to(image.device) # (800, vocab_size)
            logits = mlm_output.logits # (bs, sentence_len, vocab_size)
            pos_logits = logits[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)] # get the logits of the masked tokens
            batch_pos_soft_labels = postokens_softlabels[labels[(labels > self.min_pos) & (labels < self.max_pos) & (labels != -100)]]
            loss_soft = -torch.sum(F.log_softmax(pos_logits, dim=1) * batch_pos_soft_labels, dim=-1).mean()

            return loss_soft

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
    def _dequeue_and_enqueue(self, image_feat, text_feat):
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

    def postoken_mask(self, input_ids, targets=None, masked_indices=None, probability_matrix=None):
        if masked_indices is None:
            masked_indices = torch.bernoulli(probability_matrix).bool()
        masked_indices[:] = False

        # mask all position tokens
        masked_indices[(input_ids > self.min_pos) & (input_ids < self.max_pos)] = True
        if targets is not None:
            targets[~masked_indices] = -100  # We only compute loss on masked tokens
        input_ids[masked_indices] = self.tokenizer.mask_token_id
        return input_ids, targets, masked_indices


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
