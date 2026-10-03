from enum import StrEnum


class ClusterType(StrEnum):
    """The four kinds of cluster the platform knows. The UI menu is this list."""

    GENERIC = "generic"
    CLICK = "click"
    MCE = "mce"
    KUBEVIRT = "kubevirt"


TYPE_LABELS: dict[ClusterType, str] = {
    ClusterType.GENERIC: "Generic",
    ClusterType.CLICK: "Click Cluster",
    ClusterType.MCE: "MCE",
    ClusterType.KUBEVIRT: "KubeVirt",
}
