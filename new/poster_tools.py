from __future__ import annotations
import os
import requests
from difflib import get_close_matches
from dotenv import load_dotenv

# === Poster Configuration ===
load_dotenv()
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
POSTER_API_BASE = os.getenv("POSTER_API_BASE", "https://take-a-break-ai.joinposter.com/api")
DEFAULT_SPOT_ID = 1


def _poster_request(method: str, endpoint: str, params: dict = None, json_body: dict = None) -> dict:
    url = f"{POSTER_API_BASE}/{endpoint}"
    query = {"token": POSTER_TOKEN, **(params or {})}
    try:
        resp = requests.request(method, url, params=query, json=json_body, timeout=15)
        data = resp.json()
    except requests.RequestException as e:
        return {"error": f"Network error: {e}"}
    except ValueError:
        return {"error": f"Invalid JSON in response (HTTP {resp.status_code}): {resp.text[:200]}"}

    if "error" in data:
        err = data["error"]
        msg = data.get("message", "") if isinstance(data, dict) else ""
        return {"error": f"Poster API error {err}: {msg}"}
    return data


def _normalize_item(p: dict, kind: str) -> dict:
    name = (p.get("product_name") or p.get("dish_name") or p.get("name") or "—").strip()
    pid = p.get("product_id") or p.get("dish_id") or p.get("id")
    price_field = p.get("price", {})
    price = 0.0

    if isinstance(price_field, dict) and price_field:
        raw = price_field.get(str(DEFAULT_SPOT_ID)) or next(
            (v for v in price_field.values() if v and str(v) not in ("0", "0.00")),
            None,
        )
        try:
            price = float(raw) / 100 if raw is not None else 0.0
        except (TypeError, ValueError):
            price = 0.0
    elif isinstance(price_field, (int, float, str)) and price_field not in (None, ""):
        try:
            price = float(price_field) / 100
        except (TypeError, ValueError):
            price = 0.0

    if price == 0.0:
        for fallback_key in ("mod_price", "price_netto", "cost_netto", "cost", "fiscal_price"):
            v = p.get(fallback_key)
            if v:
                try:
                    price = float(v) / 100
                    break
                except (TypeError, ValueError):
                    pass

    return {"id": pid, "name": name, "price": price, "type": kind}


def get_menu_items() -> list[dict]:
    result: list[dict] = []
    seen_ids: set = set()

    dishes_data = _poster_request("GET", "menu.getDishes")
    if "error" not in dishes_data:
        for d in dishes_data.get("response", []) or []:
            item = _normalize_item(d, "dish")
            if item["id"] and item["id"] not in seen_ids and item["name"] != "—":
                seen_ids.add(item["id"])
                result.append(item)

    products_data = _poster_request("GET", "menu.getProducts")
    if "error" not in products_data:
        for p in products_data.get("response", []) or []:
            if str(p.get("hidden", "0")) != "0": continue
            ptype = str(p.get("type", "3"))
            kind = "dish" if ptype == "2" else "product"
            item = _normalize_item(p, kind)
            if item["id"] and item["id"] not in seen_ids and item["name"] != "—":
                seen_ids.add(item["id"])
                result.append(item)

    mods_data = _poster_request("GET", "menu.getModifications")
    if "error" not in mods_data:
        groups = mods_data.get("response", []) or []
        for group in groups:
            group_mods = group.get("modifiers", [])
            for m in group_mods:
                item = _normalize_item(m, "product")
                if item["id"] and item["name"] != "—":
                    mid_str = f"m_{item['id']}"
                    if mid_str not in seen_ids:
                        seen_ids.add(mid_str)
                        item["id"] = mid_str
                        result.append(item)

    milk_mods = [
        {"id": "gm_60", "name": "Молоко рослинне", "price": 0.8, "type": "mod"},
        {"id": "gm_61", "name": "Молоко безлактозне", "price": 0.4, "type": "mod"}
    ]
    for m in milk_mods:
        if m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            result.append(m)

    return result


def _find_item_by_name(product_name: str, items_list: list = None) -> tuple[dict, str]:
    items = items_list if items_list is not None else get_menu_items()
    if not items: return None, "Меню порожнє."

    def norm(s):
        import re
        s = s.strip().lower().replace("є", "е").replace("ї", "і")
        return re.sub(r'[^a-zа-яіїєґ0-9]', '', s)

    name_norm = norm(product_name)
    by_norm = {norm(p["name"]): p for p in items}

    if name_norm in by_norm: return by_norm[name_norm], ""

    substr_matches = [p for n, p in by_norm.items() if name_norm in n or n in name_norm]
    if substr_matches:
        substr_matches.sort(key=lambda p: len(p["name"]))
        return substr_matches[0], ""

    close = get_close_matches(name_norm, list(by_norm.keys()), n=1, cutoff=0.7)
    if close: return by_norm[close[0]], ""

    return None, f'Товар "{product_name}" не знайдено.'


def get_order_total(items: list) -> float:
    total = 0.0
    for item in items:
        found, _ = _find_item_by_name(item.get("product"))
        if found: total += found.get("price", 0.0) * item.get("quantity", 1)
    return round(total, 2)


def create_cafe_order(items: list, client_name: str, client_phone: str, spot_id: int = DEFAULT_SPOT_ID, client_id: int = None, comment: str = "") -> str:
    products_array = []
    comments_list = [comment] if comment else []

    for item in items:
        p_name = item.get("product")
        qty = item.get("quantity", 1)
        found, err = _find_item_by_name(p_name)
        if not found: return f"❌ {err}"

        if str(found["id"]).startswith("gm_"):
            mod_id = int(str(found["id"]).replace("gm_", ""))
            if products_array:
                last_p = products_array[-1]
                if "modifications" not in last_p: last_p["modifications"] = []
                last_p["modifications"].append({"modification_id": mod_id, "count": qty})
                continue

        raw_id = str(found["id"]).replace("m_", "")
        products_array.append({"product_id": int(raw_id), "count": qty})
        if item.get("comment"): comments_list.append(f"{p_name}: {item['comment']}")

    safe_phone = ''.join(filter(str.isdigit, str(client_phone)))
    payload = {
        "spot_id": spot_id,
        "first_name": client_name,
        "comment": " | ".join(comments_list),
        "products": products_array,
        "phone": safe_phone if len(safe_phone) >= 10 else "380990000000",
    }

    data = _poster_request("POST", "incomingOrders.createIncomingOrder", json_body=payload)
    if "error" in data: return f"❌ Помилка Poster: {data['error']}"

    order_id = data.get("response", {}).get("incoming_order_id") or data.get("response")
    return f"Замовлення #{order_id} створено успішно!"
