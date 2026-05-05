import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
POSTER_API_BASE = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")

def check_dish_mods(dish_id):
    url = f"{POSTER_API_BASE}/menu.getDish"
    params = {"token": POSTER_TOKEN, "dish_id": dish_id}
    resp = requests.get(url, params=params)
    data = resp.json().get("response", {})
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    # 1530 is "Круасан солодкий"
    check_dish_mods(1530)
