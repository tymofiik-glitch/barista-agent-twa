from PIL import Image

img = Image.open("img/ice_matcha.jpg")
width, height = img.size

def get_darkest(img, start_x):
    darkest = 255
    dx = -1
    dy = -1
    for x in range(start_x, width):
        for y in range(height):
            r, g, b = img.getpixel((x, y))
            avg = (r + g + b) // 3
            if avg < darkest:
                darkest = avg
                dx = x
                dy = y
    return darkest, dx, dy

print(f"Matcha >600: {get_darkest(img, 600)}")
print(f"Matcha >700: {get_darkest(img, 700)}")
print(f"Matcha >750: {get_darkest(img, 750)}")

img2 = Image.open("img/ice_latte.jpg")
print(f"Latte >600: {get_darkest(img2, 600)}")
print(f"Latte >700: {get_darkest(img2, 700)}")
print(f"Latte >750: {get_darkest(img2, 750)}")
