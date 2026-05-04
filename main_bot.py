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

MONOBANK_TOKEN = os.getenv("MONOBANK_TOKEN", "ueDogz4Hk_WJHyUqtE87o_5XVjOp_jP1J3E0UDci1Ips")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_FILE = os.path.join(BASE_DIR, "users_db.json")

# Default Web App URL
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://tymofiik-glitch.github.io/barista-agent-twa/")
PORT = int(os.getenv("PORT", "8080"))

LUNCH_PHONE_DISPLAY = "+380 66 939 4333"
PAYMENT_TIMEOUT_SEC = 15 * 60
PAID_TIMEOUT_SEC = 30 * 60

mono = MonobankClient(MONOBANK_TOKEN)
_raw_menu = get_menu_items()
menu_items = [it for it in _raw_menu if it.get("price", 0) > 0]
print(f"--- MENU INITIALIZED: {len(menu_items)} items ---")

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
    result = []
    for it in items or []:
        qty = int(it.get("quantity", it.get("qty", 1)))
        product_name = it.get("product", it.get("name", ""))
        if isinstance(product_name, dict):
            product_name = product_name.get("uk", product_name.get("en", str(product_name)))
        for _ in range(qty):
            result.append({
                "product": product_name,
                "quantity": 1,
                "comment": it.get("comment", "") or "",
            })
            for m in it.get("mods", []):
                m_name = m.get("name", "") if isinstance(m, dict) else m
                if isinstance(m_name, dict):
                    m_name = m_name.get("uk", m_name.get("en", str(m_name)))
                result.append({
                    "product": m_name,
                    "quantity": 1,
                    "comment": "",
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
            [KeyboardButton(t(lang, "btn_usual")), KeyboardButton(t(lang, "btn_lunch"))],
            [KeyboardButton(t(lang, "btn_settings"))],
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
            callback_data="lunch_call",
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
    if btn_key:
        if btn_key == "btn_make_order":
            await update.message.reply_text("Відкриваю додаток...")
        elif btn_key == "btn_usual":
            await update.message.reply_text(t(lang, "usual_no_yet"))
        elif btn_key == "btn_lunch":
            await show_lunch(update, context)
        elif btn_key == "btn_settings":
            await show_settings(update, context)
        return

    st = get_state(user_id)
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

async def create_monobank_invoice_and_notify(user_id: int, chat_id: int, items: list, arrival: str, comment: str, bot):
    lang = get_lang(user_id)
    st = get_state(user_id)
    st["cart"] = expand_cart(items)
    st["arrival"] = arrival
    st["comment"] = comment
    st["internal_id"] = f"{user_id}_{int(time.time())}"
    st["state"] = "CART_PENDING"

    total = get_order_total(st["cart"])
    if total <= 0:
        await bot.send_message(chat_id=chat_id, text=t(lang, "cant_calc"))
        return

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
        mods = it.get("modifiers") or it.get("mods") or []
        
        line = f"• {p_name} x{qty}"
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
                line += f" _(+ {', '.join(mod_names)})_"
        receipt_lines.append(line)
        
    receipt_lines.append("")
    receipt_lines.append(f"🕒 *Час:* {arrival_for_msg}")
    if comment:
        receipt_lines.append(f"📝 *Коментар:* {comment}")
        
    receipt_lines.append(f"\n💳 *До сплати: {total:.0f} ₴*")
    
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
# CALL QUERY HANDLER
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

    await global_app.initialize()
    await global_app.start()
    await global_app.updater.start_polling()

    # Start AioHTTP server alongside the bot
    aiohttp_app = web.Application()
    aiohttp_app.router.add_post('/create-order', handle_create_order)

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
