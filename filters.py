from aiogram.filters import BaseFilter

import db


class RoleFilter(BaseFilter):
    """admin_only=False: admin va ustalar. admin_only=True: faqat admin."""

    def __init__(self, admin_only: bool = False):
        self.admin_only = admin_only

    async def __call__(self, event) -> bool:
        role = await db.get_role(event.from_user.id)
        if self.admin_only:
            return role == "admin"
        return role in ("admin", "usta")
