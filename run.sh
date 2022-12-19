torchrun --nproc_per_node=2 run_grounding_train.py\
 --train 1 --pretrain 0 --test_dataset flickr --config configs/visual_grounding.yaml\
  --output_dir output/phrase_grounding --checkpoint pretrain/grounding.pth --eval_step 500