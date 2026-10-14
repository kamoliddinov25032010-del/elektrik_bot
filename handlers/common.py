from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import db
from keyboards import BTN_CANCEL, C_ABOUT, C_HOURS, C_PHONE, C_PRICES, C_WORKS, ikb, menu_for
from utils import esc

router = Router()


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    await db.upsert_user(u.id, u.full_name, u.username)
    role = await db.get_role(u.id)
    await m.answer(
        f"Assalomu alaykum, {esc(u.first_name)}! 👋\nElektr montaj xizmati botiga xush kelibsiz. Menyudan tanlang:",
        reply_markup=menu_for(role),
    )


@router.message(F.text == BTN_CANCEL)
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=menu_for(await db.get_role(m.from_user.id)))


@router.message(F.text == C_ABOUT)
async def about(m: Message):
    about_t = await db.get_setting("about")
    addr = await db.get_setting("address")
    await m.answer(f"ℹ️ <b>Biz haqimizda</b>\n\n{esc(about_t)}\n\n📍 Manzil: {esc(addr)}")


@router.message(F.text == C_PHONE)
async def phone(m: Message):
    await m.answer(f"📞 <b>Usta raqami:</b> {esc(await db.get_setting('phone'))}")


@router.message(F.text == C_HOURS)
async def hours(m: Message):
    await m.answer(f"🕒 <b>Ish kunlari:</b> {esc(await db.get_setting('hours'))}")


@router.message(F.text == C_PRICES)
async def prices(m: Message):
    rows = await db.fetchall("SELECT * FROM prices ORDER BY id")
    staff = (await db.get_role(m.from_user.id)) != "mijoz"
    text = "💰 <b>Narxlar</b>\n\n" + (
        "\n".join(f"• {esc(r['name'])} — <b>{esc(r['price'])}</b>" for r in rows)
        or "Hozircha narxlar kiritilmagan."
    )
    kb = None
    if staff:
        kb = ikb([[(f"🗑 {r['name']}"[:40], f"prd:{r['id']}")] for r in rows] + [[("➕ Narx qo'shish", "pra")]])
    await m.answer(text, reply_markup=kb)


@router.message(F.text == C_WORKS)
async def works(m: Message):
    staff = (await db.get_role(m.from_user.id)) != "mijoz"
    items = await db.fetchall("SELECT * FROM portfolio ORDER BY id DESC LIMIT 10")
    if staff:
        await m.answer("🖼 <b>Bizning ishlarimiz</b> (boshqaruv)", reply_markup=ikb([[("➕ Ish qo'shish", "wka")]]))
    if not items:
        await m.answer("Hozircha ishlar qo'shilmagan.")
        return
    for it in reversed(items):
        kb = ikb([[("🗑 O'chirish", f"wkd:{it['id']}")]]) if staff else None
        cap = esc(it["caption"]) if it["caption"] else None
        if it["file_type"] == "photo":
            await m.answer_photo(it["file_id"], caption=cap, reply_markup=kb)
        else:
            await m.answer_video(it["file_id"], caption=cap, reply_markup=kb)
