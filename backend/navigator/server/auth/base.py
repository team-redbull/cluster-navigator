from abc import ABC, abstractmethod
from typing import Literal


class AuthError(Exception):
    """Sign-in could not be completed. The message is safe to show the user."""


class AuthProvider(ABC):
    mode: Literal["password", "redirect", "disabled"] = "disabled"

    @abstractmethod
    async def groups_for(self, username: str, wanted: frozenset[str]) -> frozenset[str]:
        """Return the subset of ``wanted`` groups that ``username`` belongs to.

        Called on every request, so that removing someone from a group takes
        their access away without waiting for their session to end.
        Implementations cache.
        """

    async def close(self) -> None:
        return None


class NoAuth(AuthProvider):
    mode = "disabled"

    async def groups_for(self, username: str, wanted: frozenset[str]) -> frozenset[str]:
        return frozenset()


class PasswordProvider(AuthProvider):
    """The UI shows a username and password form."""

    mode = "password"

    @abstractmethod
    async def authenticate(self, username: str, password: str) -> str | None:
        """Return the canonical username, or None when the credentials are wrong."""


class RedirectProvider(AuthProvider):
    """The browser is sent to an identity provider and comes back with a code."""

    mode = "redirect"

    @abstractmethod
    async def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    async def exchange(self, *, code: str, redirect_uri: str) -> str:
        """Trade the code for the signed-in username."""
