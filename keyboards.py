from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

# Mijoz menyusi
C_ORDER = "📝 Zakaz berish"
C_MY = "📋 Mening zakazlarim"
C_DEBT = "💳 Mening qarzim"
C_PRICES = "💰 Narxlar"
C_WORKS = "🖼 Bizning ishlarimiz"
C_ABOUT = "ℹ️ Biz haqimizda"
C_PHONE = "📞 Usta raqami"
C_HOURS = "🕒 Ish vaqti"

# Usta / admin menyusi
S_ORDERS = "📦 Zakazlar"
S_NEW = "➕ Yangi zakaz"
S_DEBTORS = "👥 Qarzdorlar"
S_EXP = "💸 Xarajatlar"
S_REPORT = "📊 Hisobot"
S_ADMIN = "⚙️ Admin kabineti"

BTN_CANCEL = "❌ Bekor qilish"
BTN_NEXT = "➡️ Davom etish"
BTN_SKIP = "⏭ O'tkazib yuborish"

# Shu tugmalar bosilsa, tugallanmagan jarayon (FSM) bekor qilinadi
MENU_BUTTONS = {
    C_ORDER, C_MY, C_DEBT, C_PRICES, C_WORKS, C_ABOUT, C_PHONE, C_HOURS,
    S_ORDERS, S_NEW, S_DEBTORS, S_EXP, S_REPORT, S_ADMIN, BTN_CANCEL,
}


def kb_rows(rows) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in r] for r in rows], resize_keyboard=True
    )


def ikb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r] for r in rows]
    )


def menu_for(role: str) -> ReplyKeyboardMarkup:
    if role in ("admin", "usta"):
        rows = [
            [S_ORDERS, S_NEW],
            [S_DEBTORS, S_EXP],
            [S_REPORT, C_PRICES],
            [C_WORKS],
        ]
        if role == "admin":
            rows.append([S_ADMIN])
        return kb_rows(rows)
    return kb_rows([
        [C_ORDER],
        [C_MY, C_DEBT],
        [C_PRICES, C_WORKS],
        [C_ABOUT, C_PHONE],
        [C_HOURS],
    ])
