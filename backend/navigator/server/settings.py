"""Server configuration, read from the environment."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage. Without MONGO_URI the server keeps everything in memory, which
    # is only meant for tests and quick local runs.
    mongo_uri: str | None = None
    db_name: str = "cluster-navigator"
    # Reports older than this are deleted, so a decommissioned cluster drops out.
    report_ttl_days: int = 7

    # Collectors authenticate to the ingest endpoint with this bearer token.
    ingest_token: SecretStr

    # A cluster whose last report is older than this is shown as stale.
    stale_after_seconds: int = 5400

    # Placeholders: {name}, {domain}, {clusterId}. Empty means no Grafana link.
    grafana_url_template: str | None = None

    # Who may see what. See navigator/server/policy.py.
    # How users sign in. The chart always runs "openshift". "dev" (fixed users)
    # and "none" (no sign-in) are for local runs and tests.
    auth_provider: Literal["none", "dev", "openshift"] = "openshift"
    # A JSON list: ADMIN_GROUPS='["ocp-admins", "platform-team"]'
    admin_groups: Annotated[list[str], NoDecode] = []
    roles: str | None = None
    dev_users: str | None = None
    service_tokens: str | None = None
    session_secret: SecretStr | None = None
    session_ttl_hours: int = 12
    cookie_secure: bool = True

    # OpenShift OAuth (auth_provider=openshift).
    public_url: str | None = None
    openshift_api_url: str = "https://kubernetes.default.svc"
    openshift_sa_dir: str = "/var/run/secrets/kubernetes.io/serviceaccount"
    # An extra CA for the OAuth server's Route, when the site signs its router
    # certificates with its own CA. Public CAs and the cluster CA are always trusted.
    openshift_ca_file: str | None = None
    group_cache_seconds: int = 60

    # Where the built UI lives. Empty disables serving it.
    ui_dir: str | None = None

    @field_validator("admin_groups", mode="before")
    @classmethod
    def _admin_groups(cls, value: object) -> object:
        return json_list(value, "ADMIN_GROUPS") if isinstance(value, str) else value

    def json_setting(self, name: str) -> dict:
        raw = getattr(self, name)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name.upper()} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{name.upper()} must be a JSON object")
        return value


def json_list(raw: str | None, name: str) -> list[str]:
    """A list setting, written as a JSON array: '["ocp-admins", "platform-team"]'. Blank means empty."""
    if not raw or not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{name} must be a JSON list, for example ["ocp-admins"]: {exc}') from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f'{name} must be a JSON list of strings, for example ["ocp-admins"]')
    return [item.strip() for item in value if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
