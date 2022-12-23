## kuhn notes

It's necessary to switch to cuda11.1 before install torch.

```
conda create --name py37th18 -y python=3.7.11
conda activate py37th18

conda install ruamel_yaml
conda install pytorch==1.8.0 torchvision==0.9.0 torchaudio==0.8.0 cudatoolkit=11.1 -c pytorch -c conda-forge

pip install opencv-python 
pip install timm
pip install transformers==4.8.1

#install apex
export INSTALL_DIR=$PWD
git clone https://github.com/NVIDIA/apex.git
cd apex
python setup.py install --cuda_ext --cpp_ext

unset INSTALL_DIR
```



### AttributeError: module 'torch.distributed' has no attribute '_all_gather_base'

```
git clone https://github.com/NVIDIA/apex.git
cd apex
git checkout f3a960f80244cf9e80558ab30f7f7e8cbf03c0a0
python setup.py install --cuda_ext --cpp_ext
```





## Installation

Most of the requirements of this projects are exactly the same as [ALBEF](https://github.com/salesforce/ALBEF). If you have any problem of your environment, you should check their [issues page](https://github.com/salesforce/ALBEF/issues) first. Hope you will find the answer.

### Requirements
- apex 0.1
- timm 0.5.4
- yaml 0.2.5
- CUDA 11.1
- numpy 1.21.5
- pytorch 1.8.0
- torchvision 0.9.0
- transformers 4.8.1
- Python 3.7.11

```bash
conda create --name pevl -y python=3.7.11
conda activate pevl

conda install ruamel_yaml
conda install pytorch==1.8.0 torchvision==0.9.0 torchaudio==0.8.0 cudatoolkit=11.1 -c pytorch -c conda-forge

pip install opencv-python 
pip install timm
pip install transformers==4.8.1

export INSTALL_DIR=$PWD
#install apex
git clone https://github.com/NVIDIA/apex.git
cd apex
python setup.py install --cuda_ext --cpp_ext

unset INSTALL_DIR

```