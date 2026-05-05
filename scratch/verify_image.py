from PIL import Image
import os

img = Image.open("img/ice_matcha_v2.jpg")
width, height = img.size

# Check the darkest pixel near the right edge
darkest = 255
dx, dy = -1, -1

for x in range(700, width):
    for y in range(height):
        r, g, b = img.getpixel((x, y))
        avg = (r+g+b)//3
        if avg < darkest:
            darkest = avg
            dx, dy = x, y

print(f"Darkest pixel for x>=700: {darkest} at ({dx}, {dy})")

# Let's also check the actual original file from menu images
img_orig = Image.open("menu images/seasonal drinks/айс матча лате.png").convert("RGBA")
print(f"Original size: {img_orig.size}")

# Check original darkest on the right side
darkest_orig = 255
for x in range(1000, img_orig.size[0]):
    for y in range(img_orig.size[1]):
        r, g, b, a = img_orig.getpixel((x, y))
        if a > 0:
            avg = (r+g+b)//3
            # adjust avg with background white
            bg_avg = 255 - int((255 - avg) * (a / 255.0))
            if bg_avg < darkest_orig:
                darkest_orig = bg_avg

print(f"Original darkest pixel for x>=1000: {darkest_orig}")
