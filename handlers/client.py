import logging
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

import db
from keyboards import BTN_CANCEL, BTN_NEXT, BTN_SKIP, C_DEBT, C_MY, C_ORDER, ikb, kb_rows, menu_for
from utils import (STATUS_LABEL, edit_or_send, esc, fmt, norm_phone, notify_order_staff, order_card,
                   send_order_media)

router = Router()


class OrderFlow(StatesGroup):
    name = State()
    phone = State()
    desc = State()
    media = State()
    location = State()


# ---------- Zakaz berish ----------
@router.message(F.text == C_ORDER)
async def order_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrderFlow.name)
    await m.answer("Ismingizni yozing:", reply_markup=kb_rows([[m.from_user.full_name], [BTN_CANCEL]]))


@router.message(OrderFlow.name, F.text)
async def of_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:80])
    await state.set_state(OrderFlow.phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)], [KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )
    await m.answer("Telefon raqamingizni yuboring (tugmani bosing yoki yozing):", reply_markup=kb)


async def _after_phone(m: Message, state: FSMContext, phone: str):
    await state.update_data(phone=phone)
    await db.execute("UPDATE users SET phone=? WHERE tg_id=?", (phone, m.from_user.id))
    await state.set_state(OrderFlow.desc)
    await m.answer("Qanday ish kerak? Batafsil yozing:", reply_markup=kb_rows([[BTN_CANCEL]]))


@router.message(OrderFlow.phone, F.contact)
async def of_phone_contact(m: Message, state: FSMContext):
    await _after_phone(m, state, norm_phone(m.contact.phone_number))


@router.message(OrderFlow.phone, F.text)
async def of_phone_text(m: Message, state: FSMContext):
    if len(re.sub(r"\D", "", m.text)) < 7:
        await m.answer("Raqam noto'g'ri. Qayta yozing (masalan: 901234567):")
        return
    await _after_phone(m, state, norm_phone(m.text))


@router.message(OrderFlow.desc, F.text)
async def of_desc(m: Message, state: FSMContext):
    await state.update_data(desc=m.text.strip(), media=[])
    await state.set_state(OrderFlow.media)
    await m.answer(
        "Ish haqida rasm yoki video yuboring (bir nechta bo'lishi mumkin).\n"
        f"Yubormoqchi bo'lmasangiz «{BTN_NEXT}» ni bosing.",
        reply_markup=kb_rows([[BTN_NEXT], [BTN_CANCEL]]),
    )


async def _add_media(m: Message, state: FSMContext, ftype: str, file_id: str):
    data = await state.get_data()
    media = data.get("media", [])
    media.append([ftype, file_id])
    await state.update_data(media=media)
    await m.answer(f"📎 {len(media)} ta fayl qabul qilindi. Yana yuboring yoki «{BTN_NEXT}» ni bosing.")


@router.message(OrderFlow.media, F.photo)
async def of_photo(m: Message, state: FSMContext):
    await _add_media(m, state, "photo", m.photo[-1].file_id)


@router.message(OrderFlow.media, F.video)
async def of_video(m: Message, state: FSMContext):
    await _add_media(m, state, "video", m.video.file_id)


@router.message(OrderFlow.media, F.text == BTN_NEXT)
async def of_media_next(m: Message, state: FSMContext):
    await state.set_state(OrderFlow.location)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyani yuborish", request_location=True)],
            [KeyboardButton(text=BTN_SKIP)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )
    await m.answer("Ish manzilini lokatsiya sifatida yuboring:", reply_markup=kb)


@router.message(OrderFlow.media)
async def of_media_other(m: Message):
    await m.answer(f"Rasm yoki video yuboring, yoki «{BTN_NEXT}» ni bosing.")


async def _finish(m: Message, state: FSMContext, bot: Bot, lat, lon):
    data = await state.get_data()
    t = db.now()
    oid = await db.execute(
        "INSERT INTO orders (client_tg, client_name, client_phone, description, lat, lon, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'yangi', ?, ?)",
        (m.from_user.id, data["name"], data["phone"], data["desc"], lat, lon, t, t),
    )
    for ftype, fid in data.get("media", []):
        await db.execute("INSERT INTO order_media (order_id, file_id, file_type) VALUES (?, ?, ?)", (oid, fid, ftype))
    await state.clear()
    await m.answer(
        f"✅ Zakazingiz qabul qilindi! Raqami: <b>#{oid}</b>\nUsta tez orada siz bilan bog'lanadi.",
        reply_markup=menu_for(await db.get_role(m.from_user.id)),
    )
    await notify_new_order(bot, oid)


@router.message(OrderFlow.location, F.location)
async def of_location(m: Message, state: FSMContext, bot: Bot):
    await _finish(m, state, bot, m.location.latitude, m.location.longitude)


@router.message(OrderFlow.location, F.text == BTN_SKIP)
async def of_skip_location(m: Message, state: FSMContext, bot: Bot):
    await _finish(m, state, bot, None, None)


@router.message(OrderFlow.location)
async def of_location_other(m: Message):
    await m.answer(f"Lokatsiya yuboring yoki «{BTN_SKIP}» ni bosing.")


async def notify_new_order(bot: Bot, oid: int):
    o = await db.get_order(oid)
    u = await db.fetchone("SELECT username FROM users WHERE tg_id=?", (o["client_tg"],))
    profile = f'\n🔗 <a href="tg://user?id={o["client_tg"]}">Telegram profili</a>'
    if u and u["username"]:
        profile += f" (@{esc(u['username'])})"
    text = "🆕 <b>Yangi zakaz!</b>\n\n" + await order_card(o) + profile
    kb = ikb([[("✅ Qabul qilaman", f"acc:{oid}")], [("📂 Ochish", f"o:{oid}")]])
    for sid in await db.staff_ids():
        try:
            await bot.send_message(sid, text, reply_markup=kb)
            await send_order_media(bot, sid, oid)
        except Exception as e:
            logging.warning("Xabar yuborilmadi %s: %s", sid, e)


# ---------- Mening zakazlarim ----------
async def _my_list(event):
    uid = event.from_user.id
    rows = await db.fetchall(
        "SELECT id, status, description FROM orders WHERE client_tg=? ORDER BY id DESC LIMIT 20", (uid,)
    )
    if not rows:
        await edit_or_send(event, "Sizda hali zakaz yo'q.")
        return
    kb = ikb([[(f"#{r['id']} {STATUS_LABEL.get(r['status'])} — {r['description'][:20]}", f"my:{r['id']}")] for r in rows])
    await edit_or_send(event, "📋 <b>Mening zakazlarim:</b>", kb)


@router.message(F.text == C_MY)
async def my_orders(m: Message):
    await _my_list(m)


@router.callback_query(F.data == "myl")
async def my_orders_cb(call: CallbackQuery):
    await _my_list(call)
    await call.answer()


async def _own(call: CallbackQuery, oid: int):
    o = await db.get_order(oid)
    if not o or o["client_tg"] != call.from_user.id:
        await call.answer("Zakaz topilmadi", show_alert=True)
        return None
    return o


@router.callback_query(F.data.startswith("my:"))
async def my_order_view(call: CallbackQuery):
    o = await _own(call, int(call.data.split(":")[1]))
    if not o:
        return
    rows = []
    if o["estimate"] and not o["estimate_ok"]:
        rows.append([("✅ Smetani tasdiqlayman", f"cok:{o['id']}")])
    if o["status"] == "tayyor":
        rows.append([("✅ Ishni qabul qildim", f"crec:{o['id']}")])
    rows.append([("⬅️ Orqaga", "myl")])
    await edit_or_send(call, await order_card(o, client_view=True), ikb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("cok:"))
async def confirm_estimate(call: CallbackQuery, bot: Bot):
    o = await _own(call, int(call.data.split(":")[1]))
    if not o:
        return
    await db.execute("UPDATE orders SET estimate_ok=1 WHERE id=?", (o["id"],))
    await db.log(call.from_user.id, "smeta_tasdiq", f"zakaz #{o['id']}")
    await notify_order_staff(bot, o, f"✅ Mijoz <b>{esc(o['client_name'])}</b> #{o['id']} zakaz smetasini tasdiqladi.")
    o = await db.get_order(o["id"])
    await edit_or_send(call, await order_card(o, client_view=True), ikb([[("⬅️ Orqaga", "myl")]]))
    await call.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("crec:"))
async def client_received(call: CallbackQuery, bot: Bot):
    o = await _own(call, int(call.data.split(":")[1]))
    if not o:
        return
    await db.execute("UPDATE orders SET status='topshirildi', updated_at=? WHERE id=?", (db.now(), o["id"]))
    await db.log(call.from_user.id, "mijoz_qabul", f"zakaz #{o['id']}")
    await notify_order_staff(
        bot, o, f"📦 Mijoz <b>{esc(o['client_name'])}</b> #{o['id']} ishni qabul qildi (topshirildi). Qarz: {fmt(o['debt'])}"
    )
    o = await db.get_order(o["id"])
    await edit_or_send(call, await order_card(o, client_view=True), ikb([[("⬅️ Orqaga", "myl")]]))
    await call.answer("Rahmat!")


# ---------- Mening qarzim ----------
@router.message(F.text == C_DEBT)
async def my_debt(m: Message):
    rows = await db.fetchall(
        f"SELECT id, wp+mat_sum AS total, paid, wp+mat_sum-paid AS debt FROM ({db.ORDER_SELECT}) "
        "WHERE client_tg=? AND status!='bekor' AND (wp+mat_sum-paid)>0.5 ORDER BY id",
        (m.from_user.id,),
    )
    if not rows:
        await m.answer("🎉 Sizda qarz yo'q.")
        return
    lines = [f"• Zakaz #{r['id']}: jami {fmt(r['total'])}, to'langan {fmt(r['paid'])}, qarz <b>{fmt(r['debt'])}</b>" for r in rows]
    total = sum(r["debt"] for r in rows)
    await m.answer("💳 <b>Sizning qarzingiz</b>\n\n" + "\n".join(lines) + f"\n\nJami: <b>{fmt(total)}</b>")
