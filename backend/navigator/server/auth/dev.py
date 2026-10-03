"""Fixed users for local development. Never use in production.

    DEV_USERS='{"admin": {"password": "admin", "groups": ["ocp-admins"]}}'
"""

import hmac

from navigator.server.auth.base import PasswordProvider


class DevProvider(PasswordProvider):
    def __init__(self, users: dict[str, dict]) -> None:
        self._users = {name.lower(): user for name, user in users.items()}

    async def authenticate(self, username: str, password: str) -> str | None:
        user = self._users.get(username.strip().lower())
        expected = str(user.get("password", "")) if user else ""
        # Compare even when the user is unknown, so timing does not reveal which names exist.
        matches = hmac.compare_digest(password.encode(), expected.encode())
        return username.strip().lower() if user and expected and matches else None

    async def groups_for(self, username: str, wanted: frozenset[str]) -> frozenset[str]:
        user = self._users.get(username.lower()) or {}
        return frozenset(user.get("groups") or []) & wanted
