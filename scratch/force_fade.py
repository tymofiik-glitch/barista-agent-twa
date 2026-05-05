from PIL import Image, ImageDraw

def force_white_fade(input_path, output_path):
    # Open the existing RGB image
    img = Image.open(input_path).convert("RGB")
    width, height = img.size
    
    # Create a pure white image
    white_bg = Image.new("RGB", (width, height), (255, 255, 255))
    
    # Create a mask for blending
    mask = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(mask)
    
    # The cup is in the center (x=400).
    # The shadow extends to the right. We want to start fading to white at x=500
    # and be completely white by x=650.
    fade_start = 500
    fade_end = 650
    
    for x in range(width):
        if x <= fade_start:
            alpha = 255  # 100% original image
        elif x >= fade_end:
            alpha = 0    # 100% white background
        else:
            ratio = (x - fade_start) / (fade_end - fade_start)
            # Smooth fade
            alpha = int(255 * (1 - ratio))
            
        draw.line([(x, 0), (x, height)], fill=alpha)
        
    # Composite the image with the white background using the mask
    result = Image.composite(img, white_bg, mask)
    
    result.save(output_path, quality=95)
    print(f"Force faded {output_path}")

force_white_fade("img/ice_matcha_v2.jpg", "img/ice_matcha_v3.jpg")
