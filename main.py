import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import db
from config import BOT_TOKEN
from handlers import admin, client, common, orders, staff
from keyboards import MENU_BUTTONS


class ResetStateMiddleware(BaseMiddleware):
    """Menyu tugmasi yoki buyruq bosilsa, tugallanmagan jarayonni bekor qiladi."""

    async def __call__(self, handler, event, data):
        text = getattr(event, "text", None)
        if text and (text in MENU_BUTTONS or text.startswith("/")):
            state = data.get("state")
            if state:
                await state.clear()
        return await handler(event, data)


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit(".env faylida BOT_TOKEN yo'q")
    await db.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(ResetStateMiddleware())
    dp.include_router(admin.router)
    dp.include_router(orders.router)
    dp.include_router(staff.router)
    dp.include_router(client.router)
    dp.include_router(common.router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
