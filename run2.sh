/home/zx/miniconda3/envs/th13/bin/torchrun --nproc_per_node=2 --master_port=12451  run_grounding_train.py\
 --train 1 --pretrain 0 --test_dataset flickr --config configs/visual_grounding.yaml\
  --output_dir output/phrase_grounding --checkpoint pretrain/grounding.pth --eval_step 500

# python -m torch.distributed.launch --nproc_per_node=1 --master_port=12451 --use_env run_grounding_train.py\
#  --train 0 --pretrain 0 --test_dataset flickr --config ./configs/visual_grounding.yaml\
#   --output_dir ./output/phrase_grounding --checkpoint  [Finetuned checkpoint]