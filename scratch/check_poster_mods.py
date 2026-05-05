import os
import requests
from dotenv import load_dotenv

load_dotenv()
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
POSTER_API_BASE = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")

def fetch_poster_mods():
    url = f"{POSTER_API_BASE}/menu.getModifications"
    params = {"token": POSTER_TOKEN}
    resp = requests.get(url, params=params)
    groups = resp.json().get("response", [])
    
    for g in groups:
        print(f"\nGROUP: {g['mod_group_name']} (ID: {g['mod_group_id']})")
        for m in g.get("modifiers", []):
            print(f"  Modifier ID: {m['mod_id']} | Name: {m['mod_name']} | Price: {m['price']}")

if __name__ == "__main__":
    fetch_poster_mods()
