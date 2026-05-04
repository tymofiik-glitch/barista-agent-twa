import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
POSTER_API_BASE = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")

def _poster_request(method: str, endpoint: str, params: dict = None, json_body: dict = None) -> dict:
    url = f"{POSTER_API_BASE}/{endpoint}"
    query = {"token": POSTER_TOKEN, **(params or {})}
    resp = requests.request(method, url, params=query, json=json_body, timeout=15)
    return resp.json()

def check_menu():
    print("--- Dishes ---")
    data = _poster_request("GET", "menu.getDishes")
    for d in data.get("response", []):
        name = d.get("dish_name") or d.get("name")
        price = d.get("price", {}).get("1", 0)
        print(f"ID {d.get('dish_id')}: {name} ({price} cop)")

    print("\n--- Products ---")
    data = _poster_request("GET", "menu.getProducts")
    for p in data.get("response", []):
        name = p.get("product_name") or p.get("name")
        price = p.get("price", {}).get("1", 0)
        print(f"ID {p.get('product_id')}: {name} ({price} cop)")

if __name__ == "__main__":
    check_menu()
