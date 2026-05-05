from PIL import Image

img = Image.open("menu images/seasonal drinks/айс матча лате.png").convert("RGBA")
width, height = img.size

# Let's check the alpha values on the rightmost column
right_edge_alphas = [img.getpixel((width-1, y))[3] for y in range(height)]
max_alpha = max(right_edge_alphas)
print(f"Max alpha on the right edge: {max_alpha}")

# Let's check the right edge of ice_latte
img2 = Image.open("menu images/seasonal drinks/айс лате.png").convert("RGBA")
width2, height2 = img2.size
right_edge_alphas2 = [img2.getpixel((width2-1, y))[3] for y in range(height2)]
print(f"Max alpha on the right edge of ice latte: {max(right_edge_alphas2)}")
