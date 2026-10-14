import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import db
import reports
from filters import RoleFilter
from keyboards import S_ADMIN, ikb
from utils import esc, fmt

router = Router()
router.message.filter(RoleFilter(admin_only=True))
router.callback_query.filter(RoleFilter(admin_only=True))

EDITABLE = {
    "about": "Biz haqimizda matni",
    "phone": "Usta raqami",
    "hours": "Ish vaqti",
    "address": "Manzil",
}


class UstaAdd(StatesGroup):
    tg_id = State()
    name = State()


class EditSetting(StatesGroup):
    value = State()


class Broadcast(StatesGroup):
    text = State()
    confirm = State()


ADMIN_KB = ikb([
    [("👷 Ustalar", "ad:ustalar"), ("👥 Mijozlar", "ad:mijozlar")],
    [("📈 Umumiy statistika", "ad:stat"), ("📣 Xabar yuborish", "ad:bc")],
    [("✏️ Matnlar (haqimizda, raqam...)", "ad:matn")],
    [("📜 Tizim loglari", "ad:log")],
])


@router.message(F.text == S_ADMIN)
@router.message(Command("admin"))
async def admin_panel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("⚙️ <b>Admin kabineti</b>", reply_markup=ADMIN_KB)


# ---------- Ustalar ----------
async def _ustalar(event):
    rows = await db.fetchall("SELECT tg_id, name FROM users WHERE role='usta' ORDER BY id")
    text = "👷 <b>Ustalar</b>\n\n" + (
        "\n".join(f"• {esc(r['name'])} (ID: {r['tg_id']})" for r in rows) or "Hozircha usta qo'shilmagan."
    )
    kb = ikb([[(f"🗑 {r['name']}"[:40], f"ud:{r['tg_id']}")] for r in rows] + [[("➕ Usta qo'shish", "ua")]])
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ad:ustalar")
async def ustalar(call: CallbackQuery):
    await _ustalar(call)
    await call.answer()


@router.callback_query(F.data == "ua")
async def usta_add(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(UstaAdd.tg_id)
    await call.message.answer(
        "Usta Telegram ID raqamini yozing.\n(Usta @userinfobot ga /start yozib, ID sini bilib oladi.)"
    )
    await call.answer()


@router.message(UstaAdd.tg_id, F.text)
async def usta_id(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("Faqat raqam yozing:")
        return
    await state.update_data(tg=int(m.text.strip()))
    await state.set_state(UstaAdd.name)
    await m.answer("Usta ismini yozing:")


@router.message(UstaAdd.name, F.text)
async def usta_name(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    name = m.text.strip()[:60]
    await db.execute(
        "INSERT INTO users (tg_id, name, role, created_at) VALUES (?, ?, 'usta', ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET role='usta', name=excluded.name",
        (d["tg"], name, db.now()),
    )
    await db.log(m.from_user.id, "usta_qoshildi", f"{name} ({d['tg']})")
    await state.clear()
    await m.answer(f"✅ Usta qo'shildi: {esc(name)}")
    try:
        await bot.send_message(d["tg"], "👷 Siz usta sifatida qo'shildingiz. Menyuni ochish uchun /start bosing.")
    except Exception:
        await m.answer("⚠️ Ustaga xabar yuborilmadi (u botga hali /start bosmagan). Unga /start bosishni ayting.")


@router.callback_query(F.data.startswith("ud:"))
async def usta_delete(call: CallbackQuery):
    tg = int(call.data.split(":")[1])
    await db.execute("UPDATE users SET role='mijoz' WHERE tg_id=?", (tg,))
    await db.log(call.from_user.id, "usta_ochirildi", str(tg))
    await call.answer("Usta o'chirildi")
    await call.message.edit_text("🗑 Usta o'chirildi.")


# ---------- Mijozlar ----------
@router.callback_query(F.data == "ad:mijozlar")
async def clients(call: CallbackQuery):
    total = await db.scalar("SELECT COUNT(*) FROM users WHERE role='mijoz'")
    rows = await db.fetchall(
        f"SELECT u.name, u.phone, u.username, "
        f"(SELECT COUNT(*) FROM orders o WHERE o.client_tg=u.tg_id) AS cnt, "
        f"(SELECT COALESCE(SUM(wp+mat_sum-paid),0) FROM ({db.ORDER_SELECT}) x "
        f"WHERE x.client_tg=u.tg_id AND x.status!='bekor') AS debt "
        f"FROM users u WHERE u.role='mijoz' ORDER BY u.id DESC LIMIT 30"
    )
    lines = [
        f"• {esc(r['name'])} {('@' + esc(r['username'])) if r['username'] else ''} {esc(r['phone'] or '')} — "
        f"zakaz: {r['cnt']}, qarz: {fmt(max(r['debt'], 0))}"
        for r in rows
    ]
    await call.message.answer(f"👥 <b>Mijozlar</b> (jami {total}, oxirgi 30 ta)\n\n" + ("\n".join(lines) or "Hali yo'q."))
    await call.answer()


# ---------- Statistika ----------
@router.callback_query(F.data == "ad:stat")
async def stat(call: CallbackQuery):
    text = await reports.month_report_text(reports.cur_month(), None, admin=True)
    users = await db.scalar("SELECT COUNT(*) FROM users")
    await call.message.answer(text + f"\n\n👥 Foydalanuvchilar: {users}")
    await call.answer()


# ---------- Matnlar ----------
@router.callback_query(F.data == "ad:matn")
async def texts(call: CallbackQuery):
    await call.message.answer(
        "Qaysi matnni o'zgartirasiz?",
        reply_markup=ikb([[(f"✏️ {t}", f"edit:{k}")] for k, t in EDITABLE.items()]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("edit:"))
async def edit_start(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[1]
    if key not in EDITABLE:
        await call.answer()
        return
    await state.clear()
    await state.set_state(EditSetting.value)
    await state.update_data(key=key)
    await call.message.answer(
        f"<b>{EDITABLE[key]}</b>\nHozirgi: {esc(await db.get_setting(key))}\n\nYangi qiymatni yozing:"
    )
    await call.answer()


@router.message(EditSetting.value, F.text)
async def edit_save(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    await db.set_setting(key, m.text.strip())
    await db.log(m.from_user.id, "matn_ozgardi", key)
    await state.clear()
    await m.answer("✅ Saqlandi.")


# ---------- Xabar yuborish ----------
@router.callback_query(F.data == "ad:bc")
async def bc_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Broadcast.text)
    await call.message.answer("📣 Barcha mijozlarga yuboriladigan xabar matnini yozing:")
    await call.answer()


@router.message(Broadcast.text, F.text)
async def bc_text(m: Message, state: FSMContext):
    await state.update_data(text=m.text)
    await state.set_state(Broadcast.confirm)
    n = await db.scalar("SELECT COUNT(*) FROM users WHERE role='mijoz'")
    await m.answer(
        f"Xabar {n} ta mijozga yuboriladi:\n\n{esc(m.text)}",
        reply_markup=ikb([[("✅ Yuborish", "bc:ok"), ("❌ Bekor", "bc:no")]]),
    )


@router.callback_query(Broadcast.confirm, F.data.startswith("bc:"))
async def bc_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    if call.data.endswith("no"):
        await state.clear()
        await call.message.edit_text("Bekor qilindi.")
        await call.answer()
        return
    text = (await state.get_data())["text"]
    await state.clear()
    await call.message.edit_text("Yuborilmoqda...")
    rows = await db.fetchall("SELECT tg_id FROM users WHERE role='mijoz'")
    ok = 0
    for r in rows:
        try:
            await bot.send_message(r["tg_id"], esc(text))
            ok += 1
        except Exception as e:
            logging.info("Xabar yetmadi %s: %s", r["tg_id"], e)
        await asyncio.sleep(0.05)
    await db.log(call.from_user.id, "xabar_yuborildi", f"{ok}/{len(rows)}")
    await call.message.answer(f"✅ Yuborildi: {ok} / {len(rows)}")
    await call.answer()


# ---------- Loglar ----------
@router.callback_query(F.data == "ad:log")
async def logs(call: CallbackQuery):
    rows = await db.fetchall(
        "SELECT l.created_at, l.action, l.details, "
        "(SELECT name FROM users u WHERE u.tg_id=l.user_id) AS name, l.user_id "
        "FROM logs l ORDER BY l.id DESC LIMIT 30"
    )
    text = "📜 <b>Oxirgi 30 ta harakat</b>\n\n" + (
        "\n".join(
            f"{r['created_at'][5:16]} · {esc(r['name'] or r['user_id'])} · {esc(r['action'])} {esc(r['details'])}"
            for r in rows
        ) or "Hali yo'q."
    )
    await call.message.answer(text)
    await call.answer()
