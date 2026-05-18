from __future__ import annotations

"""
i18n.py — українські та англійські тексти.

Використання:
  from i18n import t
  t(lang, "key", **format_kwargs)
"""

UK = {
    # /start
    "greet_known": "Привіт, {name}! Що приготуємо? ☕",
    "greet_new": "Привіт! Надішли номер для реєстрації.",
    "send_phone_btn": "📞 Надіслати номер",
    "after_register": "Дякую, {name}! ☕",
    "tutorial": (
        "💡 Невелика підказка для зручності:\n\n"
        "Можеш писати замовлення *одним повідомленням* — я зрозумію все одразу.\n\n"
        "Наприклад:\n"
        "• _«лате»_\n"
        "• _«два капуч, зараз»_\n"
        "• _«латте на кокосовому + круасан, через 15 хв»_\n\n"
        "Спробуй ⬇"
    ),

    # Main keyboard
    "btn_make_order": "⚡ ЗАМОВИТИ ТУТ ⚡",
    "btn_usual": "☕ Як завжди",
    "btn_lunch": "🏢 Для компаній & Фуршети",
    "btn_menu": "📖 Меню",
    "btn_settings": "⚙️ Налаштування",
    "btn_feedback": "💬 Залишити відгук",
    "ask_feedback": "💬 Напиши свій відгук, побажання або пропозицію. Я одразу передам її власнику! 👇",
    "feedback_saved": "Дякую за твій відгук! Передав його керівнику. ☕",
    "input_placeholder": "напр.: лате на безлактозному, через 10 хв",

    # Order flow
    "listening": (
        "Слухаю ☕\n\n"
        "💡 Можеш одразу написати все: _«два лате на безлактозному, через 10 хв»_ — "
        "оформлю замовлення в один клік.\n\n"
        "Або просто назви напій — я перепитаю про час."
    ),
    "what_time": "🕒 *Коли тебе чекати?*",
    "what_time_hint": (
        "🕒 *Коли тебе чекати?*\n\n"
        "💡 _Наступного разу можеш написати все одразу — наприклад: «лате через 15 хв» — "
        "і пропустиш цей крок._"
    ),
    "time_now": "⚡ Зараз",
    "time_15": "Через 15 хв",
    "time_30": "Через 30 хв",
    "time_other": "Інший час",
    "ask_other_time": "🕒 Напиши час словами або числом (наприклад: _15:30_, _через 20 хв_, _о 14_).",

    # Cart
    "cart_title": "☕️ *Твоє замовлення*",
    "cart_empty": "  _корзина порожня_",
    "cart_total": "💰 *Разом: {total:.0f} грн*",
    "cart_time": "🕒 Час: {time}",
    "cart_note": "💬 Коментар: {note}",
    "no_note": "без коментаря",
    "ready_when": "по готовності",
    "btn_add_more": "🤔 Ще щось додати?",
    "btn_confirm_pay": "✅ Підтвердити та оплатити",
    "btn_edit": "✏️ Змінити",
    "btn_cancel": "❌ Скасувати",

    # Upsell
    "upsell_chooser": "🤔 Що додати?",
    "btn_back_to_cart": "⬅ Назад",
    "btn_back_to_categories": "⬅ До категорій",
    "cat_food": "🥐 До кави",
    "cat_dessert": "🍰 Десерт",
    "cat_cold": "🥤 Холодне",
    "cat_drink": "☕ Кава",
    "cat_empty": "У цій категорії зараз нічого підходящого 🤷",

    # Editing
    "editing_title": "✏️ *Що змінюємо?*",
    "editing_hint": "_Або напиши що додати/прибрати ↓_",
    "btn_change_time": "🕐 Змінити час",
    "btn_comment": "💬 Коментар",
    "btn_done": "✅ Готово",
    "type_comment": "💬 Напиши коментар до замовлення:",
    "saved": "Записав ✓",
    "edit_didnt_understand": "Не зрозумів. Спробуй: «ще лате» / «прибери круасан» / «без цукру».",
    "nothing_to_remove": "Не знайшов що прибрати 🤔",
    "cart_empty_cancelled": "Корзина пуста — замовлення скасовано.",

    # Payment
    "creating_invoice": "⏳ Створюю рахунок...",
    "ready_to_pay": (
        "💳 *До сплати: {total:.0f} грн*\n\n"
        "🕒 Час: {time}\n\n"
        "Натисни кнопку нижче — відкриється сторінка оплати ⬇"
    ),
    "btn_pay": "💳 Оплатити (Apple Pay, Google Pay або карткою)",
    "invoice_failed": "❌ Не вдалося створити рахунок. Спробуй ще раз 🙏",
    "btn_retry": "🔄 Спробувати ще раз",
    "payment_expired": "⏰ Час на оплату вийшов. Можеш спробувати ще раз або скасувати:",
    "payment_failed_msg": "❌ Оплата не пройшла. Можеш спробувати ще раз або скасувати:",
    "payment_success_full": (
        "✅ *Дякую, {name}!*\n"
        "Оплату отримано, замовлення у роботі.\n\n"
        "{items}\n\n"
        "{arrival}{order_line}\n\n"
        "Гарного дня ☕"
    ),
    "payment_success_short": (
        "✅ *Оплату отримано!*\n\n"
        "{items}\n\n"
        "Зараз баристи приймуть твоє замовлення, зачекай хвилинку 🙏"
    ),
    "wait_at": "🕒 Чекаємо на тебе о {time}",
    "preparing_now": "🕒 Готуємо одразу",
    "order_number": "\n📋 Номер замовлення: *{num}*",
    "btn_order_again": "🔄 Замовити ще",
    "cant_calc": "❌ Не вдалося порахувати суму. Зателефонуй баристі.",

    # Lunch
    "lunch_text": (
        "🏢 *Для компаній: Обіди & Фуршети*\n\n"
        "💼 *Обіди в офіс:* Доставка смачних збалансованих обідів для вашої команди щодня.\n"
        "🎉 *Фуршети:* Апетитні гастробокси та організація свят під ключ для компаній.\n\n"
        "📞 *Дзвінок адміністратору:* {phone}"
    ),
    "btn_call": "📞 Подзвонити баристі",

    # Menu stub
    "menu_stub": (
        "📖 *Меню*\n\nЗараз я готую для тебе зручну апку з повним меню. "
        "Поки що користуйся кнопкою ✍️ *Зробити замовлення*."
    ),

    # Usual
    "usual_setup": (
        "☕ *Як завжди*\n\n"
        "Чудова кнопка для тих, хто знає чого хоче 😎\n\n"
        "Опиши свій постійний заказ — наступного разу зможеш замовити в один клік.\n\n"
        "Наприклад: _«Капучино на безлактозному + круасан з шинкою»_"
    ),
    "usual_added_to_cart": "Додав до замовлення твій постійний заказ ☕",
    "usual_saved": "Готово! Тепер натискай ☕ *Як завжди*.",
    "usual_missing_items": (
        "Хм, у меню більше немає: *{names}*. Може хочеш оновити свій постійний заказ?"
    ),
    "usual_describe_again": "Опиши, що б ти хотів замовляти регулярно ☕",

    # Settings
    "settings_title": (
        "⚙️ *Твої налаштування*\n\n"
        "👤 Ім'я: {name}\n"
        "📞 Телефон: {phone}\n"
        "🌐 Мова: {lang}\n\n"
        "Що змінити?"
    ),
    "settings_no_usual": "не налаштовано",
    "settings_lang_uk_label": "Українська 🇺🇦",
    "settings_lang_en_label": "English 🇬🇧",
    "btn_set_name": "✏️ Ім'я",
    "btn_set_lang": "🌐 Мова",
    "btn_set_phone": "📞 Телефон",
    "btn_set_usual": "☕ Постійний заказ",
    "btn_back": "⬅ Назад",
    "ask_new_name": "Як тебе записати?",
    "name_saved": "Готово, {name}! ✓",
    "ask_lang": "Обери мову / Choose language:",
    "lang_set_uk": "Готово! Тепер спілкуємось українською 🇺🇦",
    "lang_set_en": "Done! Switching to English 🇬🇧",
    "ask_new_phone": "Надішли новий номер:",
    "usual_view": "☕ *Твій постійний заказ:*\n\n{summary}",
    "usual_no_yet": "У тебе ще немає постійного заказу.",
    "btn_change_usual": "✏️ Змінити",
    "btn_delete_usual": "🗑 Видалити",
    "btn_setup_usual": "➕ Налаштувати",
    "usual_deleted": "Постійний заказ видалено ✓",
    "settings_closed": "Налаштування закрито ✓",

    # Misc
    "active_order": "У тебе вже є активне замовлення. Скасувати і почати нове?",
    "btn_yes_cancel": "Так, скасувати",
    "btn_no_continue": "Ні, продовжити",
    "fresh_start": "Готово, починаємо з чистого аркуша ✨",
    "keep_current": "Окей, продовжуємо поточне замовлення 👌",
    "awaiting_payment": "Рахунок вже створено — спочатку оплати або скасуй поточне замовлення 🙏",
    "paid_new_q": "Минуле замовлення вже готується ✅\nЦе нове окреме замовлення?",
    "btn_yes_new": "Так, нове",
    "btn_no": "Ні",
    "ok_new_order": "Окей, нове замовлення! ☕\nНапиши, що приготувати.",
    "ok": "Гаразд 👌",
    "order_cancelled": "❌ Замовлення скасовано.",
    "still_inactive": "Замовлення вже неактивне",
    "didnt_understand": "Не зрозумів, що приготувати. Напиши ще раз?",
    "not_in_menu": "Не знайшов у меню: *{names}* ☕",
    "something_wrong": "Вибач, щось не так. Спробуй ще раз.",
    "creating_invoice_wait": "Створюю рахунок, зачекай...",
    "ok_lets_continue": "Окей, що приготувати ще? ☕",
    "cancelled_short": "Скасовано.",
}

EN = {
    "greet_known": "Hi, {name}! What shall we make? ☕",
    "greet_new": "Hi! Send your number to register.",
    "send_phone_btn": "📞 Send number",
    "after_register": "Thanks, {name}! ☕",
    "tutorial": (
        "💡 A quick tip:\n\n"
        "You can write your full order in *one message* — I'll get it.\n\n"
        "For example:\n"
        "• _\"latte\"_\n"
        "• _\"two cappuccinos, now\"_\n"
        "• _\"latte on coconut + croissant, in 15 min\"_\n\n"
        "Try it ⬇"
    ),

    "btn_make_order": "⚡ ORDER HERE ⚡",
    "btn_usual": "☕ The usual",
    "btn_lunch": "🏢 For Companies & Catering",
    "btn_menu": "📖 Menu",
    "btn_settings": "⚙️ Settings",
    "btn_feedback": "💬 Leave Feedback",
    "ask_feedback": "💬 Write your feedback, suggestion or comment. I will immediately pass it to the owner! 👇",
    "feedback_saved": "Thank you for your feedback! Passed it to the manager. ☕",
    "input_placeholder": "e.g.: latte on lactose-free, in 10 min",

    "listening": (
        "I'm listening ☕\n\n"
        "💡 You can write everything at once: _\"two lattes on lactose-free, in 10 min\"_ — "
        "and order in one click.\n\n"
        "Or just name a drink — I'll ask about time."
    ),
    "what_time": "🕒 *When should we expect you?*",
    "what_time_hint": (
        "🕒 *When should we expect you?*\n\n"
        "💡 _Next time you can write everything at once — like \"latte in 15 min\" — "
        "to skip this step._"
    ),
    "time_now": "⚡ Now",
    "time_15": "In 15 min",
    "time_30": "In 30 min",
    "time_other": "Other time",
    "ask_other_time": "🕒 Type the time (e.g. _15:30_, _in 20 min_, _at 2pm_).",

    "cart_title": "☕️ *Your order*",
    "cart_empty": "  _cart is empty_",
    "cart_total": "💰 *Total: {total:.0f} UAH*",
    "cart_time": "🕒 Time: {time}",
    "cart_note": "💬 Note: {note}",
    "no_note": "no note",
    "ready_when": "as ready",
    "btn_add_more": "🤔 Anything else?",
    "btn_confirm_pay": "✅ Confirm & pay",
    "btn_edit": "✏️ Edit",
    "btn_cancel": "❌ Cancel",

    "upsell_chooser": "🤔 What to add?",
    "btn_back_to_cart": "⬅ Back",
    "btn_back_to_categories": "⬅ To categories",
    "cat_food": "🥐 With coffee",
    "cat_dessert": "🍰 Dessert",
    "cat_cold": "🥤 Cold",
    "cat_drink": "☕ Coffee",
    "cat_empty": "Nothing matching here right now 🤷",

    "editing_title": "✏️ *What to change?*",
    "editing_hint": "_Or type what to add/remove ↓_",
    "btn_change_time": "🕐 Change time",
    "btn_comment": "💬 Note",
    "btn_done": "✅ Done",
    "type_comment": "💬 Type a note for your order:",
    "saved": "Saved ✓",
    "edit_didnt_understand": "Didn't get it. Try: \"add latte\" / \"remove croissant\" / \"no sugar\".",
    "nothing_to_remove": "Nothing to remove 🤔",
    "cart_empty_cancelled": "Cart is empty — order cancelled.",

    "creating_invoice": "⏳ Creating invoice...",
    "ready_to_pay": (
        "💳 *To pay: {total:.0f} UAH*\n\n"
        "🕒 Time: {time}\n\n"
        "Tap below — payment page opens ⬇"
    ),
    "btn_pay": "💳 Pay (Apple Pay, Google Pay or Card)",
    "invoice_failed": "❌ Couldn't create invoice. Try again 🙏",
    "btn_retry": "🔄 Try again",
    "payment_expired": "⏰ Payment time expired. Try again or cancel:",
    "payment_failed_msg": "❌ Payment failed. Try again or cancel:",
    "payment_success_full": (
        "✅ *Thanks, {name}!*\n"
        "Payment received, order is being prepared.\n\n"
        "{items}\n\n"
        "{arrival}{order_line}\n\n"
        "Have a great day ☕"
    ),
    "payment_success_short": (
        "✅ *Payment received!*\n\n"
        "{items}\n\n"
        "The barista will pick it up in a moment 🙏"
    ),
    "wait_at": "🕒 We'll expect you at {time}",
    "preparing_now": "🕒 Preparing right away",
    "order_number": "\n📋 Order number: *{num}*",
    "btn_order_again": "🔄 Order more",
    "cant_calc": "❌ Couldn't calculate total. Please call the barista.",

    "lunch_text": (
        "🏢 *For Companies: Lunches & Catering*\n\n"
        "💼 *Office Lunches:* Daily delivery of balanced meals for your team.\n"
        "🎉 *Catering:* Tasty food boxes and full-service event organization for companies.\n\n"
        "📞 *Call our manager:* {phone}"
    ),
    "btn_call": "📞 Call Barista",

    "menu_stub": (
        "📖 *Menu*\n\nA full-menu app is in the works. For now, just tap "
        "✍️ *Place an order* and tell me what you want."
    ),

    "usual_setup": (
        "☕ *The usual*\n\n"
        "Great shortcut for those who know what they want 😎\n\n"
        "Describe your usual order — next time it's just one tap.\n\n"
        "Example: _\"Cappuccino on lactose-free + ham croissant\"_"
    ),
    "usual_added_to_cart": "Added your usual to the order ☕",
    "usual_saved": "Done! Now tap ☕ *The usual*.",
    "usual_missing_items": (
        "Hmm, these aren't on the menu anymore: *{names}*. Want to update your usual?"
    ),
    "usual_describe_again": "Describe what you'd like to order regularly ☕",

    "settings_title": (
        "⚙️ *Your settings*\n\n"
        "👤 Name: {name}\n"
        "📞 Phone: {phone}\n"
        "🌐 Language: {lang}\n\n"
        "What to change?"
    ),
    "settings_no_usual": "not set",
    "settings_lang_uk_label": "Українська 🇺🇦",
    "settings_lang_en_label": "English 🇬🇧",
    "btn_set_name": "✏️ Name",
    "btn_set_lang": "🌐 Language",
    "btn_set_phone": "📞 Phone",
    "btn_set_usual": "☕ Usual order",
    "btn_back": "⬅ Back",
    "ask_new_name": "What should I call you?",
    "name_saved": "Done, {name}! ✓",
    "ask_lang": "Обери мову / Choose language:",
    "lang_set_uk": "Готово! Тепер спілкуємось українською 🇺🇦",
    "lang_set_en": "Done! Switching to English 🇬🇧",
    "ask_new_phone": "Send a new number:",
    "usual_view": "☕ *Your usual order:*\n\n{summary}",
    "usual_no_yet": "You don't have a usual order yet.",
    "btn_change_usual": "✏️ Change",
    "btn_delete_usual": "🗑 Delete",
    "btn_setup_usual": "➕ Set up",
    "usual_deleted": "Usual order deleted ✓",
    "settings_closed": "Settings closed ✓",

    "active_order": "You have an active order. Cancel and start over?",
    "btn_yes_cancel": "Yes, cancel",
    "btn_no_continue": "No, continue",
    "fresh_start": "Done, starting fresh ✨",
    "keep_current": "Okay, keeping current order 👌",
    "awaiting_payment": "Invoice is created — pay or cancel current order first 🙏",
    "paid_new_q": "Previous order is being prepared ✅\nIs this a new separate order?",
    "btn_yes_new": "Yes, new",
    "btn_no": "No",
    "ok_new_order": "Okay, new order! ☕\nTell me what to make.",
    "ok": "Got it 👌",
    "order_cancelled": "❌ Order cancelled.",
    "still_inactive": "Order is no longer active",
    "didnt_understand": "I didn't catch what to make. Could you write it again?",
    "not_in_menu": "Not on the menu: *{names}* ☕",
    "something_wrong": "Sorry, something went wrong. Try again.",
    "creating_invoice_wait": "Creating invoice, please wait...",
    "ok_lets_continue": "Okay, what else? ☕",
    "cancelled_short": "Cancelled.",
}

DICTS = {"uk": UK, "en": EN}


def t(lcode: str, key: str, **kwargs) -> str:
    """Повертає текст за ключем; fallback на UK."""
    d = DICTS.get(lcode, UK)
    text = d.get(key) or UK.get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


# Зворотній мапінг: текст кнопки → ключ (для розпізнавання натиснутої кнопки)
def find_button_key(text: str) -> str | None:
    """Шукає по якій з відомих кнопок натиснули, повертає key (наприклад 'btn_make_order')."""
    # Fallbacks for older buttons so users don't get stuck if they have old keyboards cached
    if text in ["🍽 Бізнес-ланч", "🍽 Business lunch", "🍱 Бізнес-ланч / Фуршети", "🍱 Business Lunch / Catering"]:
        return "btn_lunch"
    if text in ["✍️ Зробити замовлення", "✍️ Place an order", "Зробити замовлення", "Place an order"]:
        return "btn_make_order"
        
    btn_keys = [
        "btn_make_order", "btn_usual", "btn_lunch", "btn_menu", "btn_settings", "btn_feedback",
    ]
    for lang_dict in DICTS.values():
        for k in btn_keys:
            if lang_dict.get(k) == text:
                return k
    return None
