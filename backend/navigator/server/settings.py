"""Server configuration, read from the environment."""

import json
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Segment types shown on the cluster box. The rest (inventory, PXE) are
    # infrastructure networks and appear only in the details. The segments
    # themselves arrive in each cluster's report; the server never talks to
    # Segments Manager.
    primary_segment_types: str = "UPI,HC,MCE,HUB"

    # A cluster whose last report is older than this is shown as stale.
    stale_after_seconds: int = 5400

    # Placeholders: {name}, {domain}, {clusterId}. Empty means no Grafana link.
    grafana_url_template: str | None = None

    # Who may see what. See navigator/server/policy.py.
    auth_provider: Literal["none", "dev", "openshift"] = "none"
    admin_groups: str = ""
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

    def primary_types(self) -> frozenset[str]:
        return frozenset(split_list(self.primary_segment_types, upper=True))

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


def split_list(raw: str | None, *, upper: bool = False) -> list[str]:
    items = [item.strip() for item in (raw or "").split(",")]
    return [item.upper() if upper else item for item in items if item]


@lru_cache
def get_settings() -> Settings:
    return Settings()
