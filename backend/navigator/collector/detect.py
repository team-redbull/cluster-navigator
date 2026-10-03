"""Decides the cluster type. This is the only place the rules live.

The collector looks at first-class cluster APIs instead of asking whoever
installs it, because a deploy-time flag is easy to forget and silently wrong.
An explicit override always wins, for the cluster the rules get wrong.

Order matters. A cluster can match more than one rule:
  1. override              -> whatever was asked for
  2. MultiClusterEngine    -> MCE       (a hub that manages other clusters)
  3. HyperConverged        -> KubeVirt  (runs OpenShift Virtualization)
  4. external control plane-> Click     (a hosted cluster)
  5. otherwise             -> Generic   (a standalone UPI cluster)
"""

from navigator.models import ClusterType, Detection

HOSTED_TOPOLOGY = "External"


def detect_type(
    *,
    control_plane_topology: str | None,
    has_multicluster_engine: bool,
    has_hyperconverged: bool,
    platform: str | None = None,
    override: str | None = None,
) -> tuple[ClusterType, Detection]:
    signals: dict[str, str | bool | None] = {
        "controlPlaneTopology": control_plane_topology,
        "multiClusterEngine": has_multicluster_engine,
        "hyperConverged": has_hyperconverged,
        "platform": platform,
    }

    if override and override.strip().lower() not in ("", "auto"):
        return ClusterType(override.strip().lower()), Detection(source="override", signals=signals)

    if has_multicluster_engine:
        cluster_type = ClusterType.MCE
    elif has_hyperconverged:
        cluster_type = ClusterType.KUBEVIRT
    elif control_plane_topology == HOSTED_TOPOLOGY:
        cluster_type = ClusterType.CLICK
    else:
        cluster_type = ClusterType.GENERIC
    return cluster_type, Detection(source="auto", signals=signals)
