from PIL import Image

def measure_cup(path):
    img = Image.open(path).convert("L")
    width, height = img.size
    
    # Threshold to find the cup (darker than white background)
    # Background is white (255). Let's use 240 as threshold.
    top = -1
    bottom = -1
    
    for y in range(height):
        for x in range(width):
            if img.getpixel((x, y)) < 240:
                if top == -1: top = y
                bottom = y
                break
    
    return bottom - top

print(f"Matcha v5 cup height: {measure_cup('img/ice_matcha_v5.jpg')}")
print(f"Strawberry v5 cup height: {measure_cup('img/strawberry_matcha_v5.jpg')}")
print(f"Espresso Tonic v5 cup height: {measure_cup('img/espresso_tonic_v5.jpg')}")
