"""Builds the cluster list from the collectors' reports.

Every cluster here is a report. A cluster that has not reported does not
exist. Its segments and site are in the report too: the collector looked them
up in Segments Manager.

The one thing joined across reports is a hosted cluster's parent MCE. It is
taken from the MCE's own report, which lists the HostedClusters it runs, and
is never guessed from the cluster's name.

Whether a cluster is hosted is a fact about the cluster, not about its type.
A Click Cluster always is. A KubeVirt cluster (one with OpenShift
Virtualization installed) can be hosted or standalone.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from navigator.models import ClusterReport, ClusterType, HostedClusterRef, SegmentReport
from navigator.server.store import StoredReport
from navigator.server.views import ClusterCard, ClusterStatus

# How OpenShift marks a control plane that runs outside the cluster.
HOSTED_TOPOLOGY = "External"


@dataclass(frozen=True)
class MergeOptions:
    stale_after: timedelta = timedelta(minutes=90)
    primary_segment_types: frozenset[str] = frozenset({"UPI", "HC", "MCE", "HUB"})
    grafana_url_template: str | None = None


@dataclass
class MergedCluster:
    card: ClusterCard
    report: ClusterReport
    received_at: datetime
    # What this cluster's MCE says about it, when it is a hosted cluster.
    hosted_ref: HostedClusterRef | None = None
    identity_providers: list[str] = field(default_factory=list)
    # On an MCE: which of the clusters it hosts have a collector reporting.
    hosted_reporting: frozenset[str] = frozenset()

    @property
    def segments(self) -> list[SegmentReport]:
        return self.report.segments


class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _render(template: str | None, **values: str | None) -> str | None:
    if not template:
        return None
    return template.format_map(_Missing({k: v or "" for k, v in values.items()}))


def _primary(segments: list[SegmentReport], primary_types: frozenset[str]) -> list[str]:
    """The segments shown on the box: the cluster-facing ones, not inventory or PXE."""
    primary = [s.cidr for s in segments if (s.type or "").upper() in primary_types]
    return primary or [s.cidr for s in segments]


def merge(
    reports: list[StoredReport],
    *,
    now: datetime,
    options: MergeOptions = MergeOptions(),
) -> list[MergedCluster]:
    # Which MCE hosts which cluster, according to the MCEs themselves.
    hosted: dict[str, tuple[str, HostedClusterRef]] = {}
    for stored in reports:
        for ref in stored.report.hosted_clusters:
            hosted[ref.name.lower()] = (stored.report.name, ref)

    reporting = frozenset(stored.report.name.lower() for stored in reports)

    merged: list[MergedCluster] = []
    for stored in reports:
        report = stored.report
        parent_name, ref = hosted.get(report.name.lower(), (None, None))
        is_hosted = (
            parent_name is not None
            or report.type == ClusterType.CLICK
            or report.detection.signals.get("controlPlaneTopology") == HOSTED_TOPOLOGY
        )
        fresh = now - stored.received_at <= options.stale_after
        merged.append(
            MergedCluster(
                card=ClusterCard(
                    id=report.cluster_id,
                    name=report.name,
                    type=report.type,
                    site=report.site,
                    status=ClusterStatus.REPORTING if fresh else ClusterStatus.STALE,
                    openshift_version=report.openshift_version or (ref.version if ref else None),
                    segments=_primary(report.segments, options.primary_segment_types),
                    router_lb=report.router_lb,
                    hosted=is_hosted,
                    mce=parent_name,
                    console_url=report.console_url,
                    grafana_url=_render(
                        options.grafana_url_template,
                        name=report.name,
                        domain=report.base_domain,
                        clusterId=report.cluster_id,
                    ),
                    last_seen=stored.received_at,
                ),
                report=report,
                received_at=stored.received_at,
                hosted_ref=ref,
                # A hosted cluster's identity providers are configured on its
                # MCE, so its own OAuth object is usually empty.
                identity_providers=report.identity_providers or (ref.identity_providers if ref else []),
                hosted_reporting=frozenset(
                    ref.name.lower() for ref in report.hosted_clusters if ref.name.lower() in reporting
                ),
            )
        )

    merged.sort(key=lambda c: c.card.name)
    return merged
