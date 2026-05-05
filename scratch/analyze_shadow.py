from PIL import Image

img = Image.open("img/ice_matcha.jpg")
width, height = img.size

darkest = 255
darkest_x = -1
darkest_y = -1

for x in range(400, width):
    for y in range(height):
        r, g, b = img.getpixel((x, y))
        avg = (r + g + b) // 3
        if avg < darkest:
            darkest = avg
            darkest_x = x
            darkest_y = y

print(f"Darkest pixel on right side (x>=400): {darkest} at ({darkest_x}, {darkest_y})")

img2 = Image.open("img/ice_latte.jpg")
w2, h2 = img2.size
darkest2 = 255
dx2 = -1
dy2 = -1
for x in range(400, w2):
    for y in range(h2):
        r, g, b = img2.getpixel((x, y))
        avg = (r + g + b) // 3
        if avg < darkest2:
            darkest2 = avg
            dx2 = x
            dy2 = y

print(f"Darkest pixel on right side of ice latte (x>=400): {darkest2} at ({dx2}, {dy2})")
