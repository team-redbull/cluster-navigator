"""The report a collector sends to the server. This is the ingest contract."""

from datetime import datetime

from pydantic import Field

from navigator.models.base import Model
from navigator.models.types import ClusterType

SCHEMA_VERSION = 1


class NodeReport(Model):
    name: str
    roles: list[str] = Field(default_factory=list)
    internal_ip: str | None = None
    hostname: str | None = None
    ready: bool = False
    kubelet_version: str | None = None
    os_image: str | None = None
    cpu: int = 0
    memory_gi: float = 0.0


class Resources(Model):
    cpu: int = 0
    memory_gi: float = 0.0
    pods: int = 0
    ephemeral_storage_gi: float = 0.0
    gpu: int = 0


class StorageClass(Model):
    name: str
    provisioner: str
    is_default: bool = False


class DnsConfig(Model):
    servers: list[str] = Field(default_factory=list)
    search_domains: list[str] = Field(default_factory=list)


class SegmentReport(Model):
    """One network segment allocated to the cluster, as Segments Manager records it."""

    cidr: str
    site: str | None = None
    type: str | None = None
    vlan_id: int | None = None
    epg_name: str | None = None
    dhcp: bool | None = None


class HostedClusterRef(Model):
    """A hosted cluster as its MCE sees it. Only MCE collectors fill these in."""

    name: str
    namespace: str | None = None
    version: str | None = None
    platform: str | None = None
    node_pools: int = 0
    replicas: int = 0
    identity_providers: list[str] = Field(default_factory=list)


class Detection(Model):
    """How the cluster type was decided, kept so a wrong answer can be debugged."""

    source: str = "auto"  # "auto" or "override"
    signals: dict[str, str | bool | None] = Field(default_factory=dict)


class CollectorError(Model):
    collector: str
    error: str


class ClusterReport(Model):
    schema_version: int = SCHEMA_VERSION
    cluster_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=253)
    base_domain: str | None = None
    type: ClusterType
    detection: Detection = Field(default_factory=Detection)
    openshift_version: str | None = None
    kubernetes_version: str | None = None
    console_url: str | None = None
    api_url: str | None = None
    router_lb: list[str] = Field(default_factory=list)
    api_addresses: list[str] = Field(default_factory=list)
    # Looked up in Segments Manager by the collector, by cluster name.
    site: str | None = None
    segments: list[SegmentReport] = Field(default_factory=list)
    dns: DnsConfig | None = None
    nodes: list[NodeReport] = Field(default_factory=list)
    resources: Resources | None = None
    storage_classes: list[StorageClass] = Field(default_factory=list)
    identity_providers: list[str] = Field(default_factory=list)
    hosted_clusters: list[HostedClusterRef] = Field(default_factory=list)
    errors: list[CollectorError] = Field(default_factory=list)
    collector_version: str = "unknown"
    collected_at: datetime
