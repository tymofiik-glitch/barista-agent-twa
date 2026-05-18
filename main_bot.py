from __future__ import annotations
import os
import re
import time
import json
import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from aiohttp import web

from monobank_client import MonobankClient
from poster_tools import (
    get_menu_items, _find_item_by_name, get_order_total, create_cafe_order,
)
from i18n import t, find_button_key

# ────────────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MONOBANK_TOKEN = os.getenv("MONOBANK_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_FILE = os.path.join(BASE_DIR, "users_db.json")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://tymofiik-glitch.github.io/barista-agent-twa/")
PORT = int(os.getenv("PORT", "8080"))

LUNCH_PHONE_DISPLAY = "+380 66 939 4333"
PAYMENT_TIMEOUT_SEC = 15 * 60
PAID_TIMEOUT_SEC = 30 * 60

_raw_admin = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: set[int] = {int(x.strip()) for x in _raw_admin.split(",") if x.strip().isdigit()}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "tymofiik-glitch/barista-agent-twa"
GITHUB_FILE = "stop_list.json"

mono = MonobankClient(MONOBANK_TOKEN)
_raw_menu = get_menu_items()
menu_items = [it for it in _raw_menu if it.get("price", 0) > 0]
print(f"--- MENU INITIALIZED: {len(menu_items)} items ---")

# ────────────────────────────────────────────────────────────────────────
# STOP-LIST SYSTEM
# ────────────────────────────────────────────────────────────────────────

LIMITS_FILE = os.path.join(BASE_DIR, "daily_limits.json")
STOP_LIST_FILE = os.path.join(BASE_DIR, "stop_list.json")
POLL_INTERVAL_SEC = 120  # check Poster sales every 2 minutes

def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DISCOUNTS_FILE = os.path.join(BASE_DIR, "discounts.json")

def load_discounts() -> dict:
    return _load_json(DISCOUNTS_FILE, {})

def save_discounts(data: dict):
    _save_json(DISCOUNTS_FILE, data)

def get_user_discount(user_id: int) -> int:
    discounts = load_discounts()
    entry = discounts.get(str(user_id))
    if entry and isinstance(entry, dict):
        return int(entry.get("percent", 0))
    return 0


def load_limits() -> dict:
    """Returns {str(posterId): int(limit)} for today."""
    data = _load_json(LIMITS_FILE, {})
    today = datetime.now().strftime("%Y-%m-%d")
    return data.get(today, {})

def save_limit(poster_id: int, limit: int):
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_json(LIMITS_FILE, {})
    if today not in data:
        data[today] = {}
    data[today][str(poster_id)] = limit
    _save_json(LIMITS_FILE, data)

def remove_limit(poster_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_json(LIMITS_FILE, {})
    data.get(today, {}).pop(str(poster_id), None)
    _save_json(LIMITS_FILE, data)

def load_stop_list() -> dict:
    """Returns {str(posterId): {"reason": str, "manual": bool}}"""
    data = _load_json(STOP_LIST_FILE, {})
    today = datetime.now().strftime("%Y-%m-%d")
    return data.get(today, {})

def _save_stop_list(entries: dict):
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_json(STOP_LIST_FILE, {})
    data[today] = entries
    _save_json(STOP_LIST_FILE, data)

async def push_stop_list_to_github(stopped_ids: list):
    """Push current stopped posterIds to GitHub repo so frontend can read via HTTPS.
    Retries on 409 (stale SHA) since multiple toggles can fire in quick succession."""
    if not GITHUB_TOKEN:
        return
    import aiohttp as _aiohttp, base64
    content = json.dumps({"stopped": stopped_ids}, ensure_ascii=False)
    encoded = base64.b64encode(content.encode()).decode()
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    try:
        async with _aiohttp.ClientSession() as session:
            for attempt in range(5):
                async with session.get(api_url, headers=headers) as r:
                    sha = (await r.json()).get("sha", "")
                payload = {"message": "update stop_list", "content": encoded, "sha": sha}
                async with session.put(api_url, headers=headers, json=payload) as r:
                    if r.status in (200, 201):
                        return
                    if r.status == 409:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    logging.error(f"[GitHub] push stop_list failed: {r.status}")
                    return
            logging.error(f"[GitHub] push stop_list: gave up after 5 attempts (409 loop)")
    except Exception as e:
        logging.error(f"[GitHub] push_stop_list error: {e}")

def add_to_stop(poster_id: int, reason: str, manual: bool = False):
    entries = load_stop_list()
    entries[str(poster_id)] = {"reason": reason, "manual": manual}
    _save_stop_list(entries)

def remove_from_stop(poster_id: int):
    entries = load_stop_list()
    entries.pop(str(poster_id), None)
    _save_stop_list(entries)

def get_poster_sales_today() -> dict:
    """Returns {str(product_id): float(count_sold)} from Poster for today."""
    from poster_tools import _poster_request
    today = datetime.now().strftime("%Y%m%d")
    data = _poster_request("GET", "dash.getProductsSales", params={"date_from": today, "date_to": today})
    result: dict[str, float] = {}
    for item in data.get("response", []) or []:
        pid = str(item.get("product_id", ""))
        try:
            count = float(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0.0
        if pid:
            result[pid] = result.get(pid, 0.0) + count
    return result

def find_menu_item_by_poster_id(poster_id: int) -> dict | None:
    for it in menu_items:
        raw_id = str(it.get("id", "")).replace("m_", "").replace("gm_", "")
        if raw_id == str(poster_id):
            return it
    return None

async def poll_stop_list():
    """Background task: every 2 min checks Poster sales vs limits and auto-blocks items."""
    while True:
        try:
            limits = load_limits()
            if limits:
                sales = get_poster_sales_today()
                current_stop = load_stop_list()
                changed = False
                for pid_str, limit in limits.items():
                    sold = sales.get(pid_str, 0.0)
                    if sold >= limit:
                        if pid_str not in current_stop:
                            current_stop[pid_str] = {"reason": f"Ліміт {limit} порцій вичерпано ({int(sold)} продано)", "manual": False}
                            changed = True
                            logging.info(f"[StopList] Auto-blocked posterId={pid_str} sold={sold}/{limit}")
                    else:
                        # Auto-unblock only if it was auto-blocked (not manual)
                        if pid_str in current_stop and not current_stop[pid_str].get("manual"):
                            del current_stop[pid_str]
                            changed = True
                            logging.info(f"[StopList] Auto-unblocked posterId={pid_str} sold={sold}/{limit}")
                if changed:
                    _save_stop_list(current_stop)
                    asyncio.create_task(push_stop_list_to_github([int(k) for k in current_stop.keys()]))
        except Exception as e:
            logging.error(f"[StopList] Poll error: {e}")
        await asyncio.sleep(POLL_INTERVAL_SEC)

def _name_by_poster_id(poster_id: int) -> str:
    item = find_menu_item_by_poster_id(poster_id)
    if item:
        name = item.get("name", "")
        return name if isinstance(name, str) else name.get("uk", str(name))
    return f"id={poster_id}"

# ────────────────────────────────────────────────────────────────────────
# STATE
# ────────────────────────────────────────────────────────────────────────

user_states: dict[int, dict] = {}
global_app = None  # To access from aiohttp handlers

def _empty_state() -> dict:
    return {
        "state": "IDLE",
        "cart": [],
        "arrival": "по готовності",
        "comment": "",
        "internal_id": None,
        "invoice_id": None,
        "confirming": False,
        "timeout_task": None,
    }

def get_state(user_id: int) -> dict:
    st = user_states.get(user_id)
    if st is None:
        st = _empty_state()
        user_states[user_id] = st
    return st

def reset_state(user_id: int):
    st = get_state(user_id)
    if st.get("timeout_task") and not st["timeout_task"].done():
        st["timeout_task"].cancel()
    user_states[user_id] = _empty_state()

def expand_cart(items: list) -> list:
    """Expand cart from frontend into flat list of lines.
    Each line carries posterId + price from the frontend — Poster name lookup
    is NEVER used for pricing or order creation."""
    result = []
    for it in items or []:
        qty = int(it.get("quantity", it.get("qty", 1)))
        product_name = it.get("product", it.get("name", ""))
        price = float(it.get("basePrice", it.get("price", 0)))
        poster_id = it.get("posterId", 0)

        if isinstance(product_name, dict):
            product_name = product_name.get("uk", product_name.get("en", str(product_name)))

        for _ in range(qty):
            result.append({
                "product": product_name,
                "posterId": int(poster_id) if poster_id else 0,
                "quantity": 1,
                "price": price,
                "comment": it.get("comment", "") or "",
                "is_mod": False,
            })

            # Mods
            for m in it.get("mods", []):
                m_name = m.get("name", "") if isinstance(m, dict) else m
                m_price = float(m.get("price", 0)) if isinstance(m, dict) else 0.0
                m_pid = m.get("posterId", 0) if isinstance(m, dict) else 0
                m_mid = m.get("modificationId", 0) if isinstance(m, dict) else 0

                if isinstance(m_name, dict):
                    m_name = m_name.get("uk", m_name.get("en", str(m_name)))

                result.append({
                    "product": m_name,
                    "posterId": int(m_pid) if m_pid else 0,
                    "modificationId": int(m_mid) if m_mid else 0,
                    "quantity": 1,
                    "price": m_price,
                    "comment": "",
                    "is_mod": True,
                })
    return result

# ────────────────────────────────────────────────────────────────────────
# USERS DB
# ────────────────────────────────────────────────────────────────────────

def load_users() -> dict:
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_user_field(tid: int, **fields):
    users = load_users()
    key = str(tid)
    if key not in users:
        users[key] = {}
    users[key].update(fields)
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def save_user(tid: int, name: str, phone: str):
    save_user_field(tid, name=name, phone=phone)

def get_user(tid: int) -> dict:
    return load_users().get(str(tid), {})

def get_lang(user_id: int) -> str:
    return get_user(user_id).get("lang", "uk")

# ────────────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────────────

def find_price_by_name(product_name: str) -> tuple[float, str | int]:
    found, err = _find_item_by_name(product_name, menu_items)
    if found:
        return float(found.get('price', 0.0)), found.get('id', 0)
    return 0.0, 0

# ────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────────────────────────────

def main_kb(lang: str) -> ReplyKeyboardMarkup:
    # Button to launch the Web App
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(lang, "btn_make_order"), web_app=WebAppInfo(url=WEBAPP_URL))],
            [
                KeyboardButton(t(lang, "btn_lunch")),
                KeyboardButton(t(lang, "btn_settings")),
            ],
            [KeyboardButton(t(lang, "btn_feedback"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def pay_kb(lang: str, page_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_pay"), url=page_url)],
        [InlineKeyboardButton(t(lang, "btn_cancel"), callback_data="cancel_payment")],
    ])

def post_paid_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_order_again"), callback_data="order_again")],
    ])

def retry_payment_kb(lang: str, internal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_retry"), callback_data=f"confirm_{internal_id}")],
        [InlineKeyboardButton(t(lang, "btn_cancel"), callback_data="cancel_order")],
    ])

def settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_set_name"), callback_data="set_name"),
         InlineKeyboardButton(t(lang, "btn_set_lang"), callback_data="set_lang")],
        [InlineKeyboardButton(t(lang, "btn_set_phone"), callback_data="set_phone")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_close")],
    ])

def usual_view_kb(lang: str, has_usual: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_usual:
        rows.append([
            InlineKeyboardButton(t(lang, "btn_change_usual"), callback_data="usual_change"),
            InlineKeyboardButton(t(lang, "btn_delete_usual"), callback_data="usual_delete"),
        ])
    else:
        rows.append([InlineKeyboardButton(t(lang, "btn_setup_usual"), callback_data="usual_change")])
    rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")])
    return InlineKeyboardMarkup(rows)

def lang_choice_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")],
    ])

def lunch_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t(lang, "btn_call", phone=LUNCH_PHONE_DISPLAY),
            url="tel:+380669394333",
        )],
    ])

# ────────────────────────────────────────────────────────────────────────
# BOT HANDLERS
# ────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    uid = str(user_id)
    users = load_users()
    lang = get_lang(user_id)

    st = get_state(user_id)
    if st["state"] in ("CART_PENDING", "AWAITING_PAYMENT"):
        await update.message.reply_text(
            t(lang, "active_order"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn_yes_cancel"), callback_data="reset_to_idle")],
                [InlineKeyboardButton(t(lang, "btn_no_continue"), callback_data="keep_current")],
            ]),
        )
        return

    if uid in users:
        name = users[uid].get("name", "друже").capitalize()
        await update.message.reply_text(
            t(lang, "greet_known", name=name),
            reply_markup=main_kb(lang),
        )
    else:
        await update.message.reply_text(
            t(lang, "greet_new"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(t(lang, "send_phone_btn"), request_contact=True)]],
                one_time_keyboard=True, resize_keyboard=True,
            ),
        )

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    c = update.message.contact

    st = get_state(user_id)
    if st["state"] == "AWAITING_NEW_PHONE":
        save_user_field(user_id, phone=c.phone_number)
        st["state"] = "IDLE"
        try:
            await update.message.delete()
        except Exception:
            pass
        
        await update.message.reply_text(t(lang, "saved"), reply_markup=main_kb(lang))
        return

    save_user(user_id, c.first_name, c.phone_number)
    reset_state(user_id)
    name = (c.first_name or "друже").capitalize()
    await update.message.reply_text(
        t(lang, "after_register", name=name),
        reply_markup=main_kb(lang),
    )

async def show_lunch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        t(lang, "lunch_text", phone=LUNCH_PHONE_DISPLAY),
        reply_markup=lunch_kb(lang),
        parse_mode="Markdown",
    )

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    user = get_user(user_id)
    name = user.get("name", "—").capitalize()
    phone = user.get("phone", "—")
    lang_label = t(lang, "settings_lang_uk_label") if lang == "uk" else t(lang, "settings_lang_en_label")
    text = t(lang, "settings_title", name=name, phone=phone, lang=lang_label)
    reply_markup = settings_kb(lang)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    lang = get_lang(user_id)

    btn_key = find_button_key(user_text)
    if not btn_key and (user_text in (t(lang, "btn_cancel"), "❌ Скасувати", "❌ Cancel") or user_text.lower() == "cancel"):
        btn_key = "btn_cancel"

    if btn_key:
        if btn_key == "btn_make_order":
            await update.message.reply_text("Відкриваю додаток...")
        elif btn_key == "btn_lunch":
            await show_lunch(update, context)
        elif btn_key == "btn_settings":
            await show_settings(update, context)
        elif btn_key == "btn_feedback":
            st = get_state(user_id)
            st["state"] = "AWAITING_FEEDBACK"
            await update.message.reply_text(
                t(lang, "ask_feedback"),
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton(t(lang, "btn_cancel"))]],
                    resize_keyboard=True,
                )
            )
        elif btn_key == "btn_cancel":
            st = get_state(user_id)
            st["state"] = "IDLE"
            await update.message.reply_text(
                t(lang, "ok"),
                reply_markup=main_kb(lang),
            )
        return

    st = get_state(user_id)
    if st["state"] == "AWAITING_FEEDBACK":
        st["state"] = "IDLE"
        user_info = get_user(user_id)
        user_name = user_info.get("name") or update.effective_user.first_name or "Клієнт"
        user_phone = user_info.get("phone") or "не вказано"
        
        target_feedback_id = 634501437
        try:
            await context.bot.send_message(
                chat_id=target_feedback_id,
                text=(
                    f"🌟 *Новий відгук від клієнта!*\n\n"
                    f"👤 *Ім'я:* {user_name} (ID: `{user_id}`)\n"
                    f"📞 *Телефон:* `{user_phone}`\n\n"
                    f"💬 *Текст відгуку:*\n{user_text}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to send feedback to owner {target_feedback_id}: {e}")
                
        await update.message.reply_text(
            t(lang, "feedback_saved"),
            reply_markup=main_kb(lang),
        )
        return

    if st["state"] == "AWAITING_NEW_NAME":
        new_name = user_text[:40] or "—"
        save_user_field(user_id, name=new_name)
        st["state"] = "IDLE"
        try:
            await update.message.delete()
        except Exception:
            pass
        await update.message.reply_text(
            t(lang, "name_saved", name=new_name.capitalize()),
            reply_markup=main_kb(lang),
        )
        return

    # Fallback response for all other text messages
    msg = (
        "Будь ласка, скористайся кнопкою **Замовити 🛒** у меню, щоб відкрити каталог товарів!"
        if lang == "uk" else
        "Please use the **Order 🛒** button in the menu to view our items!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_kb(lang))

# ────────────────────────────────────────────────────────────────────────
# WEB APP DATA & CREATION
# ────────────────────────────────────────────────────────────────────────

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = get_lang(user_id)
    
    raw_data = update.effective_message.web_app_data.data
    logging.info(f"Received web app data from user {user_id}: {raw_data}")
    
    try:
        data = json.loads(raw_data)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=t(lang, "something_wrong"))
        return

    items = data.get("items", [])
    if not items and isinstance(data, list):
        items = data

    if not items:
        await context.bot.send_message(chat_id=chat_id, text=t(lang, "cart_empty"))
        return

    arrival = data.get("arrival") or "по готовності"
    comment = data.get("comment") or ""

    await create_monobank_invoice_and_notify(user_id, chat_id, items, arrival, comment, context.bot)

def get_cart_total(cart: list) -> float:
    total = 0.0
    for i in cart:
        p = i.get("price")
        if p is None or p == 0:
            p, _ = find_price_by_name(i.get("product", ""))
        total += float(p) * i.get("quantity", 1)
    return round(total, 2)

async def create_monobank_invoice_and_notify(user_id: int, chat_id: int, items: list, arrival: str, comment: str, bot):
    lang = get_lang(user_id)
    st = get_state(user_id)
    st["cart"] = expand_cart(items)
    st["arrival"] = arrival
    st["comment"] = comment
    st["internal_id"] = f"{user_id}_{int(time.time())}"
    st["state"] = "CART_PENDING"

    subtotal = get_cart_total(st["cart"])
    logging.warning(f"[ORDER] user={user_id} cart={st['cart']} subtotal={subtotal}")
    if subtotal <= 0:
        await bot.send_message(chat_id=chat_id, text=t(lang, "cant_calc"))
        return

    discount_pct = get_user_discount(user_id)
    discount_amount = 0.0
    total = subtotal
    if discount_pct > 0:
        discount_amount = round(subtotal * discount_pct / 100, 2)
        total = round(subtotal - discount_amount, 2)

    st["confirming"] = True

    # 1. Build and send the receipt IMMEDIATELY
    arrival_for_msg = st.get("arrival") or t(lang, "ready_when")
    if arrival_for_msg in ("по готовності", ""):
        arrival_for_msg = t(lang, "ready_when")

    receipt_lines = ["🧾 *Ваше замовлення:*"]
    for it in items:
        p_name = it.get("product") or it.get("name")
        if isinstance(p_name, dict):
            p_name = p_name.get("uk") or p_name.get("en") or str(p_name)
        if not p_name:
            p_name = "Невідомо"
            
        qty = it.get("quantity") or it.get("qty") or 1
        price = float(it.get("price") or it.get("basePrice") or 0.0)
        if price == 0:
            price, _ = find_price_by_name(p_name)
            
        mods = it.get("modifiers") or it.get("mods") or []
        mods_price = 0.0
        for m in mods:
            if isinstance(m, dict):
                mods_price += float(m.get("price") or 0.0)
                
        item_total = (price + mods_price) * qty
        
        item_comment = it.get("comment", "") or ""
        display_name = f"{p_name} — {item_comment}" if item_comment else p_name
        
        display_text = f"• {display_name} x{qty}"
        pad_len = max(2, 28 - len(display_text))
        dots = "." * pad_len
        line = f"• {display_name} x{qty} {dots} {item_total:.0f} ₴"
        
        if mods:
            mod_names = []
            for m in mods:
                if isinstance(m, dict):
                    m_val = m.get("name") or m.get("product")
                    if isinstance(m_val, dict):
                        m_val = m_val.get("uk") or m_val.get("en") or str(m_val)
                    if m_val:
                        mod_names.append(m_val)
                elif isinstance(m, str):
                    mod_names.append(m)
            if mod_names:
                line += f"\n   _(+ {', '.join(mod_names)})_"
        receipt_lines.append(line)
        
    receipt_lines.append("")
    receipt_lines.append(f"🕒 *Час:* {arrival_for_msg}")
    if comment:
        receipt_lines.append(f"📝 *Коментар:* {comment}")
        
    if lang == "uk":
        lbl_subtotal = "Сума:"
        lbl_discount = f"Знижка {discount_pct}%:"
        lbl_to_pay = "До сплати:"
    else:
        lbl_subtotal = "Subtotal:"
        lbl_discount = f"Discount {discount_pct}%:"
        lbl_to_pay = "To pay:"

    if discount_pct > 0:
        receipt_lines.append("─────────────────────")
        receipt_lines.append(f"{lbl_subtotal:<15} {subtotal:.0f} ₴")
        receipt_lines.append(f"{lbl_discount:<15} -{discount_amount:.0f} ₴")
        receipt_lines.append("─────────────────────")
        receipt_lines.append(f"💳 *{lbl_to_pay} {total:.0f} ₴*")
    else:
        receipt_lines.append("─────────────────────")
        receipt_lines.append(f"💳 *{lbl_to_pay} {total:.0f} ₴*")
    
    loading_text = "\n".join(receipt_lines + ["\n⏳ _Генерую посилання на оплату..._"])
    
    try:
        sent_msg = await bot.send_message(
            chat_id=chat_id,
            text=loading_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Failed to send initial receipt: {e}")
        st["confirming"] = False
        return

    # 2. Call Monobank API
    try:
        basket_order = []
        total_kop = int(round(total * 100))
        sum_items_kop = 0
        
        for idx, it in enumerate(st["cart"]):
            p_name = it["product"]
            p_price = it.get("price")
            if p_price is None or p_price == 0:
                p_price, _ = find_price_by_name(p_name)
            
            if discount_pct > 0:
                p_price = p_price * (100 - discount_pct) / 100
            
            p_price_kop = int(round(p_price * 100))
            
            # Adjust the last item to match total_kop exactly
            if idx == len(st["cart"]) - 1:
                p_price_kop = total_kop - sum_items_kop
                
            sum_items_kop += p_price_kop
            
            basket_order.append({
                "name": p_name,
                "qty": 1,
                "sum": p_price_kop,
                "total": p_price_kop,
            })

        inv = await mono.create_invoice(
            amount_kopecks=total_kop,
            reference=st["internal_id"],
            basket_order=basket_order,
            validity_seconds=PAYMENT_TIMEOUT_SEC,
        )
        
        if not inv:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_msg.message_id,
                text="\n".join(receipt_lines) + f"\n\n❌ {t(lang, 'invoice_failed')}",
                parse_mode="Markdown"
            )
            st["confirming"] = False
            return

        st["invoice_id"] = inv["invoiceId"]
        st["state"] = "AWAITING_PAYMENT"
        st["confirming"] = False

        # 3. Attach Payment Button
        final_text = "\n".join(receipt_lines + ["\nНатисніть кнопку нижче для оплати ⬇"])
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_msg.message_id,
            text=final_text,
            reply_markup=pay_kb(lang, inv["pageUrl"]),
            parse_mode="Markdown",
        )
        asyncio.create_task(poll_payment(user_id, chat_id, ContextMock(bot), sent_msg.message_id))
    except Exception as e:
        logging.error(f"WebApp invoice creation error: {e}\n{traceback.format_exc()}")
        st["confirming"] = False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_msg.message_id,
                text="\n".join(receipt_lines) + f"\n\n❌ {t(lang, 'something_wrong')}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

# ────────────────────────────────────────────────────────────────────────
# ADMIN PANEL (STOP-LIST)
# ────────────────────────────────────────────────────────────────────────

# Exact menu structure mirroring the app — only these items are manageable
APP_MENU: list[dict] = [
    {"cat_id": "coffee",     "cat_name": "☕ Кава", "items": [
        {"pid": 6,    "name": "Еспресо"},
        {"pid": 9,    "name": "Американо"},
        {"pid": 8,    "name": "Допіо"},
        {"pid": 122,  "name": "Еспресо макіато"},
        {"pid": 7,    "name": "Капучино"},
        {"pid": 10,   "name": "Кава Лате"},
        {"pid": 11,   "name": "Флет вайт"},
        {"pid": 32,   "name": "РАФ кава"},
        {"pid": 488,  "name": "Капуоранж"},
    ]},
    {"cat_id": "hot",        "cat_name": "🍵 Гарячі напої", "items": [
        {"pid": 324,  "name": "Матча лате"},
        {"pid": 21,   "name": "Какао Бельгійське"},
        {"pid": 1207, "name": "Чай чорний"},
        {"pid": 1208, "name": "Чай зелений"},
    ]},
    {"cat_id": "summer",     "cat_name": "🧊 Iced Mood", "items": [
        {"pid": 207,  "name": "Айс-Лате"},
        {"pid": 729,  "name": "Айс Матча-лате"},
        {"pid": 1372, "name": "Айс-Капуоранж"},
        {"pid": 1373, "name": "Капуоранж (сік)"},
        {"pid": 195,  "name": "Еспресо тонік"},
        {"pid": 1300, "name": "Матча Оранж"},
        {"pid": 1541, "name": "Полунична матча"},
    ]},
    {"cat_id": "cold",       "cat_name": "🥤 Холодні напої", "items": [
        {"pid": 773,  "name": "Сік Сандора"},
        {"pid": 141,  "name": "Пепсі 0.33"},
        {"pid": 94,   "name": "Пепсі 0.5"},
        {"pid": 1601, "name": "Вода 0.5"},
        {"pid": 19,   "name": "Фреш апельсиновий"},
    ]},
    {"cat_id": "croissants", "cat_name": "🥐 Круасани", "items": [
        {"pid": 1547, "name": "Круасан з шинкою"},
        {"pid": 1546, "name": "Круасан з пепероні"},
        {"pid": 1548, "name": "Круасан з лососем"},
        {"pid": 1251, "name": "Круасан класичний"},
        {"pid": 9001, "name": "Круасан солодкий — Малина"},
        {"pid": 9002, "name": "Круасан солодкий — Шоколад"},
        {"pid": 9003, "name": "Круасан солодкий — Абрикос"},
    ]},
    {"cat_id": "breakfast",  "cat_name": "🍳 Сніданки", "items": [
        {"pid": 1499, "name": "Омлет сирний"},
        {"pid": 1108, "name": "Яєчня / Омлет / Скрембл"},
        {"pid": 991,  "name": "Яйця бенедикт"},
        {"pid": 1631, "name": "Сирники"},
    ]},
    {"cat_id": "salads",     "cat_name": "🥗 Салати", "items": [
        {"pid": 56,   "name": "Цезар з куркою"},
        {"pid": 1114, "name": "Салат з креветкою"},
    ]},
    {"cat_id": "sandwiches", "cat_name": "🥪 Сендвічі", "items": [
        {"pid": 1569, "name": "Клаб-сендвіч курка-шукрут"},
        {"pid": 1567, "name": "Клаб-сендвіч з шинкою"},
        {"pid": 1568, "name": "Клаб-сендвіч з пепероні"},
        {"pid": 1664, "name": "Сендвіч з гравлаксом"},
    ]},
    {"cat_id": "shawarma",   "cat_name": "🌯 Шаурма / Бургер", "items": [
        {"pid": 1545, "name": "Шаурма з куркою"},
        {"pid": 1118, "name": "Шаурма-Рол з креветкою"},
        {"pid": 1514, "name": "Бургер яловичий"},
    ]},
]

def _admin_main_kb() -> InlineKeyboardMarkup:
    kb = []
    for i in range(0, len(APP_MENU), 2):
        row = [InlineKeyboardButton(APP_MENU[i]["cat_name"], callback_data=f"adm_cat:{APP_MENU[i]['cat_id']}")]
        if i + 1 < len(APP_MENU):
            row.append(InlineKeyboardButton(APP_MENU[i+1]["cat_name"], callback_data=f"adm_cat:{APP_MENU[i+1]['cat_id']}"))
        kb.append(row)
    return InlineKeyboardMarkup(kb)

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id): return
    stop = load_stop_list()
    stopped_count = len(stop)
    header = f"🛠 *Стоп-лист* — {stopped_count} позицій заблоковано\nОберіть категорію:"
    await update.message.reply_text(header, reply_markup=_admin_main_kb(), parse_mode="Markdown")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not _is_admin(update.effective_user.id):
        await query.answer()
        return

    if data.startswith("adm_cat:"):
        await query.answer()
        cat_id = data.split(":", 1)[1]
        cat = next((c for c in APP_MENU if c["cat_id"] == cat_id), None)
        if not cat: return
        stop = load_stop_list()
        kb = []
        for it in cat["items"]:
            pid_str = str(it["pid"])
            status = "❌" if pid_str in stop else "✅"
            kb.append([InlineKeyboardButton(f"{status} {it['name']}", callback_data=f"adm_tog:{pid_str}:{cat_id}")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")])
        await query.edit_message_text(
            f"{cat['cat_name']}\nТапніть позицію щоб увімк/вимк:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    elif data.startswith("adm_tog:"):
        # First tap → show confirmation screen
        await query.answer()
        _, pid_str, cat_id = data.split(":", 2)
        stop = load_stop_list()
        cat = next((c for c in APP_MENU if c["cat_id"] == cat_id), None)
        item_name = next((it["name"] for it in (cat["items"] if cat else []) if str(it["pid"]) == pid_str), pid_str)
        in_stop = pid_str in stop
        if in_stop:
            text = f"✅ *{item_name}*\n\nПовернути в наявність?"
            confirm_cb = f"adm_yes_on:{pid_str}:{cat_id}"
            confirm_btn = "✅ Так, повернути"
        else:
            text = f"⚠️ *{item_name}*\n\nЗупинити продаж цієї позиції?"
            confirm_cb = f"adm_yes_off:{pid_str}:{cat_id}"
            confirm_btn = "🔴 Так, в стоп"
        kb = [
            [InlineKeyboardButton(confirm_btn, callback_data=confirm_cb)],
            [InlineKeyboardButton("↩️ Скасувати", callback_data=f"adm_cat:{cat_id}")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data.startswith("adm_yes_off:") or data.startswith("adm_yes_on:"):
        # Confirmed → apply change and return to category
        await query.answer()
        parts = data.split(":", 2)
        action, pid_str, cat_id = parts
        cat = next((c for c in APP_MENU if c["cat_id"] == cat_id), None)
        item_name = next((it["name"] for it in (cat["items"] if cat else []) if str(it["pid"]) == pid_str), pid_str)
        if action == "adm_yes_off":
            add_to_stop(int(pid_str), "Вручну заблоковано баристою", manual=True)
        else:
            remove_from_stop(int(pid_str))
            remove_limit(int(pid_str))
        stop2 = load_stop_list()
        asyncio.create_task(push_stop_list_to_github([int(k) for k in stop2.keys()]))
        kb = []
        for it in (cat["items"] if cat else []):
            s = "❌" if str(it["pid"]) in stop2 else "✅"
            kb.append([InlineKeyboardButton(f"{s} {it['name']}", callback_data=f"adm_tog:{it['pid']}:{cat_id}")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")])
        status_line = f"🔴 *{item_name}* — в стопі" if action == "adm_yes_off" else f"✅ *{item_name}* — в наявності"
        await query.edit_message_text(
            f"{status_line}\n\n{cat['cat_name'] if cat else cat_id}:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    elif data == "adm_main":
        await query.answer()
        stop = load_stop_list()
        stopped_count = len(stop)
        await query.edit_message_text(
            f"🛠 *Стоп-лист* — {stopped_count} позицій заблоковано\nОберіть категорію:",
            reply_markup=_admin_main_kb(),
            parse_mode="Markdown"
        )

# ────────────────────────────────────────────────────────────────────────
# CALL QUERY HANDLER
# ────────────────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data.startswith("adm_"):
        await admin_callback_handler(update, context)
        return

    if data == "lunch_call":
        await query.answer(LUNCH_PHONE_DISPLAY, show_alert=True)
        return

    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    lang = get_lang(user_id)
    st = get_state(user_id)

    if data == "cancel_order" or data == "cancel_payment":
        if st.get("invoice_id"):
            await mono.cancel_invoice(st["invoice_id"])
        try:
            await query.message.edit_text(t(lang, "order_cancelled"))
        except Exception:
            pass
        reset_state(user_id)
        return

    if data == "reset_to_idle":
        if st.get("invoice_id"):
            await mono.cancel_invoice(st["invoice_id"])
        reset_state(user_id)
        await query.message.edit_text(t(lang, "fresh_start"))
        return

    if data == "keep_current":
        await query.message.edit_text(t(lang, "keep_current"))
        return

    if data == "order_again":
        reset_state(user_id)
        await context.bot.send_message(chat_id=chat_id, text=t(lang, "greet_known", name=""))
        return

    if data == "set_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "set_name":
        st["state"] = "AWAITING_NEW_NAME"
        await query.edit_message_text(
            t(lang, "ask_new_name"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")]])
        )
        return

    if data == "set_back_main":
        st["state"] = "IDLE"
        await show_settings(update, context, edit=True)
        return

    if data == "set_lang":
        await query.edit_message_text(t(lang, "ask_lang"), reply_markup=lang_choice_kb(lang))
        return

    if data == "lang_uk":
        save_user_field(user_id, lang="uk")
        await show_settings(update, context, edit=True)
        return

    if data == "lang_en":
        save_user_field(user_id, lang="en")
        await show_settings(update, context, edit=True)
        return

    if data == "set_phone":
        st["state"] = "AWAITING_NEW_PHONE"
        await query.message.delete()
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, "ask_new_phone"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(t(lang, "send_phone_btn"), request_contact=True)]],
                one_time_keyboard=True, resize_keyboard=True,
            ),
        )

# ────────────────────────────────────────────────────────────────────────
# POLLING + POSTER
# ────────────────────────────────────────────────────────────────────────

class ContextMock:
    def __init__(self, bot):
        self.bot = bot

async def poll_payment(user_id: int, chat_id: int, context: ContextMock, msg_id: int):
    st = get_state(user_id)
    inv_id = st.get("invoice_id")
    if not inv_id:
        return

    max_iterations = PAYMENT_TIMEOUT_SEC // 3

    for _ in range(max_iterations):
        await asyncio.sleep(3)
        st = get_state(user_id)
        if st["state"] != "AWAITING_PAYMENT" or st.get("invoice_id") != inv_id:
            return

        status = await mono.get_invoice_status(inv_id)
        if not status:
            continue

        s = status.get("status")
        if s == "success":
            await handle_successful_payment(user_id, chat_id, context, msg_id)
            return
        if s in mono.FINAL_FAILURE:
            await handle_failed_payment(user_id, chat_id, context, msg_id, status_str=s)
            return

    await handle_failed_payment(user_id, chat_id, context, msg_id, status_str="expired")

async def handle_successful_payment(user_id: int, chat_id: int, context: ContextMock, msg_id: int):
    st = get_state(user_id)
    lang = get_lang(user_id)
    user = get_user(user_id)
    client_name = user.get("name", "Гість")
    client_phone = user.get("phone", "")

    poster_items = [
        {
            "product": it.get("product"),
            "posterId": it.get("posterId", 0),
            "modificationId": it.get("modificationId", 0),
            "is_mod": it.get("is_mod", False),
            "quantity": it.get("quantity", 1),
            "comment": it.get("comment", ""),
        }
        for it in st["cart"]
    ]

    discount_pct = get_user_discount(user_id)
    arrival = st.get("arrival") or "по готовності"
    poster_comment_parts = ["💳 ОПЛАЧЕНО MONOBANK", f"Час: {arrival}"]
    if discount_pct > 0:
        poster_comment_parts.insert(1, f"Знижка {discount_pct}%")
    if st.get("comment"):
        poster_comment_parts.append(st["comment"])
    poster_comment = " | ".join(poster_comment_parts)

    try:
        result = create_cafe_order(
            items=poster_items,
            client_name=client_name,
            client_phone=client_phone,
            comment=poster_comment,
        )
        logging.info(f"[Poster] Order created: {result}")
        poster_ok = result.startswith("Замовлення") or result.startswith("✅")
        order_num = ""
        match = re.search(r"#(\S+?)\s", result + " ")
        if match:
            order_num = match.group(1)
    except Exception as e:
        logging.error(f"[Poster] Order failed: {e}\n{traceback.format_exc()}")
        poster_ok = False
        order_num = ""

    counts: dict[str, int] = {}
    for it in st["cart"]:
        counts[it.get("product")] = counts.get(it.get("product"), 0) + 1
    cart_lines = []
    for name, qty in counts.items():
        cart_lines.append(f" • {name}" + (f" × {qty}" if qty > 1 else ""))
    items_text = "\n".join(cart_lines)

    if arrival in ("по готовності", ""):
        arrival_text = t(lang, "preparing_now")
    else:
        arrival_text = t(lang, "wait_at", time=arrival)

    if poster_ok:
        order_line = t(lang, "order_number", num=order_num) if order_num else ""
        msg = t(lang, "payment_success_full",
                name=client_name.capitalize(),
                items=items_text,
                arrival=arrival_text,
                order_line=order_line)
    else:
        msg = t(lang, "payment_success_short", items=items_text)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=msg,
            reply_markup=post_paid_kb(lang),
            parse_mode="Markdown",
        )
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=post_paid_kb(lang), parse_mode="Markdown")

    st["state"] = "PAID"
    reset_state(user_id)

async def handle_failed_payment(user_id: int, chat_id: int, context: ContextMock, msg_id: int, status_str: str):
    st = get_state(user_id)
    lang = get_lang(user_id)
    text = t(lang, "payment_expired") if status_str == "expired" else t(lang, "payment_failed_msg")

    st["invoice_id"] = None
    st["state"] = "CART_PENDING"

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            reply_markup=retry_payment_kb(lang, st["internal_id"]),
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────────────────
# AIOHTTP API ENDPOINT
# ────────────────────────────────────────────────────────────────────────

async def handle_stop_list(request):
    stop = load_stop_list()
    return web.json_response(
        {"stopped": [int(k) for k in stop.keys()]},
        headers={"Access-Control-Allow-Origin": "*"},
    )

async def handle_create_order(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    items = data.get("items", [])
    arrival = data.get("arrival") or "по готовності"
    comment = data.get("comment") or ""

    if not user_id or not items:
        return web.json_response({"error": "user_id and items are required"}, status=400)

    try:
        user_id = int(user_id)
        chat_id = int(chat_id) if chat_id else user_id
    except ValueError:
        return web.json_response({"error": "user_id and chat_id must be valid numbers"}, status=400)

    # Invoke invoice creation in background
    asyncio.create_task(create_monobank_invoice_and_notify(user_id, chat_id, items, arrival, comment, global_app.bot))
    return web.json_response({"status": "processing"})

# ────────────────────────────────────────────────────────────────────────
# BARISTA COMMANDS (admin only)
# ────────────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def cmd_stoplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    stop = load_stop_list()
    limits = load_limits()
    if not stop and not limits:
        await update.message.reply_text("✅ Стоп-лист порожній.")
        return
    lines = []
    if stop:
        lines.append("🔴 *Зараз на стопі:*")
        for pid_str, info in stop.items():
            name = _name_by_poster_id(int(pid_str))
            tag = "👤 вручну" if info.get("manual") else "🤖 авто"
            lines.append(f"  • {name} ({tag})")
    if limits:
        lines.append("\n📊 *Ліміти на сьогодні:*")
        sales = get_poster_sales_today()
        for pid_str, lim in limits.items():
            name = _name_by_poster_id(int(pid_str))
            sold = int(sales.get(pid_str, 0))
            status = "🔴" if pid_str in stop else "🟢"
            lines.append(f"  {status} {name}: {sold}/{lim} порцій")
    lines.append("\n/admin — керування стоп-листом")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    discount = get_user_discount(user_id)
    
    if lang == "uk":
        text = f"👤 *Ваш Telegram ID:* `{user_id}`\n"
        if discount > 0:
            text += f"✨ *Ваша персональна знижка:* {discount}%"
        else:
            text += "✨ *Ваша персональна знижка:* немає"
    else:
        text = f"👤 *Your Telegram ID:* `{user_id}`\n"
        if discount > 0:
            text += f"✨ *Your personal discount:* {discount}%"
        else:
            text += "✨ *Your personal discount:* none"
            
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
        
    discounts = load_discounts()
    if not discounts:
        await update.message.reply_text("📋 Список знижок порожній.")
        return
        
    lines = ["📋 *Список клієнтів зі знижками:*"]
    for tg_id, info in discounts.items():
        name = info.get("name", "Невідомо")
        pct = info.get("percent", 0)
        lines.append(f"• `{tg_id}` — *{name}*: {pct}%")
        
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
        
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "⚠️ Використання: `/discount <tg_id> <%> <ім'я>`\n"
            "Приклад: `/discount 710518293 20 Іра`",
            parse_mode="Markdown"
        )
        return
        
    tg_id_str = args[0]
    pct_str = args[1]
    name = " ".join(args[2:])
    
    if not tg_id_str.isdigit():
        await update.message.reply_text("❌ Помилка: `<tg_id>` має бути числом.")
        return
        
    if not pct_str.isdigit():
        await update.message.reply_text("❌ Помилка: `<%>` має бути цілим числом.")
        return
        
    pct = int(pct_str)
    if pct < 0 or pct > 100:
        await update.message.reply_text("❌ Помилка: відсоток знижки має бути від 0 до 100.")
        return
        
    discounts = load_discounts()
    discounts[tg_id_str] = {
        "percent": pct,
        "name": name
    }
    save_discounts(discounts)
    
    await update.message.reply_text(
        f"✅ Знижку встановлено!\n"
        f"👤 Клієнт: *{name}* (ID: `{tg_id_str}`)\n"
        f"✨ Розмір знижки: *{pct}%*",
        parse_mode="Markdown"
    )

async def cmd_undiscount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
        
    args = context.args
    if not args or len(args) < 1:
        await update.message.reply_text(
            "⚠️ Використання: `/undiscount <tg_id>`\n"
            "Приклад: `/undiscount 710518293`",
            parse_mode="Markdown"
        )
        return
        
    tg_id_str = args[0]
    discounts = load_discounts()
    if tg_id_str in discounts:
        removed_info = discounts.pop(tg_id_str)
        save_discounts(discounts)
        name = removed_info.get("name", "Невідомо")
        pct = removed_info.get("percent", 0)
        await update.message.reply_text(
            f"✅ Знижку видалено!\n"
            f"👤 Клієнт: *{name}* (ID: `{tg_id_str}`, була знижка {pct}%)",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Клієнта з ID `{tg_id_str}` немає у списку знижок.",
            parse_mode="Markdown"
        )

# ────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────

async def main():
    global global_app
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

    global_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    global_app.add_handler(CommandHandler("start", start))
    global_app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    global_app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    global_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    global_app.add_handler(CallbackQueryHandler(callback_handler))

    global_app.add_handler(CommandHandler("admin", cmd_admin))
    global_app.add_handler(CommandHandler("stoplist", cmd_stoplist))
    global_app.add_handler(CommandHandler("whoami", cmd_whoami))
    global_app.add_handler(CommandHandler("discounts", cmd_discounts))
    global_app.add_handler(CommandHandler("discount", cmd_discount))
    global_app.add_handler(CommandHandler("undiscount", cmd_undiscount))

    await global_app.initialize()
    await global_app.start()
    await global_app.updater.start_polling()

    asyncio.create_task(poll_stop_list())

    # Start AioHTTP server alongside the bot
    aiohttp_app = web.Application()
    aiohttp_app.router.add_post('/create-order', handle_create_order)
    aiohttp_app.router.add_get('/stop-list', handle_stop_list)

    runner = web.AppRunner(aiohttp_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    print(f"--- BOT STARTED & API RUNNING ON PORT {PORT} ---")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await site.stop()
        await global_app.updater.stop()
        await global_app.stop()
        await global_app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
