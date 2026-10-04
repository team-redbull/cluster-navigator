"""What the API returns."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from navigator.models import ClusterType, Model

Scalar = str | int | float | bool | None


class ClusterStatus(StrEnum):
    REPORTING = "reporting"  # a collector report arrived recently
    STALE = "stale"  # the last report is too old


class ClusterCard(Model):
    """The collapsed view: what the cluster box shows."""

    id: str
    name: str
    type: ClusterType
    site: str | None = None
    # The network it belongs to, as set in its collector's chart.
    network: str | None = None
    status: ClusterStatus
    openshift_version: str | None = None
    segments: list[str] = Field(default_factory=list)
    router_lb: list[str] = Field(default_factory=list)
    # The control plane runs on an MCE. True for every Click Cluster, and for a
    # KubeVirt cluster that is hosted rather than standalone.
    hosted: bool = False
    # The MCE it runs on, when that MCE reports and the caller may know it.
    mce: str | None = None
    console_url: str | None = None
    grafana_url: str | None = None
    last_seen: datetime | None = None


class KeyValue(Model):
    label: str
    value: Scalar | list[str] = None
    mono: bool = False


class Column(Model):
    key: str
    label: str
    mono: bool = False


class Section(Model):
    """One block of the expanded view.

    The server says how to draw it (``kind``), so the UI needs no change when
    a new section is added for a new audience.
    """

    id: str
    title: str
    audience: str
    kind: Literal["kv", "stats", "table", "tags"]
    items: list[KeyValue] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    rows: list[dict[str, Scalar]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ClusterDetail(ClusterCard):
    sections: list[Section] = Field(default_factory=list)


class Facets(Model):
    sites: list[str] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    mces: list[str] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)


class ClusterList(Model):
    items: list[ClusterCard]
    total: int
    facets: Facets
    counts: dict[str, int]


class TypeInfo(Model):
    id: ClusterType
    label: str


class Me(Model):
    authenticated: bool
    username: str | None = None
    roles: list[str] = Field(default_factory=list)
    # Only the cluster types this caller may open. The UI builds its menu from
    # this list, so a type the caller may not see is never mentioned to them.
    types: list[TypeInfo] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    login_mode: Literal["password", "redirect", "disabled"] = "disabled"
