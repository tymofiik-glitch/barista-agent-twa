from PIL import Image
import os

def get_solid_cup_height(img):
    # Convert to grayscale and threshold to find the solid cup body
    # (ignoring faint shadows)
    gray = img.convert("L")
    alpha = img.split()[3]
    
    # We'll use a combination of alpha and darkness
    # Solid cup body usually has alpha > 200
    top = -1
    bottom = -1
    
    pixels = alpha.load()
    w, h = img.size
    
    for y in range(h):
        for x in range(w):
            if pixels[x, y] > 200:
                if top == -1: top = y
                bottom = y
                break
    
    return bottom - top, top, bottom

def normalize_seasonal_drinks():
    mapping = {
        'ice_latte': 'айс лате.png',
        'ice_matcha': 'айс матча лате.png',
        'ice_capuorange': 'Айс капуоранж.png',
        'capuorange_juice': 'Капуоранж сік.png',
        'espresso_tonic': 'Еспресо тонік.png',
        'matcha_orange': 'Матча оранж.png',
        'strawberry_matcha': 'Полунична матча.png'
    }
    
    # Target height for the SOLID body of the cup
    target_solid_height = 680 
    
    for key, filename in mapping.items():
        src_path = os.path.join("menu images/seasonal drinks", filename)
        if not os.path.exists(src_path): continue
            
        img = Image.open(src_path).convert("RGBA")
        solid_h, top_y, bot_y = get_solid_cup_height(img)
        
        scale = target_solid_height / solid_h
        
        new_size = (int(img.width * scale), int(img.height * scale))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Measure solid body in resized image
        new_solid_h, new_top_y, new_bot_y = get_solid_cup_height(resized)
        
        final = Image.new("RGB", (800, 800), (255, 255, 255))
        
        # Center horizontally
        # We need to find the horizontal center of the solid body too
        gray_resized = resized.convert("L")
        alpha_resized = resized.split()[3]
        pix_a = alpha_resized.load()
        
        left_x = -1
        right_x = -1
        for x in range(resized.width):
            for y in range(resized.height):
                if pix_a[x, y] > 200:
                    if left_x == -1: left_x = x
                    right_x = x
                    break
        
        solid_center_x = (left_x + right_x) // 2
        solid_center_y = (new_top_y + new_bot_y) // 2
        
        paste_x = 400 - solid_center_x
        paste_y = 400 - solid_center_y
        
        final.paste(resized, (paste_x, paste_y), resized)
        
        # Save as v6
        out_name = f"img/{key}_v6.jpg"
        final.save(out_name, quality=95)
        print(f"Saved {out_name} (solid height: {new_solid_h})")

normalize_seasonal_drinks()
