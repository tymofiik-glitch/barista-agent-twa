from __future__ import annotations

"""
Take A Break Bot — main_bot.py (фінальна версія)

ОНОВЛЕННЯ:
  + Новий формат промпту: arrival_time (час) і note_for_barista (коментар) — окремі поля
  + Апсейл як кнопка "🤔 Ще щось додати?" → категорії → 1-2 товари
  + Анти-апсейл: молчимо якщо корзина = їжа+напій, або сума ≥ 300 грн
  + Контекстний апсейл по часу дня
  + Чорний список товарів (тестові — не показуємо в апсейлі)
  + Повний розділ Налаштування (ім'я / телефон / мова / постійний заказ)
  + Двомовність (uk/en)
  + Кнопка tel: для бізнес-ланчу
  + Виправлений потік "Інший час" — текст БЕЗ виклику GPT
"""

import os
import re
import time
import json
import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from openai import AsyncOpenAI
from dotenv import load_dotenv
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

from monobank_client import MonobankClient
from poster_tools import (
    get_menu_items, _find_item_by_name, get_order_total, create_cafe_order,
)
from i18n import t, find_button_key, DICTS


# ────────────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MONOBANK_TOKEN = os.getenv("MONOBANK_TOKEN", "ueDogz4Hk_WJHyUqtE87o_5XVjOp_jP1J3E0UDci1Ips")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

DB_FILE = os.path.join(BASE_DIR, "users_db.json")
PROMPT_FILE = os.path.join(BASE_DIR, "barista_prompt.txt")

LUNCH_PHONE = "+380669394333"
LUNCH_PHONE_DISPLAY = "+380 66 939 4333"

CART_TIMEOUT_SEC = 10 * 60
PAYMENT_TIMEOUT_SEC = 15 * 60
PAID_TIMEOUT_SEC = 30 * 60
GPT_MODEL = "gpt-4o-mini"

HINT_SHOW_LIMIT = 2
ANTI_UPSELL_THRESHOLD_UAH = 300

# Чорний список — за ключовими словами в назві (lowercase, substring match)
PRODUCT_BLACKLIST = ["тест", "test", "фоп", "службов", "не використ"]

# Категорії апсейлу — ключові слова в назвах товарів
UPSELL_CATEGORIES = {
    "food": {
        "label_key": "cat_food",
        "keywords": ["круасан", "сендвіч", "клаб", "багет", "панін", "омлет", "яєчня",
                     "скрембл", "бенедикт", "шаурм", "бургер", "цезар", "салат"],
    },
    "dessert": {
        "label_key": "cat_dessert",
        "keywords": ["тарт", "трайфл", "мурашник", "кекс", "морквя", "чизкейк",
                     "тортик", "тірамісу", "брауні", "макарун", "десерт", "дріп"],
    },
    "cold": {
        "label_key": "cat_cold",
        "keywords": ["айс", "бамбл", "лимонад", "смузі", "сік", "холодн"],
    },
    "drink": {
        "label_key": "cat_drink",
        "keywords": ["капуч", "лате", "латте", "американ", "еспрес", "флет",
                     "раф", "матч", "какао", "чай", "кав"],
    },
}

# Розпізнавання напоїв (для антиапсейлу)
DRINK_KEYWORDS = UPSELL_CATEGORIES["drink"]["keywords"] + UPSELL_CATEGORIES["cold"]["keywords"]

INPUT_PLACEHOLDER_UK = "напр.: лате на безлактозному, через 10 хв"
INPUT_PLACEHOLDER_EN = "e.g.: latte on lactose-free, in 10 min"


client_openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
mono = MonobankClient(MONOBANK_TOKEN)


def _is_blacklisted(name: str) -> bool:
    n = (name or "").lower()
    return any(kw in n for kw in PRODUCT_BLACKLIST)


def _filter_menu(items: list) -> list:
    """Прибирає чорний список + товари з price=0."""
    return [it for it in items
            if it.get("price", 0) > 0
            and not _is_blacklisted(it.get("name", ""))]


# Завантажуємо меню один раз — фільтруємо одразу
_raw_menu = get_menu_items()
menu_items = _filter_menu(_raw_menu)
print(f"--- MENU FOR AI: {len(menu_items)} items (filtered from {len(_raw_menu)}) ---")
print(f"--- BLACKLIST removed {len(_raw_menu) - len(menu_items)} items ---")


# ────────────────────────────────────────────────────────────────────────
# STATE
# ────────────────────────────────────────────────────────────────────────

user_states: dict[int, dict] = {}
user_histories: dict[int, list] = {}


def _empty_state() -> dict:
    return {
        "state": "IDLE",
        "cart": [],
        "arrival": "по готовності",
        "comment": "",
        "internal_id": None,
        "invoice_id": None,
        "card_msg_id": None,
        "timeout_task": None,
        "confirming": False,
        "upsell_view": "main",  # main | categories | items | none
        "upsell_category": None,  # "food" / "dessert" / "cold" / "drink"
        "upsell_dismissed": False,  # клієнт вже бачив upsell-кнопку і не натиснув
        "settings_msg_id": None,
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
    
    s_id = st.get("settings_msg_id")
    user_states[user_id] = _empty_state()
    user_states[user_id]["settings_msg_id"] = s_id
    
    # Очищуємо історію листування з ШІ
    if user_id in user_histories:
        user_histories[user_id] = []


def expand_cart(items: list) -> list:
    result = []
    for it in items or []:
        qty = int(it.get("quantity", 1))
        for _ in range(qty):
            result.append({
                "product": it.get("product"),
                "quantity": 1,
                "comment": it.get("comment", "") or "",
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


def increment_hint_counter(tid: int) -> int:
    user = get_user(tid)
    cur = int(user.get("hint_shown_count", 0)) + 1
    save_user_field(tid, hint_shown_count=cur)
    return cur


def delete_user_field(tid: int, field: str):
    users = load_users()
    key = str(tid)
    if key in users and field in users[key]:
        del users[key][field]
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=4)


# ────────────────────────────────────────────────────────────────────────
# TIME PARSING
# ────────────────────────────────────────────────────────────────────────

def parse_arrival_time_field(raw: str) -> str:
    """
    Парсить поле arrival_time від GPT:
      "15:30" → "15:30"
      "+10"   → HH:MM (now+10)
      "now"   → "по готовності"
      ""      → ""  (нема часу — питаємо)
    """
    if not raw:
        return ""
    raw = raw.strip()
    if raw == "now":
        return "по готовності"
    if raw.startswith("+"):
        try:
            mins = int(raw[1:])
            return (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")
        except (ValueError, TypeError):
            return ""
    # "HH:MM" або "HH"
    m = re.match(r"^(\d{1,2}):?(\d{0,2})$", raw)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) else 0
        if 0 <= h <= 23 and 0 <= mm <= 59:
            return f"{h:02d}:{mm:02d}"
    return raw  # на крайній випадок — повертаємо як є


def parse_user_typed_time(text: str) -> str:
    """
    Парсить час, який клієнт ввів вручну (коли натиснув "Інший час"):
      "15:30" → "15:30"
      "о 14"  → "14:00"
      "через 20 хв" → now+20
      "за пів години" → now+30
      "зараз" → "по готовності"
    """
    text = text.strip().lower()

    if any(w in text for w in ["зараз", "одразу", "негайно", "now", "asap"]):
        return "по готовності"

    # "пів години", "через пів години"
    if "пів години" in text or "пів-години" in text or "halfhour" in text or "half hour" in text:
        return (datetime.now() + timedelta(minutes=30)).strftime("%H:%M")

    # "через N хв"
    m = re.search(r"(?:через|за|in|after)\s*(\d+)\s*(хв|хвилин|minute|min|m)?", text)
    if m:
        try:
            mins = int(m.group(1))
            return (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")
        except ValueError:
            pass

    # "о 14", "на 15:30", "at 3pm"
    m = re.search(r"(\d{1,2})[:\.\-](\d{2})", text)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm <= 59:
            return f"{h:02d}:{mm:02d}"

    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    # Не змогли — повертаємо як є, нехай хоч щось бариста побачить
    return text[:30]


def parse_time_choice(choice: str) -> str:
    """Для callback_data: time_now / time_15 / time_30."""
    suffix = choice.split("_", 1)[1] if "_" in choice else choice
    if suffix == "now":
        return "по готовності"
    try:
        minutes = int(suffix)
        return (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    except (ValueError, TypeError):
        return "по готовності"


# ────────────────────────────────────────────────────────────────────────
# UPSELL LOGIC
# ────────────────────────────────────────────────────────────────────────

def categorize_item(name: str) -> str | None:
    """Повертає 'food' / 'dessert' / 'cold' / 'drink' або None."""
    n = (name or "").lower()
    for cat, info in UPSELL_CATEGORIES.items():
        for kw in info["keywords"]:
            if kw in n:
                return cat
    return None


def is_drink(name: str) -> bool:
    return categorize_item(name) in ("drink", "cold")


def cart_categories(cart: list) -> set:
    """Повертає множину {'food', 'drink', ...} у поточній корзині."""
    result = set()
    for it in cart:
        cat = categorize_item(it.get("product", ""))
        if cat == "cold" or cat == "drink":
            result.add("drink")
        elif cat:
            result.add("food_or_dessert")
    return result


def should_show_upsell(cart: list) -> bool:
    """
    Анти-апсейл: показувати кнопку "🤔 Ще щось додати?" чи ні.
    Не показуємо якщо:
      - корзина порожня
      - корзина = їжа + напій (вже мікс)
      - сума ≥ 300 грн
    """
    if not cart:
        return False
    total = get_order_total(cart)
    if total >= ANTI_UPSELL_THRESHOLD_UAH:
        return False
    cats = cart_categories(cart)
    if "drink" in cats and "food_or_dessert" in cats:
        return False
    return True


def get_upsell_category_options(cart: list) -> list[dict]:
    """
    Повертає список категорій для апсейлу залежно від того що в корзині.
    Якщо в корзині напої — пропонуємо food + dessert.
    Якщо в корзині їжа — пропонуємо drink + cold.
    """
    cats = cart_categories(cart)
    options = []

    if "drink" in cats and "food_or_dessert" not in cats:
        # Напої → пропонуємо їжу
        options = [
            {"key": "food", "label_key": "cat_food"},
            {"key": "dessert", "label_key": "cat_dessert"},
        ]
    elif "food_or_dessert" in cats and "drink" not in cats:
        # Їжа → пропонуємо напої
        options = [
            {"key": "drink", "label_key": "cat_drink"},
            {"key": "cold", "label_key": "cat_cold"},
        ]
    return options


def get_items_for_category(cat_key: str, exclude_names: set, hour: int | None = None) -> list[dict]:
    """
    Повертає 1-2 товари з потрібної категорії, виключаючи те що вже в корзині.
    Враховує час дня (Ідея 1).
    """
    if hour is None:
        hour = datetime.now().hour

    keywords = UPSELL_CATEGORIES.get(cat_key, {}).get("keywords", [])
    candidates = []
    for it in menu_items:
        name = it.get("name", "")
        if name.strip().lower() in exclude_names:
            continue
        if it.get("type") == "mod":
            continue  # модифікатори не пропонуємо
        n_lower = name.lower()
        if any(kw in n_lower for kw in keywords):
            candidates.append(it)

    if not candidates:
        return []

    # Бустинг по часу дня (Ідея 1)
    def score(item):
        name_low = item["name"].lower()
        s = 0
        # Утром (7-11): круасани, сніданки — буст
        if 7 <= hour <= 11:
            if any(k in name_low for k in ["круасан", "омлет", "яєчн", "скрембл", "бенедикт"]):
                s -= 100  # буст (нижче за score = вище в списку)
        # Полдник (15-17): десерти — буст
        if 15 <= hour <= 17:
            if any(k in name_low for k in ["тарт", "трайфл", "мурашник", "кекс", "чизкейк"]):
                s -= 100
        # Обід (12-14): сендвічі, салати — буст
        if 12 <= hour <= 14:
            if any(k in name_low for k in ["сендвіч", "клаб", "салат", "цезар", "шаурм"]):
                s -= 100
        # Тоді — за ціною (дешевші зверху)
        s += item.get("price", 0)
        return s

    candidates.sort(key=score)
    return candidates[:2]


# ────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────────────────────────────

def main_kb(lang: str) -> ReplyKeyboardMarkup:
    placeholder = INPUT_PLACEHOLDER_UK if lang == "uk" else INPUT_PLACEHOLDER_EN
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(lang, "btn_make_order"))],
            [KeyboardButton(t(lang, "btn_usual")), KeyboardButton(t(lang, "btn_lunch"))],
            [KeyboardButton(t(lang, "btn_menu")), KeyboardButton(t(lang, "btn_settings"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=placeholder,
    )


def time_kb(lang: str, prefix: str = "time") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t(lang, "time_now"), callback_data=f"{prefix}_now"),
         InlineKeyboardButton(t(lang, "time_15"), callback_data=f"{prefix}_15")],
        [InlineKeyboardButton(t(lang, "time_30"), callback_data=f"{prefix}_30"),
         InlineKeyboardButton(t(lang, "time_other"), callback_data=f"{prefix}_other")],
    ]
    if prefix == "rtime":
        rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_cart")])
    return InlineKeyboardMarkup(rows)


def cart_kb(lang: str, internal_id: str, show_upsell_btn: bool, view: str = "main") -> InlineKeyboardMarkup:
    """
    view = 'main'       — головна картка з кнопкою "Ще щось додати?"
    view = 'categories' — показуємо вибір категорій апсейлу
    view = 'items'      — показуємо 1-2 товари з обраної категорії
    """
    rows = []

    if view == "main" and show_upsell_btn:
        rows.append([InlineKeyboardButton(t(lang, "btn_add_more"), callback_data="ups_open")])

    rows.append([InlineKeyboardButton(t(lang, "btn_confirm_pay"), callback_data=f"confirm_{internal_id}")])
    rows.append([
        InlineKeyboardButton(t(lang, "btn_edit"), callback_data=f"goedit_{internal_id}"),
        InlineKeyboardButton(t(lang, "btn_cancel"), callback_data="cancel_order"),
    ])
    return InlineKeyboardMarkup(rows)


def upsell_categories_kb(lang: str, options: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки вибору категорії апсейлу."""
    rows = []
    for opt in options:
        rows.append([InlineKeyboardButton(
            t(lang, opt["label_key"]),
            callback_data=f"ups_cat_{opt['key']}",
        )])
    rows.append([InlineKeyboardButton(t(lang, "btn_back_to_cart"), callback_data="ups_back_cart")])
    return InlineKeyboardMarkup(rows)


def upsell_items_kb(lang: str, items: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки конкретних товарів-апсейлу."""
    rows = []
    for it in items:
        # Лейбл: "➕ Назва — ціна"
        name = it["name"]
        short = name if len(name) <= 25 else name[:24] + "…"
        label = f"➕ {short} — {it['price']:.0f} грн"
        rows.append([InlineKeyboardButton(label, callback_data=f"ups_add_{it['id']}")])
    rows.append([InlineKeyboardButton(t(lang, "btn_back_to_categories"), callback_data="ups_back_cats")])
    return InlineKeyboardMarkup(rows)


def editing_kb(lang: str, cart: list) -> InlineKeyboardMarkup:
    rows = []
    for idx, item in enumerate(cart):
        name = item.get("product", "Товар")
        label = name if len(name) <= 22 else name[:21] + "…"
        rows.append([InlineKeyboardButton(f"❌ {label}", callback_data=f"rm_{idx}")])

    rows.append([
        InlineKeyboardButton(t(lang, "btn_change_time"), callback_data="edit_time"),
        InlineKeyboardButton(t(lang, "btn_comment"), callback_data="edit_comment"),
    ])
    rows.append([
        InlineKeyboardButton(t(lang, "btn_done"), callback_data="edit_done"),
        InlineKeyboardButton(t(lang, "btn_cancel"), callback_data="cancel_order"),
    ])
    return InlineKeyboardMarkup(rows)


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
        [InlineKeyboardButton(t(lang, "btn_set_phone"), callback_data="set_phone"),
         InlineKeyboardButton(t(lang, "btn_set_usual"), callback_data="set_usual")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_close")],
    ])


def lang_choice_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")],
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


def lunch_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t(lang, "btn_call", phone=LUNCH_PHONE_DISPLAY),
            callback_data="lunch_call",
        )],
    ])


# ────────────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────────────

def find_price_by_name(product_name: str) -> tuple[float, str | int]:
    found, err = _find_item_by_name(product_name, menu_items)
    if found:
        return float(found.get('price', 0.0)), found.get('id', 0)
    print(f"  [MISS] '{product_name}' not found! {err}")
    return 0.0, 0


def render_cart(state: dict, lang: str, editing: bool = False) -> str:
    if editing:
        lines = [t(lang, "editing_title"), ""]
    else:
        lines = [t(lang, "cart_title"), ""]

    total = 0.0
    for item in state["cart"]:
        name = item.get("product", "—")
        price, _ = find_price_by_name(name)
        total += price
        currency = "грн" if lang == "uk" else "UAH"
        lines.append(f"  • {name} — {price:.0f} {currency}")
        item_comment = item.get("comment")
        if item_comment:
            lines.append(f"     _{item_comment}_")

    if not state["cart"]:
        lines.append(t(lang, "cart_empty"))

    lines.append("")
    lines.append(t(lang, "cart_total", total=total))

    arrival = state.get("arrival") or t(lang, "ready_when")
    if arrival in ("по готовності", ""):
        arrival = t(lang, "ready_when")
    lines.append(t(lang, "cart_time", time=arrival))

    note = state.get("comment") or t(lang, "no_note")
    lines.append(t(lang, "cart_note", note=note))

    if editing:
        lines.append("")
        lines.append(t(lang, "editing_hint"))

    return "\n".join(lines)


def calc_total(cart: list) -> float:
    return get_order_total(cart)


# ────────────────────────────────────────────────────────────────────────
# GPT
# ────────────────────────────────────────────────────────────────────────

EDITING_SYSTEM_PROMPT = """Ти помічник у режимі редагування корзини кав'ярні.
Клієнт уже має корзину і хоче її змінити. Поверни ТІЛЬКИ JSON.

Можливі інтенти (intent):
  - "add"             — додати позиції; items: [{product, quantity, comment}]
  - "remove"          — прибрати позиції; items: [{product, quantity}]
  - "clear"           — очистити корзину
  - "change_comment"  — змінити коментар; comment: "..."
  - "change_time"     — клієнт хоче змінити час
  - "done"            — клієнт каже "все" / "готово"
  - "noop"            — не зрозумів

Використовуй ТІЛЬКИ назви товарів зі списку меню.
"""


def _menu_text_for_prompt() -> str:
    return "\n".join(
        f"- {i['name']} ({i['price']:.2f} грн)"
        for i in menu_items if i.get("price", 0) > 0
    )


async def gpt_parse_normal(user_text: str, history: list):
    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            prompt = f.read()
    except Exception:
        prompt = "Ти бариста. Відповідай у JSON."

    system_msg = (
        prompt
        + "\n\n[ПОТОЧНЕ МЕНЮ ЗАКЛАДУ]:\n"
        + _menu_text_for_prompt()
        + "\n\nIMPORTANT: ALWAYS respond in valid JSON."
    )

    response = await client_openai.chat.completions.create(
        model=GPT_MODEL,
        messages=[{"role": "system", "content": system_msg}] + history[-5:],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw), raw


async def gpt_parse_editing(user_text: str, current_cart: list) -> dict:
    cart_summary = ", ".join(it["product"] for it in current_cart) or "(пуста)"
    system_msg = (
        EDITING_SYSTEM_PROMPT
        + f"\n\nПоточна корзина: {cart_summary}"
        + "\n\nМеню:\n" + _menu_text_for_prompt()
    )
    response = await client_openai.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_text},
        ],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


# ────────────────────────────────────────────────────────────────────────
# TIMEOUTS
# ────────────────────────────────────────────────────────────────────────

async def cart_timeout(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.sleep(CART_TIMEOUT_SEC)
        st = get_state(user_id)
        if st["state"] in ("CART_PENDING", "EDITING"):
            try:
                if st.get("card_msg_id"):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=st["card_msg_id"],
                        text="⏰ Замовлення скасовано через неактивність.\nНапиши знову, коли захочеш ☕",
                    )
            except Exception as e:
                logging.warning(f"cart_timeout edit failed: {e}")
            reset_state(user_id)
    except asyncio.CancelledError:
        pass


async def _paid_to_idle(user_id: int):
    try:
        await asyncio.sleep(PAID_TIMEOUT_SEC)
        st = user_states.get(user_id)
        if st and st["state"] == "PAID":
            reset_state(user_id)
    except asyncio.CancelledError:
        pass


def _restart_cart_timeout(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    st = get_state(user_id)
    if st.get("timeout_task") and not st["timeout_task"].done():
        st["timeout_task"].cancel()
    st["timeout_task"] = asyncio.create_task(cart_timeout(user_id, chat_id, context))


async def redraw_card(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Перемальовує живу картку в поточному стейті."""
    st = get_state(user_id)
    lang = get_lang(user_id)
    if not st.get("card_msg_id"):
        return

    is_editing = st["state"] == "EDITING"

    if is_editing:
        text = render_cart(st, lang, editing=True)
        kb = editing_kb(lang, st["cart"])
    else:
        text = render_cart(st, lang)
        view = st.get("upsell_view", "main")
        if view == "categories":
            options = get_upsell_category_options(st["cart"])
            if not options:
                # категорій немає — повертаємось до головного вигляду
                st["upsell_view"] = "main"
                kb = cart_kb(lang, st["internal_id"], show_upsell_btn=should_show_upsell(st["cart"]))
            else:
                # Додаємо текст з підказкою
                text = text + "\n\n" + t(lang, "upsell_chooser")
                kb = upsell_categories_kb(lang, options)
        elif view == "items":
            cat_key = st.get("upsell_category")
            exclude = {it.get("product", "").strip().lower() for it in st["cart"]}
            items = get_items_for_category(cat_key, exclude_names=exclude)
            if not items:
                # У категорії нічого немає — даємо знати
                text = text + "\n\n" + t(lang, "cat_empty")
                # Кнопка "до категорій"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(lang, "btn_back_to_categories"), callback_data="ups_back_cats")],
                ])
            else:
                kb = upsell_items_kb(lang, items)
        else:
            kb = cart_kb(lang, st["internal_id"], show_upsell_btn=should_show_upsell(st["cart"]))

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=st["card_msg_id"],
            text=text, reply_markup=kb, parse_mode="Markdown",
        )
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            return
        
        logging.warning(f"redraw_card failed: {e}")
        # Якщо повідомлення видалено або не знайдено — відправляємо нове
        if "message to edit not found" in err_str or "message can't be edited" in err_str:
            try:
                sent = await context.bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=kb, parse_mode="Markdown"
                )
                st["card_msg_id"] = sent.message_id
                logging.info(f"Sent new card because old one was missing (ID: {sent.message_id})")
            except Exception as e2:
                logging.error(f"Failed to even send a NEW card: {e2}")


# ────────────────────────────────────────────────────────────────────────
# /start, contact
# ────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    uid = str(user_id)
    users = load_users()
    lang = get_lang(user_id)

    st = get_state(user_id)
    if st["state"] in ("CART_PENDING", "EDITING", "AWAITING_PAYMENT"):
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

    # Якщо це зміна номера в налаштуваннях
    st = get_state(user_id)
    if st["state"] == "AWAITING_NEW_PHONE":
        save_user_field(user_id, phone=c.phone_number)
        st["state"] = "IDLE"
        # Видаляємо повідомлення з кнопкою "Надіслати номер"
        try:
            await update.message.delete()
        except Exception:
            pass
        
        # Редагуємо налаштування назад
        if st.get("settings_msg_id"):
            await show_settings(update, context, edit=True)
        else:
            await update.message.reply_text(t(lang, "saved"), reply_markup=main_kb(lang))
        return

    # Інакше — реєстрація
    save_user(user_id, c.first_name, c.phone_number)
    reset_state(user_id)
    name = (c.first_name or "друже").capitalize()
    await update.message.reply_text(
        t(lang, "after_register", name=name),
        reply_markup=main_kb(lang),
    )

    # Туторіал — тільки один раз
    user = get_user(user_id)
    if not user.get("tutorial_shown"):
        await update.message.reply_text(t(lang, "tutorial"), parse_mode="Markdown")
        save_user_field(user_id, tutorial_shown=True)


# ────────────────────────────────────────────────────────────────────────
# Кнопки головної клавіатури
# ────────────────────────────────────────────────────────────────────────

async def show_lunch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        t(lang, "lunch_text", phone=LUNCH_PHONE_DISPLAY),
        reply_markup=lunch_kb(lang),
        parse_mode="Markdown",
    )


async def show_menu_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(t(lang, "menu_stub"), parse_mode="Markdown")


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    user = get_user(user_id)
    name = user.get("name", "—").capitalize()
    phone = user.get("phone", "—")
    lang_label = t(lang, "settings_lang_uk_label") if lang == "uk" else t(lang, "settings_lang_en_label")
    usual = user.get("usual_order")
    if usual:
        parts = []
        for it in usual:
            p_name = it.get("product", "")
            qty = it.get("quantity", 1)
            parts.append(f"{p_name} x{qty}")
        usual_str = ", ".join(parts)
    else:
        usual_str = t(lang, "settings_no_usual")

    text = t(lang, "settings_title", name=name, phone=phone, lang=lang_label, usual=usual_str)
    reply_markup = settings_kb(lang)

    if edit and update.callback_query:
        sent = await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        sent = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    st["settings_msg_id"] = sent.message_id


async def prompt_for_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(t(lang, "listening"), parse_mode="Markdown")


async def show_usual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = get_lang(user_id)
    user = get_user(user_id)
    usual = user.get("usual_order")
    st = get_state(user_id)

    if st["state"] in ("CART_PENDING", "EDITING") and usual:
        st["cart"].extend(expand_cart(usual))
        # Якщо це було натискання кнопки головного меню — шлемо тост або коротке повідомлення.
        # Оскільки кнопки головного меню не мають callback_query, тост не вийде.
        # Але ми можемо просто перемалювати картку.
        if st.get("card_msg_id"):
            await redraw_card(user_id, chat_id, context)
            # Якщо повідомлення було від юзера (кнопка меню), можемо видалити його для чистоти
            try:
                await update.message.delete()
            except Exception:
                pass
        else:
            # Створюємо нову картку
            await show_card_for_first_time(
                user_id, chat_id, context,
                items=st["cart"], arrival="по готовності", comment="",
            )
        _restart_cart_timeout(user_id, chat_id, context)
        return

    if not usual:
        st["state"] = "AWAITING_USUAL_SETUP"
        await update.message.reply_text(t(lang, "usual_setup"), parse_mode="Markdown")
        return

    expanded = expand_cart(usual)
    missing = [it["product"] for it in expanded if find_price_by_name(it["product"])[1] == 0]
    if missing:
        await update.message.reply_text(
            t(lang, "usual_missing_items", names=", ".join(set(missing))),
            parse_mode="Markdown",
        )
        return

    st["cart"] = expanded
    st["arrival"] = "по готовності"
    st["comment"] = ""
    st["upsell_view"] = "main"
    st["internal_id"] = f"{user_id}_{int(time.time())}"
    st["state"] = "CART_PENDING"

    sent = await context.bot.send_message(
        chat_id=chat_id, text=render_cart(st, lang),
        reply_markup=cart_kb(lang, st["internal_id"], show_upsell_btn=should_show_upsell(st["cart"])),
        parse_mode="Markdown",
    )
    st["card_msg_id"] = sent.message_id
    _restart_cart_timeout(user_id, chat_id, context)


# ────────────────────────────────────────────────────────────────────────
# Допоміжні
# ────────────────────────────────────────────────────────────────────────

async def show_card_for_first_time(
    user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
    items: list, arrival: str, comment: str,
):
    """Створює живу картку. Викликається коли заказ готовий (час уже відомий)."""
    st = get_state(user_id)
    lang = get_lang(user_id)
    st["cart"] = expand_cart(items)
    st["arrival"] = arrival or "по готовності"
    st["comment"] = comment or ""
    st["upsell_view"] = "main"
    st["internal_id"] = f"{user_id}_{int(time.time())}"
    st["state"] = "CART_PENDING"

    sent = await context.bot.send_message(
        chat_id=chat_id, text=render_cart(st, lang),
        reply_markup=cart_kb(lang, st["internal_id"], show_upsell_btn=should_show_upsell(st["cart"])),
        parse_mode="Markdown",
    )
    st["card_msg_id"] = sent.message_id
    _restart_cart_timeout(user_id, chat_id, context)


async def ask_time_with_hint(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(user_id)
    user = get_user(user_id)
    shown = int(user.get("hint_shown_count", 0))

    if shown < HINT_SHOW_LIMIT:
        text = t(lang, "what_time_hint")
        increment_hint_counter(user_id)
    else:
        text = t(lang, "what_time")

    await context.bot.send_message(
        chat_id=chat_id, text=text,
        reply_markup=time_kb(lang, "time"),
        parse_mode="Markdown",
    )


# ────────────────────────────────────────────────────────────────────────
# Обробка тексту
# ────────────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    lang = get_lang(user_id)

    # Кнопки головної клавіатури — розпізнаємо по будь-якій мові
    btn_key = find_button_key(user_text)
    if btn_key:
        if btn_key == "btn_make_order":
            await prompt_for_order(update, context)
        elif btn_key == "btn_usual":
            await show_usual(update, context)
        elif btn_key == "btn_lunch":
            await show_lunch(update, context)
        elif btn_key == "btn_menu":
            await show_menu_stub(update, context)
        elif btn_key == "btn_settings":
            await show_settings(update, context)
        return

    st = get_state(user_id)

    # ── AWAITING_NEW_NAME (зміна імені)
    if st["state"] == "AWAITING_NEW_NAME":
        new_name = user_text[:40] or "—"
        save_user_field(user_id, name=new_name)
        st["state"] = "IDLE"
        
        # Видаляємо повідомлення юзера (опціонально для чистоти)
        try:
            await update.message.delete()
        except Exception:
            pass
            
        # Оновлюємо картку налаштувань
        if st.get("settings_msg_id"):
            await show_settings(update, context, edit=True)
        else:
            await update.message.reply_text(
                t(lang, "name_saved", name=new_name.capitalize()),
                reply_markup=main_kb(lang),
            )
        return

    # ── AWAITING_USUAL_SETUP
    if st["state"] == "AWAITING_USUAL_SETUP":
        try:
            res, _ = await gpt_parse_normal(user_text, [{"role": "user", "content": user_text}])
        except Exception as e:
            logging.error(f"usual_setup gpt error: {e}")
            await update.message.reply_text(t(lang, "didnt_understand"))
            return

        if res.get("action") != "place_order":
            await update.message.reply_text(t(lang, "usual_describe_again"))
            return

        items = res.get("parameters", {}).get("items", [])
        if not items:
            await update.message.reply_text(t(lang, "didnt_understand"))
            return

        missing = [it.get("product") for it in items if find_price_by_name(it.get("product", ""))[1] == 0]
        if missing:
            await update.message.reply_text(
                t(lang, "not_in_menu", names=", ".join(missing)),
                parse_mode="Markdown",
            )
            return

        save_user_field(user_id, usual_order=items)
        reset_state(user_id)
        
        # Видаляємо повідомлення юзера
        try:
            await update.message.delete()
        except Exception:
            pass

        if st.get("settings_msg_id"):
            await show_settings(update, context, edit=True)
        else:
            await update.message.reply_text(t(lang, "usual_saved"), parse_mode="Markdown")
        return

    # ── AWAITING_EDIT_COMMENT
    if st["state"] == "AWAITING_EDIT_COMMENT":
        st["comment"] = user_text
        st["state"] = "EDITING"
        
        # Видаляємо повідомлення юзера
        try:
            await update.message.delete()
        except Exception:
            pass
            
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── AWAITING_TIME та AWAITING_OTHER_TIME — клієнт пише час БЕЗ виклику GPT
    if st["state"] in ("AWAITING_TIME", "AWAITING_OTHER_TIME"):
        st["arrival"] = parse_user_typed_time(user_text)
        st["state"] = "CART_PENDING"
        
        # Видаляємо повідомлення юзера
        try:
            await update.message.delete()
        except Exception:
            pass

        if st.get("card_msg_id"):
            await redraw_card(user_id, chat_id, context)
        else:
            # картки ще немає — створюємо
            await show_card_for_first_time(
                user_id, chat_id, context,
                items=st["cart"], arrival=st["arrival"], comment=st.get("comment", ""),
            )
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── AWAITING_OTHER_TIME_EDIT — те ж саме, але з режиму редагування
    if st["state"] == "AWAITING_OTHER_TIME_EDIT":
        st["arrival"] = parse_user_typed_time(user_text)
        st["state"] = "EDITING"
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── EDITING (текстом)
    if st["state"] == "EDITING":
        try:
            res = await gpt_parse_editing(user_text, st["cart"])
        except Exception as e:
            logging.error(f"editing gpt error: {e}")
            await update.message.reply_text(t(lang, "edit_didnt_understand"))
            return

        intent = res.get("intent", "noop")
        if intent == "add":
            new_items = res.get("items", [])
            missing = [it.get("product") for it in new_items if find_price_by_name(it.get("product", ""))[1] == 0]
            if missing:
                await update.message.reply_text(
                    t(lang, "not_in_menu", names=", ".join(missing)),
                    parse_mode="Markdown",
                )
                return
            st["cart"].extend(expand_cart(new_items))
            await redraw_card(user_id, chat_id, context)
        elif intent == "remove":
            to_remove = res.get("items", [])
            for rm in to_remove:
                name = (rm.get("product") or "").strip().lower()
                qty = int(rm.get("quantity", 1))
                new_cart = []
                for it in st["cart"]:
                    if it.get("product", "").lower() == name and qty > 0:
                        qty -= 1
                    else:
                        new_cart.append(it)
                st["cart"] = new_cart
            if not st["cart"]:
                await update.message.reply_text(t(lang, "cart_empty_cancelled"))
                reset_state(user_id)
                return
            await redraw_card(user_id, chat_id, context)
        elif intent == "clear":
            reset_state(user_id)
            await update.message.reply_text(t(lang, "cancelled_short"))
            return
        elif intent == "change_comment":
            st["comment"] = res.get("comment", "")
            await redraw_card(user_id, chat_id, context)
        elif intent == "change_time":
            await update.message.reply_text(t(lang, "what_time"), reply_markup=time_kb(lang, "rtime"))
        elif intent == "done":
            st["state"] = "CART_PENDING"
            await redraw_card(user_id, chat_id, context)
        else:
            await update.message.reply_text(t(lang, "edit_didnt_understand"))
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── AWAITING_PAYMENT
    if st["state"] == "AWAITING_PAYMENT":
        await update.message.reply_text(t(lang, "awaiting_payment"))
        return

    # ── PAID
    if st["state"] == "PAID":
        await update.message.reply_text(
            t(lang, "paid_new_q"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn_yes_new"), callback_data="new_order")],
                [InlineKeyboardButton(t(lang, "btn_no"), callback_data="keep_paid")],
            ]),
        )
        return

    # ── Звичайний шлях: парсимо новий заказ
    history = user_histories.get(user_id, [])
    history.append({"role": "user", "content": user_text})

    try:
        res, raw = await gpt_parse_normal(user_text, history)
        user_histories[user_id] = (history + [{"role": "assistant", "content": raw}])[-10:]

        print(f"\n[OPENAI RESPONSE]\n{json.dumps(res, ensure_ascii=False, indent=2)}")

        if res.get("action") == "place_order":
            params = res.get("parameters", {})
            items = params.get("items", [])
            if not items:
                await update.message.reply_text(t(lang, "didnt_understand"))
                return

            missing = [it.get("product") for it in items if find_price_by_name(it.get("product", ""))[1] == 0]
            if missing:
                await update.message.reply_text(
                    t(lang, "not_in_menu", names=", ".join(missing)),
                    parse_mode="Markdown",
                )
                return

            # Парсимо НОВИЙ формат: arrival_time + note_for_barista
            arrival_raw = (params.get("arrival_time") or "").strip()
            arrival = parse_arrival_time_field(arrival_raw)
            note = params.get("note_for_barista") or ""

            # Якщо час уже відомий — пропускаємо AWAITING_TIME
            time_known = arrival and arrival != ""

            if time_known:
                await show_card_for_first_time(
                    user_id, chat_id, context,
                    items=items, arrival=arrival, comment=note,
                )
            else:
                # Зберігаємо корзину тимчасово і питаємо час
                st["cart"] = expand_cart(items)
                st["arrival"] = "по готовності"
                st["comment"] = note
                st["state"] = "AWAITING_TIME"
                await ask_time_with_hint(user_id, chat_id, context)
        else:
            # action = reply
            reply_text = (
                res.get("reply")
                or res.get("parameters", {}).get("message")
                or t(lang, "ok")
            )
            await update.message.reply_text(reply_text)

    except Exception as e:
        logging.error(f"handle_message error: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(t(lang, "something_wrong"))


# ────────────────────────────────────────────────────────────────────────
# Callbacks
# ────────────────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "lunch_call":
        await query.answer(LUNCH_PHONE_DISPLAY, show_alert=True)
        return

    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    lang = get_lang(user_id)
    st = get_state(user_id)

    # ── Час при першому замовленні
    if data.startswith("time_"):
        suffix = data.split("_", 1)[1]
        if suffix == "other":
            st["state"] = "AWAITING_OTHER_TIME"
            await query.message.edit_text(t(lang, "ask_other_time"), parse_mode="Markdown")
            return

        st["arrival"] = parse_time_choice(data)
        try:
            await query.message.delete()
        except Exception:
            pass
        await show_card_for_first_time(
            user_id, chat_id, context,
            items=st["cart"], arrival=st["arrival"], comment=st.get("comment", ""),
        )
        return

    # ── Час у режимі редагування
    if data.startswith("rtime_"):
        suffix = data.split("_", 1)[1]
        if suffix == "other":
            st["state"] = "AWAITING_OTHER_TIME_EDIT"
            await query.message.edit_text(t(lang, "ask_other_time"), parse_mode="Markdown")
            return
        st["arrival"] = parse_time_choice(data)
        try:
            await query.message.delete()
        except Exception:
            pass
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── Перейти в режим редагування
    if data.startswith("goedit_"):
        if st["state"] != "CART_PENDING":
            await query.answer(t(lang, "still_inactive"), show_alert=True)
            return
        st["state"] = "EDITING"
        st["upsell_view"] = "main"  # скидаємо щоб не глючило
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── Видалити позицію з корзини
    if data.startswith("rm_"):
        try:
            idx = int(data.split("_")[1])
        except (ValueError, IndexError):
            return
        if 0 <= idx < len(st["cart"]):
            st["cart"].pop(idx)
        if not st["cart"]:
            try:
                await query.message.edit_text(t(lang, "cart_empty_cancelled"))
            except Exception:
                pass
            reset_state(user_id)
            return
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    # ── Кнопки в режимі редагування
    if data == "edit_time":
        await query.answer()
        await query.edit_message_text(
            t(lang, "what_time"),
            reply_markup=time_kb(lang, "rtime"), parse_mode="Markdown",
        )
        return

    if data == "edit_comment":
        await query.answer()
        st["state"] = "AWAITING_EDIT_COMMENT"
        await query.edit_message_text(
            t(lang, "type_comment"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_cart")]])
        )
        return

    if data == "set_back_cart":
        await query.answer()
        st["state"] = "EDITING"
        await redraw_card(user_id, chat_id, context)
        return

    if data == "edit_done":
        st["state"] = "CART_PENDING"
        await redraw_card(user_id, chat_id, context)
        return

    if data == "cancel_order":
        try:
            await query.message.edit_text(t(lang, "order_cancelled"))
        except Exception:
            pass
        reset_state(user_id)
        return

    # ── АПСЕЛ-ЧУЗЕР
    if data == "ups_open":
        if st["state"] != "CART_PENDING":
            return
        options = get_upsell_category_options(st["cart"])
        if not options:
            return
        st["upsell_view"] = "categories"
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    if data.startswith("ups_cat_"):
        cat_key = data.split("_", 2)[2]
        st["upsell_category"] = cat_key
        st["upsell_view"] = "items"
        await redraw_card(user_id, chat_id, context)
        _restart_cart_timeout(user_id, chat_id, context)
        return

    if data.startswith("ups_add_"):
        item_id = data.split("_", 2)[2]
        # Знаходимо товар у меню
        found = None
        for it in menu_items:
            if str(it.get("id", "")) == str(item_id):
                found = it
                break
        if found:
            st["cart"].append({"product": found["name"], "quantity": 1, "comment": ""})
            st["upsell_view"] = "main"
            await redraw_card(user_id, chat_id, context)
            _restart_cart_timeout(user_id, chat_id, context)
        return

    if data == "ups_back_cart":
        st["upsell_view"] = "main"
        await redraw_card(user_id, chat_id, context)
        return

    if data == "ups_back_cats":
        st["upsell_view"] = "categories"
        await redraw_card(user_id, chat_id, context)
        return

    # ── Підтвердження → інвойс
    if data.startswith("confirm_"):
        if st.get("confirming"):
            await query.answer(t(lang, "creating_invoice_wait"), show_alert=False)
            return
        if st["state"] not in ("CART_PENDING",):
            await query.answer(t(lang, "still_inactive"), show_alert=True)
            return

        st["confirming"] = True
        try:
            total = calc_total(st["cart"])
            if total <= 0:
                await query.answer(t(lang, "cant_calc"), show_alert=True)
                st["confirming"] = False
                return

            if st.get("timeout_task") and not st["timeout_task"].done():
                st["timeout_task"].cancel()

            basket_order = []
            for it in st["cart"]:
                p_name = it["product"]
                p_price, _ = find_price_by_name(p_name)
                basket_order.append({
                    "name": p_name, "qty": 1, "sum": int(p_price * 100),
                    "icon": "☕", "unit": "шт",
                })

            inv = await mono.create_invoice(
                amount_kopecks=int(round(total * 100)),
                reference=st["internal_id"],
                basket_order=basket_order,
                validity_seconds=PAYMENT_TIMEOUT_SEC,
            )
            if not inv:
                await query.message.edit_text(
                    t(lang, "invoice_failed"),
                    reply_markup=retry_payment_kb(lang, st["internal_id"]),
                )
                st["confirming"] = False
                return

            st["invoice_id"] = inv["invoiceId"]
            st["state"] = "AWAITING_PAYMENT"
            st["confirming"] = False

            arrival_for_msg = st.get("arrival") or t(lang, "ready_when")
            if arrival_for_msg in ("по готовності", ""):
                arrival_for_msg = t(lang, "ready_when")

            await query.message.edit_text(
                t(lang, "ready_to_pay", total=total, time=arrival_for_msg),
                reply_markup=pay_kb(lang, inv["pageUrl"]),
                parse_mode="Markdown",
            )

            asyncio.create_task(poll_payment(user_id, chat_id, context, query.message.message_id))
        except Exception as e:
            logging.error(f"Confirm error: {e}\n{traceback.format_exc()}")
            st["confirming"] = False
            await query.answer(t(lang, "something_wrong"), show_alert=True)
        return

    # ── Скасування під час оплати
    if data == "cancel_payment":
        if st.get("invoice_id"):
            await mono.cancel_invoice(st["invoice_id"])
        try:
            await query.message.edit_text(t(lang, "order_cancelled"))
        except Exception:
            pass
        reset_state(user_id)
        return

    # ── /start під час замовлення
    if data == "reset_to_idle":
        if st.get("invoice_id"):
            await mono.cancel_invoice(st["invoice_id"])
        reset_state(user_id)
        await query.message.edit_text(t(lang, "fresh_start"))
        users = load_users()
        name = users.get(str(user_id), {}).get("name", "друже").capitalize()
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, "greet_known", name=name),
            reply_markup=main_kb(lang),
        )
        return

    if data == "keep_current":
        await query.message.edit_text(t(lang, "keep_current"))
        return

    if data == "new_order":
        reset_state(user_id)
        await query.message.edit_text(t(lang, "ok_new_order"))
        return

    if data == "keep_paid":
        await query.message.edit_text(t(lang, "ok"))
        return

    if data == "order_again":
        reset_state(user_id)
        await context.bot.send_message(
            chat_id=chat_id, text=t(lang, "ok_lets_continue"),
            reply_markup=main_kb(lang),
        )
        return

    # ── НАЛАШТУВАННЯ
    if data == "set_close":
        await query.answer()
        try:
            # Просто видаляємо повідомлення налаштувань
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "set_name":
        await query.answer()
        st["state"] = "AWAITING_NEW_NAME"
        # Замість видалення картки — пишемо в ній інструкцію
        await query.edit_message_text(
            t(lang, "ask_new_name"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")]])
        )
        return

    if data == "set_back_main":
        await query.answer()
        st["state"] = "IDLE"
        await show_settings(update, context, edit=True)
        return

    if data == "set_lang":
        await query.answer()
        await query.edit_message_text(t(lang, "ask_lang"), reply_markup=lang_choice_kb(lang))
        return

    if data == "lang_uk":
        await query.answer()
        save_user_field(user_id, lang="uk")
        await show_settings(update, context, edit=True)
        return

    if data == "lang_en":
        await query.answer()
        save_user_field(user_id, lang="en")
        await show_settings(update, context, edit=True)
        return

    if data == "set_phone":
        await query.answer()
        st["state"] = "AWAITING_NEW_PHONE"
        # Для телефону потрібна ReplyKeyboardMarkup, тому доведеться послати нове повідомлення,
        # але ми видалимо картку налаштувань тимчасово або просто закриємо її.
        await query.message.delete()
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, "ask_new_phone"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(t(lang, "send_phone_btn"), request_contact=True)]],
                one_time_keyboard=True, resize_keyboard=True,
            ),
        )
        # Зберігаємо ID цього повідомлення, щоб потім видалити
        # (Хоча воно і так зникне з one_time_keyboard, але краще видалити вручну)
        return

    if data == "set_usual":
        await query.answer()
        user = get_user(user_id)
        usual = user.get("usual_order")
        if usual:
            summary_lines = []
            for it in usual:
                qty = int(it.get("quantity", 1))
                line = f"• {it.get('product')}" + (f" × {qty}" if qty > 1 else "")
                if it.get("comment"):
                    line += f" _({it['comment']})_"
                summary_lines.append(line)
            text = t(lang, "usual_view", summary="\n".join(summary_lines))
        else:
            text = t(lang, "usual_no_yet")
        
        await query.edit_message_text(
            text, reply_markup=usual_view_kb(lang, has_usual=bool(usual)),
            parse_mode="Markdown",
        )
        return

    if data == "usual_change":
        await query.answer()
        st["state"] = "AWAITING_USUAL_SETUP"
        await query.edit_message_text(
            t(lang, "usual_setup"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_back"), callback_data="set_back_main")]]),
            parse_mode="Markdown"
        )
        return

    if data == "usual_delete":
        save_user_field(user_id, usual_order=None)
        await query.answer(t(lang, "usual_deleted")) # Тост!
        await show_settings(update, context, edit=True)
        return


# ────────────────────────────────────────────────────────────────────────
# Polling статусу + Poster
# ────────────────────────────────────────────────────────────────────────

async def poll_payment(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE, msg_id: int):
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


async def handle_successful_payment(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    st = get_state(user_id)
    lang = get_lang(user_id)
    user = get_user(user_id)
    client_name = user.get("name", "Гість")
    client_phone = user.get("phone", "")

    poster_items = [
        {"product": it.get("product"), "quantity": it.get("quantity", 1), "comment": it.get("comment", "")}
        for it in st["cart"]
    ]

    arrival = st.get("arrival") or "по готовності"
    poster_comment_parts = [f"Час: {arrival}"]
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
        cart_lines.append(f"  • {name}" + (f" × {qty}" if qty > 1 else ""))
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
        logging.error(f"⚠️ ALERT: payment OK but Poster create failed for user {user_id}")

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=msg,
            reply_markup=post_paid_kb(lang),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.warning(f"edit success msg failed: {e}")
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=post_paid_kb(lang), parse_mode="Markdown")

    st["state"] = "PAID"
    if st.get("timeout_task") and not st["timeout_task"].done():
        st["timeout_task"].cancel()
    st["timeout_task"] = asyncio.create_task(_paid_to_idle(user_id))


async def handle_failed_payment(
    user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
    msg_id: int, status_str: str,
):
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
    except Exception as e:
        logging.warning(f"edit failed payment: {e}")

    _restart_cart_timeout(user_id, chat_id, context)


# ────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("--- BOT STARTED ---")
    app.run_polling()


if __name__ == "__main__":
    main()
