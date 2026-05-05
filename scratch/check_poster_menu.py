import os
import requests
from dotenv import load_dotenv

load_dotenv()
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
POSTER_API_BASE = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")

def fetch_poster_menu():
    url = f"{POSTER_API_BASE}/menu.getProducts"
    params = {"token": POSTER_TOKEN}
    resp = requests.get(url, params=params)
    products = resp.json().get("response", [])
    
    url_dishes = f"{POSTER_API_BASE}/menu.getDishes"
    resp_dishes = requests.get(url_dishes, params=params)
    dishes = resp_dishes.json().get("response", [])
    
    print("--- PRODUCTS ---")
    for p in products:
        print(f"ID: {p['product_id']} | Name: {p['product_name']} | Price: {p['price'].get('1', '0')}")
        
    print("\n--- DISHES ---")
    for d in dishes:
        print(f"ID: {d['dish_id']} | Name: {d['dish_name']} | Price: {d['price'].get('1', '0')}")

if __name__ == "__main__":
    fetch_poster_menu()
