from PIL import Image

img = Image.open("img/ice_matcha.jpg")
width, height = img.size

# Check the pixel colors on the right side
colors = [img.getpixel((width-10, y)) for y in range(400, 500)]
print("Colors on right edge (x=790) around y=450:", colors[:5])
