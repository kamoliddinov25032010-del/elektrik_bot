import html
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto, InputMediaVideo

import db
from config import ADMIN_IDS

STATUS_LABEL = {
    "yangi": "🆕 Yangi",
    "qabul": "✅ Qabul qilindi",
    "jarayonda": "🔧 Jarayonda",
    "tayyor": "🟢 Tayyor",
    "topshirildi": "📦 Topshirildi",
    "bekor": "❌ Bekor qilindi",
}


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def fmt(n) -> str:
    return f"{(n or 0):,.0f}".replace(",", " ") + " so'm"


def parse_amount(text, allow_zero=False):
    t = re.sub(r"[^\d.,]", "", text or "").replace(",", ".")
    if t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    if v < 0 or (v == 0 and not allow_zero):
        return None
    return v


def norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    if not digits:
        return p or ""
    if len(digits) == 9:
        digits = "998" + digits
    return "+" + digits


async def edit_or_send(event, text, kb=None):
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                await event.message.answer(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


async def order_card(o: dict, client_view: bool = False) -> str:
    lines = [
        f"📦 <b>Zakaz #{o['id']}</b> — {STATUS_LABEL.get(o['status'], o['status'])}",
        f"👤 {esc(o['client_name'])}   📞 {esc(o['client_phone'])}",
        f"📝 {esc(o['description'])}",
        f"📅 {(o['created_at'] or '')[:16]}",
    ]
    if o["usta_id"]:
        lines.append(f"👷 Usta: {esc(await db.user_name(o['usta_id']))}")
    lines.append("")
    if o["estimate"]:
        ok = " ✅ mijoz tasdiqlagan" if o["estimate_ok"] else ""
        lines.append(f"📋 Taxminiy smeta: {fmt(o['estimate'])}{ok}")
    if client_view:
        mats = await db.fetchall(
            "SELECT name, qty, price FROM materials WHERE order_id=? ORDER BY id", (o["id"],)
        )
        if mats:
            lines.append("🧱 Materiallar:")
            for m in mats:
                lines.append(f"  • {esc(m['name'])}: {m['qty']:g} × {fmt(m['price'])} = {fmt(m['qty'] * m['price'])}")
    lines += [
        f"💵 Ish haqi: {fmt(o['wp'])}",
        f"🧱 Materiallar: {fmt(o['mat_sum'])}",
        f"🧾 Jami: <b>{fmt(o['total'])}</b>",
        f"✅ To'langan: {fmt(o['paid'])}",
        f"💳 Qarz: <b>{fmt(o['debt'])}</b>",
    ]
    return "\n".join(lines)


async def send_order_media(bot: Bot, chat_id: int, oid: int) -> int:
    """Zakazning rasm/video va lokatsiyasini yuboradi. Nechta narsa yuborilganini qaytaradi."""
    sent = 0
    media = await db.fetchall("SELECT file_id, file_type FROM order_media WHERE order_id=? ORDER BY id", (oid,))
    items = [
        InputMediaPhoto(media=r["file_id"]) if r["file_type"] == "photo" else InputMediaVideo(media=r["file_id"])
        for r in media
    ]
    for i in range(0, len(items), 10):
        chunk = items[i:i + 10]
        if len(chunk) == 1:
            it = chunk[0]
            if isinstance(it, InputMediaPhoto):
                await bot.send_photo(chat_id, it.media)
            else:
                await bot.send_video(chat_id, it.media)
        else:
            await bot.send_media_group(chat_id, chunk)
        sent += len(chunk)
    o = await db.fetchone("SELECT lat, lon FROM orders WHERE id=?", (oid,))
    if o and o["lat"] is not None and o["lon"] is not None:
        await bot.send_location(chat_id, o["lat"], o["lon"])
        sent += 1
    return sent


async def notify_order_staff(bot: Bot, o: dict, text: str, kb=None):
    """Zakazga biriktirilgan usta va adminlarga xabar."""
    ids = set(ADMIN_IDS)
    if o.get("usta_id"):
        ids.add(o["usta_id"])
    for sid in ids:
        try:
            await bot.send_message(sid, text, reply_markup=kb)
        except Exception:
            pass
