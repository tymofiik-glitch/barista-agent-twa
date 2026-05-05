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
    
    target_cup_height = 650  # pixels in the final 800x800 image
    
    for key, filename in mapping.items():
        src_path = os.path.join("menu images/seasonal drinks", filename)
        if not os.path.exists(src_path):
            print(f"Skipping {src_path} - not found")
            continue
            
        img = Image.open(src_path).convert("RGBA")
        bbox = img.getbbox()
        if not bbox:
            print(f"Empty image {src_path}")
            continue
            
        cup_h = bbox[3] - bbox[1]
        scale = target_cup_height / cup_h
        
        new_size = (int(img.width * scale), int(img.height * scale))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # New bbox after resize
        new_bbox = resized.getbbox()
        
        # Create white 800x800
        final = Image.new("RGB", (800, 800), (255, 255, 255))
        
        # Paste centered horizontally, and slightly below center vertically
        # Usually cups should be grounded or slightly centered.
        # Let's align by the bottom of the cup being at y=720 (leaving 80px bottom margin)
        # Or just center the cup bbox in the middle of 800x800
        
        cup_center_x = (new_bbox[0] + new_bbox[2]) // 2
        cup_center_y = (new_bbox[1] + new_bbox[3]) // 2
        
        paste_x = 400 - cup_center_x
        paste_y = 400 - cup_center_y
        
        final.paste(resized, (paste_x, paste_y), resized)
        
        # Save as v4 to be sure
        out_name = f"img/{key}_v4.jpg"
        final.save(out_name, quality=95)
        print(f"Saved {out_name}")

normalize_seasonal_drinks()
