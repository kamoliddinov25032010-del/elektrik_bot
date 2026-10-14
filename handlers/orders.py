import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import db
from filters import RoleFilter
from keyboards import S_NEW, S_ORDERS, ikb
from utils import (STATUS_LABEL, edit_or_send, esc, fmt, norm_phone, order_card, parse_amount,
                   send_order_media)

router = Router()
router.message.filter(RoleFilter())
router.callback_query.filter(RoleFilter())


class NewOrder(StatesGroup):
    name = State()
    phone = State()
    desc = State()


class WorkPrice(StatesGroup):
    amount = State()


class Estimate(StatesGroup):
    amount = State()


class MatAdd(StatesGroup):
    name = State()
    qty = State()
    price = State()


class PayAdd(StatesGroup):
    amount = State()
    kind = State()
    method = State()


FILTER_KB = ikb([
    [("🆕 Yangi", "ol:yangi"), ("🔧 Jarayonda", "ol:aktiv")],
    [("🟢 Tayyor", "ol:tayyor"), ("📦 Topshirilgan", "ol:topshirildi")],
    [("📚 Hammasi", "ol:all")],
])


def staff_kb(o):
    i = o["id"]
    return ikb([
        [("✅ Qabul", f"st:{i}:qabul"), ("🔧 Jarayonda", f"st:{i}:jarayonda")],
        [("🟢 Tayyor", f"st:{i}:tayyor"), ("📦 Topshirildi", f"st:{i}:topshirildi")],
        [("❌ Bekor qilish", f"st:{i}:bekor")],
        [("💵 Ish haqi", f"wp:{i}"), ("📋 Taxminiy smeta", f"est:{i}")],
        [("🧱 Material qo'shish", f"mat:{i}"), ("🧱 Materiallar", f"ml:{i}")],
        [("💳 To'lov qabul qilish", f"pay:{i}"), ("💳 To'lovlar", f"pl:{i}")],
        [("📎 Rasm/lokatsiya", f"media:{i}"), ("🧾 Smetani mijozga", f"sm:{i}")],
        [("💸 Xarajat", f"exn:{i}"), ("🔔 Qarz eslatma", f"rem:{i}")],
        [("⬅️ Zakazlar ro'yxati", "olm")],
    ])


async def load(call: CallbackQuery, oid: int):
    o = await db.get_order(oid)
    if not o:
        await call.answer("Zakaz topilmadi", show_alert=True)
        return None
    role = await db.get_role(call.from_user.id)
    if role != "admin" and o["usta_id"] not in (None, call.from_user.id):
        await call.answer("Bu zakaz boshqa ustaga biriktirilgan", show_alert=True)
        return None
    return o


async def show_order(event, oid: int):
    o = await db.get_order(oid)
    await edit_or_send(event, await order_card(o), staff_kb(o))


async def tell_client(bot: Bot, o: dict, text: str, kb=None):
    if o["client_tg"]:
        try:
            await bot.send_message(o["client_tg"], text, reply_markup=kb)
        except Exception as e:
            logging.warning("Mijozga yuborilmadi: %s", e)


# ---------- Zakazlar ro'yxati ----------
@router.message(F.text == S_ORDERS)
async def orders_menu(m: Message):
    await m.answer("📦 Qaysi zakazlarni ko'rasiz?", reply_markup=FILTER_KB)


@router.callback_query(F.data == "olm")
async def orders_menu_cb(call: CallbackQuery):
    await edit_or_send(call, "📦 Qaysi zakazlarni ko'rasiz?", FILTER_KB)
    await call.answer()


@router.callback_query(F.data.startswith("ol:"))
async def order_list(call: CallbackQuery):
    f = call.data.split(":")[1]
    uid = call.from_user.id
    role = await db.get_role(uid)
    cond, params = [], []
    if f == "yangi":
        cond.append("status='yangi'")
    elif f == "aktiv":
        cond.append("status IN ('qabul','jarayonda')")
    elif f in ("tayyor", "topshirildi"):
        cond.append("status=?")
        params.append(f)
    if role != "admin":
        cond.append("(usta_id=? OR usta_id IS NULL)")
        params.append(uid)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = await db.fetchall(
        f"SELECT id, client_name, status FROM orders {where} ORDER BY id DESC LIMIT 30", params
    )
    if not rows:
        await edit_or_send(call, "Zakaz topilmadi.", ikb([[("⬅️ Orqaga", "olm")]]))
        await call.answer()
        return
    kb = ikb(
        [[(f"#{r['id']} {r['client_name'][:18]} · {STATUS_LABEL.get(r['status'])}", f"o:{r['id']}")] for r in rows]
        + [[("⬅️ Orqaga", "olm")]]
    )
    await edit_or_send(call, f"📦 Zakazlar ({len(rows)} ta):", kb)
    await call.answer()


@router.callback_query(F.data.startswith("o:"))
async def open_order(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    await show_order(call, oid)
    await call.answer()


@router.callback_query(F.data.startswith("acc:"))
async def accept_order(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        await call.answer("Zakaz topilmadi", show_alert=True)
        return
    uid = call.from_user.id
    if o["usta_id"] and o["usta_id"] != uid:
        await call.answer("Bu zakazni boshqa usta qabul qilgan", show_alert=True)
        return
    await db.execute("UPDATE orders SET usta_id=?, status='qabul', updated_at=? WHERE id=?", (uid, db.now(), oid))
    await db.log(uid, "zakaz_qabul", f"#{oid}")
    await tell_client(bot, o, f"✅ Zakaz #{oid} usta tomonidan qabul qilindi. Tez orada bog'lanamiz.")
    await show_order(call, oid)
    await call.answer("Qabul qilindi")


@router.callback_query(F.data.startswith("st:"))
async def set_status(call: CallbackQuery, bot: Bot):
    _, oid, status = call.data.split(":")
    oid = int(oid)
    o = await load(call, oid)
    if not o:
        return
    uid = call.from_user.id
    await db.execute(
        "UPDATE orders SET status=?, updated_at=?, usta_id=COALESCE(usta_id, ?) WHERE id=?",
        (status, db.now(), uid, oid),
    )
    await db.log(uid, "holat", f"#{oid} -> {status}")
    kb = ikb([[("✅ Ishni qabul qildim", f"crec:{oid}")]]) if status == "tayyor" else None
    await tell_client(bot, o, f"📦 Zakaz #{oid} holati: <b>{STATUS_LABEL[status]}</b>", kb)
    await show_order(call, oid)
    await call.answer("Holat yangilandi")


# ---------- Staff tomonidan yangi zakaz ----------
@router.message(F.text == S_NEW)
async def new_order(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(NewOrder.name)
    await m.answer("👤 Mijoz ismini yozing:")


@router.message(NewOrder.name, F.text)
async def no_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:80])
    await state.set_state(NewOrder.phone)
    await m.answer("📞 Mijoz telefon raqami:")


@router.message(NewOrder.phone, F.text)
async def no_phone(m: Message, state: FSMContext):
    await state.update_data(phone=norm_phone(m.text))
    await state.set_state(NewOrder.desc)
    await m.answer("📝 Qanday ish? Qisqacha yozing:")


@router.message(NewOrder.desc, F.text)
async def no_desc(m: Message, state: FSMContext):
    d = await state.get_data()
    t = db.now()
    oid = await db.execute(
        "INSERT INTO orders (client_tg, client_name, client_phone, usta_id, description, status, created_at, updated_at) "
        "VALUES (NULL, ?, ?, ?, ?, 'qabul', ?, ?)",
        (d["name"], d["phone"], m.from_user.id, m.text.strip(), t, t),
    )
    await db.log(m.from_user.id, "zakaz_qoshildi", f"#{oid}")
    await state.clear()
    await show_order(m, oid)


# ---------- Ish haqi ----------
@router.callback_query(F.data.startswith("wp:"))
async def wp_start(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    await state.clear()
    await state.set_state(WorkPrice.amount)
    await state.update_data(oid=oid)
    await call.message.answer(f"💵 Zakaz #{oid} uchun ish haqi summasini yozing (so'mda):")
    await call.answer()


@router.message(WorkPrice.amount, F.text)
async def wp_save(m: Message, state: FSMContext):
    v = parse_amount(m.text, allow_zero=True)
    if v is None:
        await m.answer("Summani raqam bilan yozing (masalan: 500000):")
        return
    oid = (await state.get_data())["oid"]
    await db.execute("UPDATE orders SET work_price=?, updated_at=? WHERE id=?", (v, db.now(), oid))
    await db.log(m.from_user.id, "ish_haqi", f"#{oid} = {v:.0f}")
    await state.clear()
    await show_order(m, oid)


# ---------- Taxminiy smeta ----------
@router.callback_query(F.data.startswith("est:"))
async def est_start(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    await state.clear()
    await state.set_state(Estimate.amount)
    await state.update_data(oid=oid)
    await call.message.answer(f"📋 Zakaz #{oid} uchun taxminiy smeta jami summasini yozing:")
    await call.answer()


@router.message(Estimate.amount, F.text)
async def est_save(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("Summani raqam bilan yozing:")
        return
    oid = (await state.get_data())["oid"]
    await db.execute("UPDATE orders SET estimate=?, estimate_ok=0, updated_at=? WHERE id=?", (v, db.now(), oid))
    await db.log(m.from_user.id, "smeta", f"#{oid} = {v:.0f}")
    await state.clear()
    await show_order(m, oid)


@router.callback_query(F.data.startswith("sm:"))
async def send_smeta(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await load(call, oid)
    if not o:
        return
    if not o["client_tg"]:
        await call.answer("Bu mijoz botdan foydalanmaydi (telefon orqali qo'shilgan).", show_alert=True)
        return
    kb = ikb([[("✅ Smetani tasdiqlayman", f"cok:{oid}")]]) if o["estimate"] and not o["estimate_ok"] else None
    await tell_client(bot, o, "🧾 <b>Smeta</b>\n\n" + await order_card(o, client_view=True), kb)
    await call.answer("Mijozga yuborildi", show_alert=True)


# ---------- Materiallar ----------
@router.callback_query(F.data.startswith("mat:"))
async def mat_start(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    await state.clear()
    await state.set_state(MatAdd.name)
    await state.update_data(oid=oid)
    await call.message.answer("🧱 Material nomini yozing (masalan: VVG 3x2.5 sim):")
    await call.answer()


@router.message(MatAdd.name, F.text)
async def mat_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:100])
    await state.set_state(MatAdd.qty)
    await m.answer("Miqdori? (masalan: 50 yoki 12.5)")


@router.message(MatAdd.qty, F.text)
async def mat_qty(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("Miqdorni raqam bilan yozing:")
        return
    await state.update_data(qty=v)
    await state.set_state(MatAdd.price)
    await m.answer("Bir birligining narxi (so'm)?")


@router.message(MatAdd.price, F.text)
async def mat_price(m: Message, state: FSMContext):
    v = parse_amount(m.text, allow_zero=True)
    if v is None:
        await m.answer("Narxni raqam bilan yozing:")
        return
    d = await state.get_data()
    await db.execute(
        "INSERT INTO materials (order_id, name, qty, price, created_at) VALUES (?, ?, ?, ?, ?)",
        (d["oid"], d["name"], d["qty"], v, db.now()),
    )
    await db.log(m.from_user.id, "material", f"#{d['oid']} {d['name']} {d['qty']:g}x{v:.0f}")
    await state.clear()
    await m.answer(
        f"✅ Qo'shildi: {esc(d['name'])} — {d['qty']:g} × {fmt(v)} = <b>{fmt(d['qty'] * v)}</b>",
        reply_markup=ikb([[("➕ Yana material", f"mat:{d['oid']}")], [("📂 Zakazga qaytish", f"o:{d['oid']}")]]),
    )


@router.callback_query(F.data.startswith("ml:"))
async def mat_list(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    rows = await db.fetchall("SELECT * FROM materials WHERE order_id=? ORDER BY id", (oid,))
    if rows:
        total = sum(r["qty"] * r["price"] for r in rows)
        text = f"🧱 <b>Zakaz #{oid} materiallari</b>\n\n" + "\n".join(
            f"{i}. {esc(r['name'])}: {r['qty']:g} × {fmt(r['price'])} = {fmt(r['qty'] * r['price'])}"
            for i, r in enumerate(rows, 1)
        ) + f"\n\nJami: <b>{fmt(total)}</b>"
        kb = ikb(
            [[(f"🗑 {i}. {r['name']}"[:40], f"md:{r['id']}:{oid}")] for i, r in enumerate(rows, 1)]
            + [[("📂 Zakazga qaytish", f"o:{oid}")]]
        )
    else:
        text = "Materiallar hali kiritilmagan."
        kb = ikb([[("➕ Material qo'shish", f"mat:{oid}")], [("📂 Zakazga qaytish", f"o:{oid}")]])
    await edit_or_send(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("md:"))
async def mat_delete(call: CallbackQuery):
    _, mid, oid = call.data.split(":")
    mid, oid = int(mid), int(oid)
    if not await load(call, oid):
        return
    await db.execute("DELETE FROM materials WHERE id=? AND order_id=?", (mid, oid))
    await db.log(call.from_user.id, "material_ochirildi", f"#{oid} material id {mid}")
    call.data = f"ml:{oid}"
    await mat_list(call)


# ---------- To'lovlar ----------
@router.callback_query(F.data.startswith("pay:"))
async def pay_start(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    await state.clear()
    await state.set_state(PayAdd.amount)
    await state.update_data(oid=oid)
    await call.message.answer(f"💳 Zakaz #{oid}: qabul qilingan summani yozing (so'mda):")
    await call.answer()


@router.message(PayAdd.amount, F.text)
async def pay_amount(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("Summani raqam bilan yozing:")
        return
    await state.update_data(amount=v)
    await state.set_state(PayAdd.kind)
    await m.answer(f"Summa: <b>{fmt(v)}</b>\nTuri:", reply_markup=ikb([[("💰 Avans", "pk:avans"), ("💳 To'lov", "pk:tolov")]]))


@router.callback_query(PayAdd.kind, F.data.startswith("pk:"))
async def pay_kind(call: CallbackQuery, state: FSMContext):
    await state.update_data(kind=call.data.split(":")[1])
    await state.set_state(PayAdd.method)
    await call.message.edit_text(
        "To'lov usuli:",
        reply_markup=ikb([[("💵 Naqd", "pm:naqd"), ("💳 Karta", "pm:karta"), ("🏦 O'tkazma", "pm:otkazma")]]),
    )
    await call.answer()


@router.callback_query(PayAdd.method, F.data.startswith("pm:"))
async def pay_method(call: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    method = call.data.split(":")[1]
    await db.execute(
        "INSERT INTO payments (order_id, amount, kind, method, created_at) VALUES (?, ?, ?, ?, ?)",
        (d["oid"], d["amount"], d["kind"], method, db.now()),
    )
    await db.log(call.from_user.id, "tolov", f"#{d['oid']} {d['amount']:.0f} ({d['kind']}, {method})")
    await state.clear()
    o = await db.get_order(d["oid"])
    await tell_client(
        bot, o,
        f"✅ To'lov qabul qilindi: <b>{fmt(d['amount'])}</b>\n📦 Zakaz #{o['id']}\n💳 Qolgan qarz: <b>{fmt(o['debt'])}</b>",
    )
    await show_order(call, d["oid"])
    await call.answer("To'lov saqlandi")


@router.callback_query(F.data.startswith("pl:"))
async def pay_list(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    rows = await db.fetchall("SELECT * FROM payments WHERE order_id=? ORDER BY id", (oid,))
    if rows:
        text = f"💳 <b>Zakaz #{oid} to'lovlari</b>\n\n" + "\n".join(
            f"{i}. {r['created_at'][:16]} — {fmt(r['amount'])} ({r['kind']}, {r['method']})"
            for i, r in enumerate(rows, 1)
        )
        kb = ikb(
            [[(f"🗑 {i}. {fmt(r['amount'])}", f"pd:{r['id']}:{oid}")] for i, r in enumerate(rows, 1)]
            + [[("📂 Zakazga qaytish", f"o:{oid}")]]
        )
    else:
        text = "To'lovlar hali yo'q."
        kb = ikb([[("📂 Zakazga qaytish", f"o:{oid}")]])
    await edit_or_send(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("pd:"))
async def pay_delete(call: CallbackQuery):
    _, pid, oid = call.data.split(":")
    pid, oid = int(pid), int(oid)
    if not await load(call, oid):
        return
    await db.execute("DELETE FROM payments WHERE id=? AND order_id=?", (pid, oid))
    await db.log(call.from_user.id, "tolov_ochirildi", f"#{oid} to'lov id {pid}")
    call.data = f"pl:{oid}"
    await pay_list(call)


# ---------- Media va eslatma ----------
@router.callback_query(F.data.startswith("media:"))
async def show_media(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    if not await load(call, oid):
        return
    n = await send_order_media(bot, call.from_user.id, oid)
    await call.answer("Rasm/video/lokatsiya yo'q" if n == 0 else "Yuborildi", show_alert=(n == 0))


@router.callback_query(F.data.startswith("rem:"))
async def remind(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await load(call, oid)
    if not o:
        return
    if o["debt"] <= 0.5:
        await call.answer("Bu zakaz bo'yicha qarz yo'q", show_alert=True)
        return
    if not o["client_tg"]:
        await call.answer("Mijoz botdan foydalanmaydi. Telefon orqali eslating.", show_alert=True)
        return
    await tell_client(bot, o, f"🔔 Eslatma: zakaz #{oid} bo'yicha qarzingiz <b>{fmt(o['debt'])}</b>.")
    await db.log(call.from_user.id, "qarz_eslatma", f"#{oid}")
    await call.answer("Eslatma yuborildi", show_alert=True)
