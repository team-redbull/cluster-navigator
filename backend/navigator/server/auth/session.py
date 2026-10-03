"""Signed cookies. The session holds only the username.

Roles are deliberately not stored in it. They are worked out from live group
membership on every request, so a session cannot outlive the access it was
given.
"""

import secrets

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE = "cn_session"
STATE_COOKIE = "cn_oauth_state"
STATE_TTL_SECONDS = 600


class SessionCodec:
    def __init__(self, secret: str | None, ttl_seconds: int) -> None:
        # Without a configured secret a random one is used. Sessions then end
        # on restart and do not work across replicas, which is fine locally.
        self.generated = not secret
        self._secret = secret or secrets.token_urlsafe(32)
        self.ttl_seconds = ttl_seconds
        self._sessions = URLSafeTimedSerializer(self._secret, salt="session")
        self._states = URLSafeTimedSerializer(self._secret, salt="oauth-state")

    def encode(self, username: str) -> str:
        return self._sessions.dumps({"u": username})

    def decode(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            data = self._sessions.loads(token, max_age=self.ttl_seconds)
        except BadSignature:
            return None
        username = data.get("u") if isinstance(data, dict) else None
        return username if isinstance(username, str) and username else None

    def encode_state(self, return_to: str) -> tuple[str, str]:
        """Return (state, cookie). The state goes to the identity provider, the cookie to the browser."""
        nonce = secrets.token_urlsafe(16)
        return nonce, self._states.dumps({"n": nonce, "r": return_to})

    def decode_state(self, cookie: str | None, state: str | None) -> str | None:
        """Return where to send the user, or None when the state does not check out."""
        if not cookie or not state:
            return None
        try:
            data = self._states.loads(cookie, max_age=STATE_TTL_SECONDS)
        except BadSignature:
            return None
        if not isinstance(data, dict) or not secrets.compare_digest(str(data.get("n", "")), state):
            return None
        return str(data.get("r") or "/")


def safe_return_to(value: str | None) -> str:
    """Only allow redirects back into this site."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value
