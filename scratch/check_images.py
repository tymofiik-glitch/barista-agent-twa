from PIL import Image
import os

def check_img(path):
    if os.path.exists(path):
        img = Image.open(path)
        print(f"{path}: size={img.size}, mode={img.mode}")
    else:
        print(f"{path} not found")

check_img("menu images/seasonal drinks/айс матча лате.png")
check_img("menu images/seasonal drinks/айс лате.png")
check_img("img/ice_matcha.jpg")
check_img("img/ice_latte.jpg")
