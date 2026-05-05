from PIL import Image

def get_cup_bbox(img):
    # Find bounding box of non-transparent pixels
    return img.getbbox()

def process_matcha_orange():
    # Load original images
    target_img = Image.open("menu images/seasonal drinks/Полунична матча.png").convert("RGBA")
    source_img = Image.open("menu images/seasonal drinks/Матча оранж.png").convert("RGBA")
    
    target_bbox = get_cup_bbox(target_img)
    source_bbox = get_cup_bbox(source_img)
    
    target_h = target_bbox[3] - target_bbox[1]
    source_h = source_bbox[3] - source_bbox[1]
    
    print(f"Target cup height: {target_h}")
    print(f"Source cup height: {source_h}")
    
    scale_factor = target_h / source_h
    print(f"Scale factor: {scale_factor}")
    
    # Scale the source image
    new_size = (int(source_img.width * scale_factor), int(source_img.height * scale_factor))
    resized_source = source_img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Recalculate bbox after resize
    new_bbox = get_cup_bbox(resized_source)
    
    # Create white 800x800 background
    final_img = Image.new("RGB", (800, 800), (255, 255, 255))
    
    # Paste centered
    paste_x = (800 - resized_source.width) // 2
    paste_y = (800 - resized_source.height) // 2
    
    # Adjustment: Usually these images have the cup bottom at a certain line. 
    # Let's align by center of the cup bbox.
    target_center_y = (target_bbox[1] + target_bbox[3]) // 2
    # In the target 800x800 crop (center crop), what was the cup's center y?
    # Claude used center crop: (1180 - 800)//2 = 190, (912 - 800)//2 = 56
    # So relative target center y was target_center_y - 56
    
    rel_target_center_y = target_center_y - 56
    
    # Now place resized_source so its new_bbox center y matches rel_target_center_y
    new_center_y = (new_bbox[1] + new_bbox[3]) // 2
    final_paste_y = rel_target_center_y - new_center_y
    
    final_img.paste(resized_source, (paste_x, final_paste_y), resized_source)
    
    final_img.save("img/matcha_orange_v2.jpg", quality=95)
    print("Saved img/matcha_orange_v2.jpg")

process_matcha_orange()
