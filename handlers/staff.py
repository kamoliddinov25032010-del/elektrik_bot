import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import db
import reports
from filters import RoleFilter
from keyboards import S_DEBTORS, S_EXP, S_REPORT, ikb
from utils import STATUS_LABEL, edit_or_send, esc, fmt, parse_amount

router = Router()
router.message.filter(RoleFilter())
router.callback_query.filter(RoleFilter())

CATS = {"transport": "🚚 Transport", "instrument": "🛠 Instrument", "boshqa": "📦 Boshqa"}


class ExpAdd(StatesGroup):
    category = State()
    amount = State()
    note = State()


class PriceAdd(StatesGroup):
    name = State()
    price = State()


class WorkAdd(StatesGroup):
    media = State()


# ================= Qarzdorlar =================
DEBT_SQL = (
    "SELECT MAX(client_name) AS client_name, client_phone, MAX(client_tg) AS tg, "
    "SUM(wp+mat_sum-paid) AS debt, COUNT(*) AS cnt "
    f"FROM ({db.ORDER_SELECT}) o WHERE status!='bekor'"
)


async def show_debtors(event):
    uid = event.from_user.id
    role = await db.get_role(uid)
    extra, params = ("", []) if role == "admin" else (" AND usta_id=?", [uid])
    rows = await db.fetchall(
        DEBT_SQL + extra + " GROUP BY client_phone HAVING debt>0.5 ORDER BY debt DESC", params
    )
    if not rows:
        await edit_or_send(event, "🎉 Qarzdorlar yo'q.")
        return
    total = sum(r["debt"] for r in rows)
    kb = ikb([[(f"{r['client_name'][:22]} — {fmt(r['debt'])}", f"dbt:{r['client_phone']}")] for r in rows[:40]])
    await edit_or_send(event, f"👥 <b>Qarzdorlar</b> ({len(rows)} ta)\nJami qarz: <b>{fmt(total)}</b>", kb)


@router.message(F.text == S_DEBTORS)
async def debtors(m: Message):
    await show_debtors(m)


@router.callback_query(F.data == "dbl")
async def debtors_cb(call: CallbackQuery):
    await show_debtors(call)
    await call.answer()


@router.callback_query(F.data.startswith("dbt:"))
async def debtor_detail(call: CallbackQuery):
    phone = call.data[4:]
    uid = call.from_user.id
    role = await db.get_role(uid)
    extra, params = ("", []) if role == "admin" else (" AND usta_id=?", [uid])
    rows = await db.fetchall(
        f"SELECT id, client_name, status, wp+mat_sum AS total, paid, wp+mat_sum-paid AS debt "
        f"FROM ({db.ORDER_SELECT}) o WHERE client_phone=? AND status!='bekor'{extra} ORDER BY id",
        [phone] + params,
    )
    if not rows:
        await call.answer("Topilmadi", show_alert=True)
        return
    total = sum(r["debt"] for r in rows)
    lines = [
        f"• #{r['id']} ({STATUS_LABEL.get(r['status'])}): jami {fmt(r['total'])}, to'langan {fmt(r['paid'])}, qarz {fmt(r['debt'])}"
        for r in rows
    ]
    text = f"👤 <b>{esc(rows[0]['client_name'])}</b>  📞 {esc(phone)}\n\n" + "\n".join(lines) + f"\n\nJami qarz: <b>{fmt(total)}</b>"
    kb = ikb(
        [[(f"📂 Zakaz #{r['id']}", f"o:{r['id']}")] for r in rows]
        + [[("🔔 Eslatma yuborish", f"dr:{phone}")], [("⬅️ Qarzdorlar", "dbl")]]
    )
    await edit_or_send(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("dr:"))
async def debtor_remind(call: CallbackQuery, bot: Bot):
    phone = call.data[3:]
    rows = await db.fetchall(
        f"SELECT id, client_tg, wp+mat_sum-paid AS debt FROM ({db.ORDER_SELECT}) o "
        "WHERE client_phone=? AND status!='bekor' AND client_tg IS NOT NULL",
        (phone,),
    )
    by_tg = {}
    for r in rows:
        by_tg.setdefault(r["client_tg"], []).append(r)
    sent = 0
    for tg, items in by_tg.items():
        debt = sum(i["debt"] for i in items)
        if debt <= 0.5:
            continue
        try:
            await bot.send_message(tg, f"🔔 Eslatma: sizning umumiy qarzingiz <b>{fmt(debt)}</b>.")
            sent += 1
        except Exception as e:
            logging.warning("Eslatma yuborilmadi: %s", e)
    await db.log(call.from_user.id, "qarz_eslatma", phone)
    await call.answer("Eslatma yuborildi" if sent else "Mijoz botdan foydalanmaydi, telefon orqali eslating.", show_alert=True)


# ================= Xarajatlar =================
@router.message(F.text == S_EXP)
async def exp_menu(m: Message):
    uid = m.from_user.id
    role = await db.get_role(uid)
    extra, params = ("", []) if role == "admin" else (" AND by_user=?", [uid])
    rows = await db.fetchall(
        "SELECT category, SUM(amount) AS s FROM expenses WHERE strftime('%Y-%m', created_at)=?"
        + extra + " GROUP BY category",
        [reports.cur_month()] + params,
    )
    text = f"💸 <b>Xarajatlar ({reports.cur_month()})</b>\n\n"
    text += "\n".join(f"{CATS.get(r['category'], r['category'])}: {fmt(r['s'])}" for r in rows) or "Bu oy xarajat yo'q."
    text += "\n\n<i>Materiallar xarajati zakaz ichidan avtomatik hisoblanadi.</i>"
    await m.answer(text, reply_markup=ikb([[("➕ Xarajat qo'shish", "exn:0")], [("📜 Oxirgilari", "exl")]]))


@router.callback_query(F.data.startswith("exn:"))
async def exp_start(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    await state.clear()
    await state.set_state(ExpAdd.category)
    await state.update_data(oid=oid or None)
    await call.message.answer(
        "Xarajat turini tanlang:",
        reply_markup=ikb([[(v, f"ec:{k}")] for k, v in CATS.items()]),
    )
    await call.answer()


@router.callback_query(ExpAdd.category, F.data.startswith("ec:"))
async def exp_cat(call: CallbackQuery, state: FSMContext):
    await state.update_data(category=call.data.split(":")[1])
    await state.set_state(ExpAdd.amount)
    await call.message.edit_text("Summani yozing (so'mda):")
    await call.answer()


@router.message(ExpAdd.amount, F.text)
async def exp_amount(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("Summani raqam bilan yozing:")
        return
    await state.update_data(amount=v)
    await state.set_state(ExpAdd.note)
    await m.answer("Izoh yozing (yoki «-» yuboring):")


@router.message(ExpAdd.note, F.text)
async def exp_note(m: Message, state: FSMContext):
    d = await state.get_data()
    note = "" if m.text.strip() == "-" else m.text.strip()
    await db.execute(
        "INSERT INTO expenses (order_id, by_user, category, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (d["oid"], m.from_user.id, d["category"], d["amount"], note, db.now()),
    )
    await db.log(m.from_user.id, "xarajat", f"{d['category']} {d['amount']:.0f} {note}")
    await state.clear()
    await m.answer(f"✅ Xarajat saqlandi: {CATS[d['category']]} — {fmt(d['amount'])}")


async def _exp_list(call: CallbackQuery):
    uid = call.from_user.id
    role = await db.get_role(uid)
    extra, params = ("", []) if role == "admin" else (" WHERE by_user=?", [uid])
    rows = await db.fetchall(f"SELECT * FROM expenses{extra} ORDER BY id DESC LIMIT 10", params)
    if not rows:
        await edit_or_send(call, "Xarajatlar yo'q.")
        return
    text = "📜 <b>Oxirgi xarajatlar</b>\n\n" + "\n".join(
        f"{i}. {r['created_at'][:16]} — {CATS.get(r['category'], r['category'])}: {fmt(r['amount'])} {esc(r['note'])}"
        for i, r in enumerate(rows, 1)
    )
    kb = ikb([[(f"🗑 {i}. {fmt(r['amount'])}", f"exd:{r['id']}")] for i, r in enumerate(rows, 1)])
    await edit_or_send(call, text, kb)


@router.callback_query(F.data == "exl")
async def exp_list(call: CallbackQuery):
    await _exp_list(call)
    await call.answer()


@router.callback_query(F.data.startswith("exd:"))
async def exp_delete(call: CallbackQuery):
    eid = int(call.data.split(":")[1])
    await db.execute("DELETE FROM expenses WHERE id=?", (eid,))
    await db.log(call.from_user.id, "xarajat_ochirildi", f"id {eid}")
    await _exp_list(call)
    await call.answer("O'chirildi")


# ================= Hisobot =================
REPORT_KB = ikb([
    [("📅 Shu oy", "rp:this"), ("📅 O'tgan oy", "rp:prev")],
    [("📥 Excel: shu oy", "rpx:this"), ("📥 Excel: o'tgan oy", "rpx:prev")],
    [("📥 Excel: hammasi", "rpx:all")],
])


async def _report_text(uid, month):
    role = await db.get_role(uid)
    usta = None if role == "admin" else uid
    return await reports.month_report_text(month, usta, admin=(role == "admin"))


@router.message(F.text == S_REPORT)
async def report_menu(m: Message):
    await m.answer(await _report_text(m.from_user.id, reports.cur_month()), reply_markup=REPORT_KB)


@router.callback_query(F.data.startswith("rp:"))
async def report_cb(call: CallbackQuery):
    month = reports.cur_month() if call.data.split(":")[1] == "this" else reports.prev_month()
    await edit_or_send(call, await _report_text(call.from_user.id, month), REPORT_KB)
    await call.answer()


@router.callback_query(F.data.startswith("rpx:"))
async def report_excel(call: CallbackQuery):
    which = call.data.split(":")[1]
    month = {"this": reports.cur_month(), "prev": reports.prev_month(), "all": None}[which]
    uid = call.from_user.id
    usta = None if (await db.get_role(uid)) == "admin" else uid
    await call.answer("Tayyorlanmoqda...")
    data = await reports.build_excel(month, usta)
    name = f"hisobot_{month or 'hammasi'}.xlsx"
    await call.message.answer_document(BufferedInputFile(data, filename=name), caption="📥 Excel hisobot")


# ================= Narxlar (usta/admin) =================
@router.callback_query(F.data == "pra")
async def price_add(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PriceAdd.name)
    await call.message.answer("Xizmat/mahsulot nomini yozing (masalan: Rozetka o'rnatish):")
    await call.answer()


@router.message(PriceAdd.name, F.text)
async def price_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:100])
    await state.set_state(PriceAdd.price)
    await m.answer("Narxini yozing (masalan: 15 000 so'm yoki 50 000 so'm / nuqta):")


@router.message(PriceAdd.price, F.text)
async def price_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await db.execute("INSERT INTO prices (name, price) VALUES (?, ?)", (d["name"], m.text.strip()[:100]))
    await db.log(m.from_user.id, "narx_qoshildi", d["name"])
    await state.clear()
    await m.answer("✅ Narx qo'shildi. «💰 Narxlar» tugmasidan ko'rishingiz mumkin.")


@router.callback_query(F.data.startswith("prd:"))
async def price_delete(call: CallbackQuery):
    await db.execute("DELETE FROM prices WHERE id=?", (int(call.data.split(":")[1]),))
    await db.log(call.from_user.id, "narx_ochirildi", call.data)
    await call.answer("O'chirildi")
    await call.message.edit_text("🗑 O'chirildi. Yangilangan ro'yxat uchun «💰 Narxlar» ni bosing.")


# ================= Ishlar (portfolio) =================
@router.callback_query(F.data == "wka")
async def work_add(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(WorkAdd.media)
    await call.message.answer("Rasm yoki video yuboring (izoh yozsangiz, u ham saqlanadi):")
    await call.answer()


@router.message(WorkAdd.media, F.photo)
async def work_photo(m: Message, state: FSMContext):
    await db.execute(
        "INSERT INTO portfolio (file_id, file_type, caption, created_at) VALUES (?, 'photo', ?, ?)",
        (m.photo[-1].file_id, m.caption, db.now()),
    )
    await state.clear()
    await m.answer("✅ Ish portfolioga qo'shildi.")


@router.message(WorkAdd.media, F.video)
async def work_video(m: Message, state: FSMContext):
    await db.execute(
        "INSERT INTO portfolio (file_id, file_type, caption, created_at) VALUES (?, 'video', ?, ?)",
        (m.video.file_id, m.caption, db.now()),
    )
    await state.clear()
    await m.answer("✅ Ish portfolioga qo'shildi.")


@router.callback_query(F.data.startswith("wkd:"))
async def work_delete(call: CallbackQuery):
    await db.execute("DELETE FROM portfolio WHERE id=?", (int(call.data.split(":")[1]),))
    await call.message.delete()
    await call.answer("O'chirildi")
