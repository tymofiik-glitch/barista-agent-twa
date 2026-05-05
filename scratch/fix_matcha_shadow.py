from PIL import Image, ImageDraw

def fix_shadow(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")
    width, height = img.size
    
    r, g, b, a = img.split()
    mask = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(mask)
    
    # Claude cropped center 800x800. Right edge of crop is at x=990
    crop_right = (width - 800) // 2 + 800  # 190 + 800 = 990
    
    # Let's fade out completely before x=980
    fade_end = 980
    fade_start = 650
    
    for x in range(fade_start, width):
        if x >= fade_end:
            alpha_val = 0
        else:
            ratio = (x - fade_start) / (fade_end - fade_start)
            # smooth step or ease out
            alpha_val = int(255 * (1 - ratio**1.5))
        draw.line([(x, 0), (x, height)], fill=alpha_val)
        
    a_new = Image.eval(a, lambda px: px)
    mask_pixels = mask.load()
    a_pixels = a_new.load()
    
    for y in range(height):
        for x in range(width):
            if x >= fade_start:
                a_pixels[x, y] = int((a_pixels[x, y] * mask_pixels[x, y]) / 255)
                
    img = Image.merge("RGBA", (r, g, b, a_new))
    
    left = (width - 800) // 2
    top = (height - 800) // 2
    right = left + 800
    bottom = top + 800
    
    img_cropped = img.crop((left, top, right, bottom))
    
    bg = Image.new("RGB", (800, 800), (255, 255, 255))
    bg.paste(img_cropped, (0, 0), img_cropped)
    
    bg.save(output_path, quality=95)
    print(f"Fixed {output_path}")

fix_shadow("menu images/seasonal drinks/айс матча лате.png", "img/ice_matcha.jpg")
