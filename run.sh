python -m torch.distributed.launch --master_port=12451 --use_env  --nproc_per_node=2 run_grounding_train.py\
 --train 1 --pretrain 0 --test_dataset flickr --config configs/visual_grounding.yaml\
 --output_dir output/phrase_grounding --checkpoint pretrain/grounding.pth --eval_step 500


#CUDA_VISIBLE_DEVICES=0,1 /home/zx/miniconda3/envs/py37th18/bin/torchrun --nproc_per_node=2 run_grounding_train.py\
# --train 1 --pretrain 0 --test_dataset flickr --config configs/visual_grounding.yaml\
#  --output_dir output/phrase_grounding --checkpoint pretrain/grounding.pth --eval_step 500

# python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py\
#  --train 0 --pretrain 0 --test_dataset flickr --config ./configs/visual_grounding.yaml\
#   --output_dir ./output/phrase_grounding --checkpoint  [Finetuned checkpoint]