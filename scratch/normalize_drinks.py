from PIL import Image
import os

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
    
    # Let's increase the size. 
    # If the canvas is 800x800, 750px height for the cup is a good "large" size.
    target_cup_height = 760 
    
    for key, filename in mapping.items():
        src_path = os.path.join("menu images/seasonal drinks", filename)
        if not os.path.exists(src_path):
            continue
            
        img = Image.open(src_path).convert("RGBA")
        bbox = img.getbbox()
        if not bbox: continue
            
        cup_h = bbox[3] - bbox[1]
        scale = target_cup_height / cup_h
        
        new_size = (int(img.width * scale), int(img.height * scale))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        
        new_bbox = resized.getbbox()
        
        final = Image.new("RGB", (800, 800), (255, 255, 255))
        
        cup_center_x = (new_bbox[0] + new_bbox[2]) // 2
        cup_center_y = (new_bbox[1] + new_bbox[3]) // 2
        
        paste_x = 400 - cup_center_x
        # Let's shift it slightly down to look more natural, or just center.
        # Top ones in screenshot look centered or slightly grounded.
        paste_y = 400 - cup_center_y
        
        final.paste(resized, (paste_x, paste_y), resized)
        
        # Save as v5
        out_name = f"img/{key}_v5.jpg"
        final.save(out_name, quality=95)
        print(f"Saved {out_name}")

normalize_seasonal_drinks()
