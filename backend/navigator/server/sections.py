"""The expanded view of a cluster, as a list of sections.

Every section declares the audience allowed to see it. ``build_sections``
drops the ones the caller may not see, so restricted data is never sent.

To show extra data to a new kind of user: write one more builder below, give
it a new audience name, and grant that audience to a role in ``policy.py``.
The UI draws sections from their ``kind`` and needs no change.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from navigator.models import TYPE_LABELS, ClusterType
from navigator.server.merge import MergedCluster
from navigator.server.policy import ADMIN, PUBLIC, Principal
from navigator.server.views import Column, KeyValue, Section


@dataclass(frozen=True)
class SectionDef:
    id: str
    title: str
    audience: str
    build: Callable[["SectionDef", MergedCluster, datetime], Section | None]


def _age(then: datetime | None, now: datetime) -> str | None:
    if then is None:
        return None
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds // 60} minutes ago"
    if seconds < 172800:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _kv(definition: SectionDef, items: list[KeyValue]) -> Section | None:
    items = [item for item in items if item.value not in (None, "", [])]
    if not items:
        return None
    return Section(id=definition.id, title=definition.title, audience=definition.audience, kind="kv", items=items)


def _overview(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    report = c.report
    status = {
        "reporting": "Reporting",
        "stale": "Stale: the collector has stopped reporting",
    }[c.card.status.value]
    return _kv(d, [
        KeyValue(label="Type", value=TYPE_LABELS[c.card.type]),
        KeyValue(label="Site", value=c.card.site),
        KeyValue(label="Network", value=c.card.network),
        KeyValue(label="Parent MCE", value=c.card.mce, mono=True),
        KeyValue(label="OpenShift version", value=c.card.openshift_version, mono=True),
        KeyValue(label="Kubernetes version", value=report.kubernetes_version, mono=True),
        KeyValue(label="Base domain", value=report.base_domain, mono=True),
        KeyValue(label="API URL", value=report.api_url, mono=True),
        KeyValue(label="Cluster ID", value=report.cluster_id, mono=True),
        KeyValue(label="Status", value=status),
        KeyValue(label="Last report", value=_age(c.received_at, now)),
    ])


def _addresses(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    report = c.report
    dns = report.dns
    return _kv(d, [
        KeyValue(label="Router LB", value=c.card.router_lb, mono=True),
        KeyValue(label="API addresses", value=report.api_addresses, mono=True),
        KeyValue(label="DNS servers", value=dns.servers if dns else [], mono=True),
        KeyValue(label="Search domains", value=dns.search_domains if dns else [], mono=True),
    ])


def _segments(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    if not c.segments:
        return None
    return Section(
        id=d.id, title=d.title, audience=d.audience, kind="table",
        columns=[
            Column(key="cidr", label="Segment", mono=True),
            Column(key="type", label="Type"),
            Column(key="vlan", label="VLAN", mono=True),
            Column(key="epg", label="EPG", mono=True),
            Column(key="site", label="Site"),
        ],
        rows=[
            {"cidr": s.cidr, "type": s.type, "vlan": s.vlan_id, "epg": s.epg_name, "site": s.site}
            for s in c.segments
        ],
    )


def _resources(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    report = c.report
    if not report.resources:
        return None
    r = report.resources
    control_plane = sum(1 for n in report.nodes if {"master", "control-plane"} & set(n.roles))
    items = [
        KeyValue(label="Nodes", value=len(report.nodes)),
        KeyValue(label="Control plane", value=control_plane),
        KeyValue(label="CPU cores", value=r.cpu),
        KeyValue(label="Memory (GiB)", value=r.memory_gi),
        KeyValue(label="Pod capacity", value=r.pods),
        KeyValue(label="Ephemeral storage (GiB)", value=r.ephemeral_storage_gi),
    ]
    if r.gpu:
        items.append(KeyValue(label="GPUs", value=r.gpu))
    return Section(id=d.id, title=d.title, audience=d.audience, kind="stats", items=items)


def _nodes(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    if not c.report.nodes:
        return None
    return Section(
        id=d.id, title=d.title, audience=d.audience, kind="table",
        columns=[
            Column(key="name", label="Node", mono=True),
            Column(key="roles", label="Roles"),
            Column(key="ip", label="Internal IP", mono=True),
            Column(key="ready", label="Ready"),
            Column(key="cpu", label="CPU", mono=True),
            Column(key="memory", label="Memory (GiB)", mono=True),
            Column(key="kubelet", label="Kubelet", mono=True),
            Column(key="os", label="OS"),
        ],
        rows=[
            {
                "name": n.name, "roles": ", ".join(n.roles) or "worker", "ip": n.internal_ip,
                "ready": n.ready, "cpu": n.cpu, "memory": n.memory_gi,
                "kubelet": n.kubelet_version, "os": n.os_image,
            }
            for n in c.report.nodes
        ],
    )


def _storage(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    if not c.report.storage_classes:
        return None
    return Section(
        id=d.id, title=d.title, audience=d.audience, kind="table",
        columns=[
            Column(key="name", label="Storage class", mono=True),
            Column(key="provisioner", label="Provisioner", mono=True),
            Column(key="default", label="Default"),
        ],
        rows=[
            {"name": s.name, "provisioner": s.provisioner, "default": s.is_default}
            for s in c.report.storage_classes
        ],
    )


def _identity(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    if not c.identity_providers:
        return None
    return Section(id=d.id, title=d.title, audience=d.audience, kind="tags", tags=c.identity_providers)


def _hosted_clusters(d: SectionDef, c: MergedCluster, now: datetime) -> Section | None:
    if c.card.type != ClusterType.MCE or not c.report.hosted_clusters:
        return None
    return Section(
        id=d.id, title=d.title, audience=d.audience, kind="table",
        columns=[
            Column(key="name", label="Hosted cluster", mono=True),
            Column(key="namespace", label="Namespace", mono=True),
            Column(key="version", label="Version", mono=True),
            Column(key="platform", label="Platform"),
            Column(key="pools", label="Node pools", mono=True),
            Column(key="replicas", label="Replicas", mono=True),
            # Whether that cluster's own collector is installed and reporting.
            # One that is not does not appear in the cluster list at all.
            Column(key="reporting", label="Collector reporting"),
        ],
        rows=[
            {
                "name": h.name, "namespace": h.namespace, "version": h.version,
                "platform": h.platform, "pools": h.node_pools, "replicas": h.replicas,
                "reporting": h.name.lower() in c.hosted_reporting,
            }
            for h in c.report.hosted_clusters
        ],
    )


# Order here is the order on screen: the compact blocks first, then the tables.
SECTIONS: list[SectionDef] = [
    SectionDef("overview", "Overview", PUBLIC, _overview),
    # Not titled "Network": that is the network the cluster belongs to, in the overview.
    SectionDef("addresses", "Addresses and DNS", PUBLIC, _addresses),
    SectionDef("resources", "Capacity", PUBLIC, _resources),
    SectionDef("identity", "Identity providers", PUBLIC, _identity),
    SectionDef("segments", "Segments", PUBLIC, _segments),
    SectionDef("nodes", "Nodes", PUBLIC, _nodes),
    SectionDef("storage", "Storage classes", PUBLIC, _storage),
    SectionDef("hostedClusters", "Hosted clusters", ADMIN, _hosted_clusters),
]


def build_sections(cluster: MergedCluster, principal: Principal, now: datetime) -> list[Section]:
    sections = []
    for definition in SECTIONS:
        if not principal.can_see_audience(definition.audience):
            continue
        section = definition.build(definition, cluster, now)
        if section is not None:
            sections.append(section)
    return sections
