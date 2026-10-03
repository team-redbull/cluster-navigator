"""Sign-in. Anonymous callers are clients; signing in can only add access.

A provider answers two questions: who is this user, and which of the groups
we care about are they in. Mapping groups to roles is not its job. That lives
in ``policy.py``.

Providers:
  none       sign-in is switched off, everyone is a client
  dev        fixed users from DEV_USERS, for local runs
  openshift  "log in with OpenShift", backed by the cluster's LDAP identity
             provider and its synced Groups
"""

from navigator.server.auth.base import AuthProvider, NoAuth, PasswordProvider, RedirectProvider
from navigator.server.auth.dev import DevProvider
from navigator.server.auth.openshift import OpenShiftProvider
from navigator.server.auth.session import SessionCodec
from navigator.server.settings import Settings


def build_provider(settings: Settings) -> AuthProvider:
    if settings.auth_provider == "dev":
        return DevProvider(settings.json_setting("dev_users"))
    if settings.auth_provider == "openshift":
        return OpenShiftProvider(
            api_url=settings.openshift_api_url,
            sa_dir=settings.openshift_sa_dir,
            ca_file=settings.openshift_ca_file,
            group_cache_seconds=settings.group_cache_seconds,
        )
    return NoAuth()


__all__ = [
    "AuthProvider",
    "DevProvider",
    "NoAuth",
    "OpenShiftProvider",
    "PasswordProvider",
    "RedirectProvider",
    "SessionCodec",
    "build_provider",
]
