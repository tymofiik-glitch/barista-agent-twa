from PIL import Image, ImageOps

def process_img(in_path, out_path, bg_color=(255, 255, 255)):
    # Open the image
    img = Image.open(in_path).convert("RGBA")
    
    # We want to output a square 800x800 JPG
    # Let's see the bounding box of the non-zero alpha
    bbox = img.getbbox()
    print(f"Original bounding box for {in_path}: {bbox}")
    
    # Let's just create a thumbnail that fits into 800x800, maintaining aspect ratio
    # First, create a new white background
    bg = Image.new("RGB", (800, 800), bg_color)
    
    # We can crop the image to its bbox first
    cropped = img.crop(bbox)
    
    # Now resize cropped to fit within 700x700 to leave some padding
    cropped.thumbnail((700, 700), Image.Resampling.LANCZOS)
    
    # Paste the resized image onto the center of the white background
    offset_x = (800 - cropped.width) // 2
    offset_y = (800 - cropped.height) // 2
    
    # Actually, we might need to match the ice latte. Let's do the same for ice latte to see if they look consistent.
    bg.paste(cropped, (offset_x, offset_y), cropped)
    
    bg.save(out_path, quality=95)
    print(f"Saved {out_path}")

process_img("menu images/seasonal drinks/айс матча лате.png", "img/ice_matcha_test.jpg")
process_img("menu images/seasonal drinks/айс лате.png", "img/ice_latte_test.jpg")
