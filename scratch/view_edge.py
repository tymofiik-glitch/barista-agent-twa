from PIL import Image
import base64
from io import BytesIO

img = Image.open("img/ice_matcha.jpg")
edge = img.crop((750, 400, 800, 450))
buffer = BytesIO()
edge.save(buffer, format="JPEG")
print("Base64 of edge (x=750..800, y=400..450):")
print(base64.b64encode(buffer.getvalue()).decode())

img2 = Image.open("img/ice_latte.jpg")
edge2 = img2.crop((750, 400, 800, 450))
buffer2 = BytesIO()
edge2.save(buffer2, format="JPEG")
print("Base64 of ice_latte edge (x=750..800, y=400..450):")
print(base64.b64encode(buffer2.getvalue()).decode())
