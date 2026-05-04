import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("POSTER_TOKEN")
base = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")

def inspect_cappuccino():
    print("=== АНАЛІЗ КАПУЧИНО (ID: 7) ===\n")
    
    try:
        # Отримуємо деталі конкретного товару
        r = requests.get(f"{base}/menu.getProduct", params={"token": token, "product_id": 7}, timeout=10).json()
        product = r.get("response", {})
        
        if not product:
            print("❌ Не вдалося знайти Капучино з ID 7.")
            return

        print(f"Назва: {product.get('product_name')}")
        
        # Перевіряємо модифікатори
        mods = product.get("group_modifications", [])
        if mods:
            print(f"\n✅ Знайдено групові модифікатори ({len(mods)}):")
            for g in mods:
                print(f"  Група: {g.get('name')}")
                for m in g.get("modifications", []):
                    print(f"    - {m.get('name')} (ID: {m.get('id')}) +{int(m.get('price', 0))/100} грн")
        else:
            print("\nℹ️ Групових модифікаторів не знайдено.")

    except Exception as e:
        print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    inspect_cappuccino()
