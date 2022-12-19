linkList=(
"https://developer.download.nvidia.com/compute/cuda/11.1.1/local_installers/cuda_11.1.1_455.32.00_linux.run"
"https://thunlp.oss-cn-qingdao.aliyuncs.com/grounding.pth"
"https://thunlp.oss-cn-qingdao.aliyuncs.com/pevl_grounding_data.tar.gz"
)


for link in ${linkList[@]}; do
    flag=0
    while true; do
      if [ $flag -eq 0 ]; then
        echo "Downloading $link"
        wget -c $link
        if [ $? -eq 0 ]; then
          flag=1
        fi
      else
        break
      fi
      sleep 2
    done
done

mv cuda_11.1.1_455.32.00_linux.run ~/kuhn/cuda-cudnn/
tar -zxvf pevl_grounding_data.tar.gz

