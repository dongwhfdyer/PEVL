# PEVL

This is the official PyTorch implementation of the EMNLP 2022 paper "[PEVL: Position-enhanced Pre-training and Prompt Tuning for Vision-language Models](https://arxiv.org/abs/2205.11169)".


## Quick links

- [PEVL](#pevl)
  - [Quick links](#quick-links)
  - [Overview](#overview)
  - [Install](#install)
  - [Pretraining Instructions](#pretraining-instructions)
  - [Second Stage Pre-training and Fine-tuning](#second-stage-pre-training-and-fine-tuning)
    - [Referring Expression Comprehension](#referring-expression-comprehension)
    - [Phrase Grounding](#phrase-grounding)
    - [Visual Relation Detection](#visual-relation-detection)
    - [Visual Commonsense Reasoning](#visual-commonsense-reasoning)
    - [Visual Question Answering](#visual-question-answering)
  - [Citations](#citations)
  - [Acknowledgement](#acknowledgement)


## Overview
PEVL reformulates discretized object positions and language in a unified language modeling framework, which facilitates explicit VL alignment during pre-training and enables flexible prompt tuning for various downstream tasks. PEVL shows impressive results of detector-free VLP models on position-sensitive tasks such as referring expression comprehension and phrase grounding, and also improves the performance on position-insensitive tasks with grounded inputs such as visual commomsense reasoning, visual relation detection and visual question answering(GQA). For more details, please see the paper [PEVL](https://arxiv.org/abs/2205.11169)

<img src="img.png" width="800">

## Install
Please refer to [INSTALL](INSTALL.md).

## Pretraining Instructions
Before pretraining, we initialize PEVL's weights with the parameters of **[ALBEF\[14M\]](https://storage.googleapis.com/sfr-pcl-data-research/ALBEF/ALBEF.pth)**

Our raw pretraining corpus is from **[Visual Commonsense Reasoning(VCR)](https://visualcommonsense.com/download/)** and **[MDETR](https://arxiv.org/abs/2104.12763)** that collects images from Flickr30k entities, COCO, Visual Genome datasets. 
- **[MDETR Data](https://zenodo.org/record/4729015/files/mdetr_annotations.tar.gz?download=1)**
- Download VCR data from the original websites **[VCR](https://visualcommonsense.com/download/)**.

## Second Stage Pre-training and Fine-tuning
You can download our first-stage pre-training model from **[pre-trained pevl](https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_pretrain.pth)**. We conduct second stage pre-training and fine-tuning for all downstream tasks.

### Referring Expression Comprehension
1. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/grounding.pth"> Second-stage pre-trained checkpoint </a> for position output tasks.
2. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_grounding_data.tar.gz"> Dataset json files for position output downstream tasks</a>.(the 'file_name' in each json file need to be changed to your own directory)
3. In configs/visual_grounding.yaml, set the paths for the json files.
4. Fine-tuning the model using 4 V100 GPUs:
```bash
##RefCOCO:
###train
python -m torch.distributed.launch --nproc_per_node=4 --master_port=12451 --use_env run_grounding_train.py --train 1 --pretrain 0 --test_dataset refcoco --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcoco --checkpoint grounding.pth --eval_step 500
###evaluate
python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py --train 0  --pretrain 0 --test_dataset refcoco --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcoco_test --checkpoint [Finetuned checkpoint]

##RefCOCOg
###train
python -m torch.distributed.launch --nproc_per_node=4 --master_port=12451 --use_env run_grounding_train.py --train 1  --pretrain 0 --test_dataset refcocog --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcocog --checkpoint grounding.pth --eval_step 500
###evaluate
python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py --train 0  --pretrain 0 --test_dataset refcocog --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcocog_test --checkpoint [Finetuned checkpoint]

##RefCOCO+
###train
python -m torch.distributed.launch --nproc_per_node=4 --master_port=12451 --use_env run_grounding_train.py --train 1  --pretrain 0 --test_dataset refcocop --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcocop --checkpoint grounding.pth --eval_step 500
###evaluate
python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py --train 0  --pretrain 0 --test_dataset refcocop --config ./configs/visual_grounding.yaml --output_dir ./output/visual_grounding/refcocop_test --checkpoint [Finetuned checkpoint]

```

### Phrase Grounding
1. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/grounding.pth"> Second stage pre-trained checkpoint </a> for position output tasks.
2. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_grounding_data.tar.gz"> Dataset json files for position output downstream tasks</a>.
3. In configs/visual_grounding.yaml, set the paths for the json files.
4. Fine-tuning the model using 8 V100 GPUs:
```bash
##Flickr30k
###train
python -m torch.distributed.launch --nproc_per_node=8 --master_port=12451 --use_env run_grounding_train.py --train 1 --pretrain 0 --test_dataset flickr --config ./configs/visual_grounding.yaml --output_dir ./output/phrase_grounding --checkpoint grounding.pth --eval_step 500
###evaluate
python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py --train 0 --pretrain 0 --test_dataset flickr --config ./configs/visual_grounding.yaml --output_dir ./output/phrase_grounding --checkpoint  [Finetuned checkpoint]

```

### Visual Relation Detection (VRD)
1. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/vrd.pth"> Second stage pre-trained checkpoint </a> for visual relation detection.
2. Download PEVL's VRD dataset json files for visual relation detection from <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_vrd.tar.gz"> pevl_vrd</a> and images for VRD from <a href="https://visualgenome.org/api/v0/api_home.html"> Visual Genome </a>. 
3. In configs/vrd.yaml, set the paths for the json files.
4. Fine-tuning the model using 8 V100 GPUs:
```bash
##for finetuning on visual genome:
python -m torch.distributed.launch --nproc_per_node=8 --master_port=12451 --use_env run_vrd_train.py --train 1 --pretrain 0 --mode finetune --config ./configs/vrd.yaml --output_dir ./output/vrd --checkpoint vrd.pth

##for evaluation on visual genome:
python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_vrd_train.py --train 0 --pretrain 0 --config ./configs/vrd.yaml  --checkpoint [Finetuned checkpoint]
```


### Visual Commonsense Reasoning (VCR)
1. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_vcr_ssp.pth"> Second-stage pre-trained checkpoint </a> for visual commonsense reasoning.
2. <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_vcr_finetune.pth"> Fine-tuned checkpoint </a> for visual commonsense reasoning.
3. Download PEVL's VCR dataset json files from <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_vcr.tar.gz"> vcr data </a> and images for visual commonsense reasoning from original websites <a href="https://visualcommonsense.com/download/"> VCR </a>.
4. In configs/vcr.yaml, set the paths for the json files and vcr images.

### Visual Question Answering (GQA)
1. Download PEVL's GQA dataset json files from <a href="https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_gqa_data.tar.gz"> pevl_gqa</a> and images for GQA from original websites <a href="https://cs.stanford.edu/people/dorarad/gqa/download.html"> GQA </a>.
2. In configs/gqa.yaml, set the paths for the json files and gqa images.


## Citations
If you find this project helps your research, please kindly consider citing our paper in your publications.
```
@inproceedings{yao2022pevl,
  title={PEVL: Position-enhanced Pre-training and Prompt Tuning for Vision-language Models},
  author={Yao, Yuan and Chen, Qianyu and Zhang, Ao and Ji, Wei and Liu, Zhiyuan and Chua, Tat-Seng and Sun, Maosong},
  booktitle={Proceedings of EMNLP},
  year={2022}
}
```

## Acknowledgement
The implementation of PEVL relies on resources from <a href="https://github.com/salesforce/ALBEF">ALBEF</a> especially, <a href="https://github.com/huggingface/transformers">Huggingface Transformers</a>, and <a href="https://github.com/rwightman/pytorch-image-models/tree/master/timm">timm</a>. We thank the original authors for their open-sourcing and excellent work.
