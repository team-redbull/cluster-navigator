"""Log in with OpenShift.

The same idea as the oauth-proxy sidecar in front of the Temporal UI, done in
the server so that anonymous visitors still get in as clients:

1. The browser is sent to the cluster's OAuth server. Users type their LDAP
   credentials into the normal OpenShift login page. This service never sees
   a password.
2. The server's own ServiceAccount is the OAuth client. No OAuthClient object
   is needed. The redirect URI is allowed by an annotation on the
   ServiceAccount that points at the Route.
3. The returned token is used once, to ask the API who the user is.
4. Group membership is read from OpenShift ``Group`` objects with the
   ServiceAccount's own token. On LDAP-backed clusters those are created by
   ``oc adm groups sync`` or the group-sync operator, not by the login itself.
   The lookup is cached, so membership changes apply within
   ``group_cache_seconds``.
"""

import logging
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from navigator.server.auth.base import AuthError, RedirectProvider

logger = logging.getLogger(__name__)

DISCOVERY_PATH = "/.well-known/oauth-authorization-server"
SCOPE = "user:info"


class OpenShiftProvider(RedirectProvider):
    def __init__(
        self,
        *,
        api_url: str,
        sa_dir: str,
        ca_file: str | None = None,
        group_cache_seconds: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._sa_dir = Path(sa_dir)
        self._cache_seconds = group_cache_seconds
        ca = ca_file or str(self._sa_dir / "ca.crt")
        self._client = client or httpx.AsyncClient(verify=ca, timeout=10.0)
        self._endpoints: dict | None = None
        self._groups: dict[str, tuple[float, frozenset[str]]] = {}

    # The token is re-read on every use: bound ServiceAccount tokens rotate.
    def _sa_token(self) -> str:
        return (self._sa_dir / "token").read_text().strip()

    def _client_id(self) -> str:
        # A ServiceAccount token's subject is "system:serviceaccount:<ns>:<name>",
        # which is exactly the OAuth client ID OpenShift expects for it.
        subject = _unverified_claims(self._sa_token()).get("sub", "")
        if not str(subject).startswith("system:serviceaccount:"):
            raise AuthError("Sign-in is misconfigured: the server is not running as a ServiceAccount.")
        return str(subject)

    async def _discover(self) -> dict:
        if self._endpoints is None:
            response = await self._client.get(self._api_url + DISCOVERY_PATH)
            response.raise_for_status()
            self._endpoints = response.json()
        return self._endpoints

    async def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        endpoints = await self._discover()
        query = urlencode({
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
        })
        return f"{endpoints['authorization_endpoint']}?{query}"

    async def exchange(self, *, code: str, redirect_uri: str) -> str:
        endpoints = await self._discover()
        try:
            token_response = await self._client.post(
                endpoints["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id(),
                    "client_secret": self._sa_token(),
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            user_response = await self._client.get(
                f"{self._api_url}/apis/user.openshift.io/v1/users/~",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            username = user_response.json()["metadata"]["name"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("OpenShift sign-in failed: %s: %s", type(exc).__name__, exc)
            raise AuthError("Sign-in with OpenShift failed. Try again.") from exc
        return username

    async def _members(self, group: str) -> frozenset[str]:
        cached = self._groups.get(group)
        now = time.monotonic()
        if cached and now - cached[0] < self._cache_seconds:
            return cached[1]
        try:
            response = await self._client.get(
                f"{self._api_url}/apis/user.openshift.io/v1/groups/{group}",
                headers={"Authorization": f"Bearer {self._sa_token()}"},
            )
            if response.status_code == 404:
                logger.warning("OpenShift Group %s does not exist: nobody gets its role", group)
                members: frozenset[str] = frozenset()
            else:
                response.raise_for_status()
                members = frozenset(response.json().get("users") or [])
        except (httpx.HTTPError, ValueError, OSError) as exc:
            # The API is unreachable. Keep the last answer if there is one.
            # With no answer at all, deny: an outage must not grant access.
            logger.warning("could not read OpenShift Group %s: %s", group, exc)
            return cached[1] if cached else frozenset()
        self._groups[group] = (now, members)
        return members

    async def groups_for(self, username: str, wanted: frozenset[str]) -> frozenset[str]:
        held = set()
        for group in wanted:
            if username in await self._members(group):
                held.add(group)
        return frozenset(held)

    async def close(self) -> None:
        await self._client.aclose()


def _unverified_claims(token: str) -> dict:
    """Read the claims of our own ServiceAccount token, to learn its name."""
    import base64
    import json

    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
