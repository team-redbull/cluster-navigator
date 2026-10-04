"""Builds one ClusterReport from the cluster API.

Each fact is gathered by its own step. A step that fails is recorded in
``report.errors`` and the rest of the report is still sent, so one missing
permission or a DNS hiccup does not hide the whole cluster. Only the cluster
ID and name are mandatory, because without them the server cannot file the
report.
"""

import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar
from urllib.parse import urlparse

import httpx

from navigator import __version__
from navigator.collector.detect import detect_type
from navigator.collector.kube import KubeClient
from navigator.collector.quantity import parse_quantity, to_gi
from navigator.collector.resolvconf import read_resolv_conf
from navigator.collector.segments import fetch_segments
from navigator.models import (
    ClusterReport,
    CollectorError,
    DnsConfig,
    HostedClusterRef,
    NodeReport,
    Resources,
    SegmentReport,
    StorageClass,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

CONFIG_API = "/apis/config.openshift.io/v1"
ROLE_LABEL_PREFIX = "node-role.kubernetes.io/"
GPU_RESOURCE = "nvidia.com/gpu"
DEFAULT_CLASS_ANNOTATION = "storageclass.kubernetes.io/is-default-class"


def resolve_host(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


class CollectionError(RuntimeError):
    """The report cannot be built at all."""


class Collector:
    def __init__(
        self,
        kube: KubeClient,
        *,
        type_override: str | None = None,
        name_override: str | None = None,
        network: str | None = None,
        resolver: Callable[[str], list[str]] = resolve_host,
        dns_reader: Callable[[], DnsConfig] = read_resolv_conf,
        segments_manager_url: str | None = None,
        segments_client: httpx.Client | None = None,
    ) -> None:
        self._kube = kube
        self._segments_url = segments_manager_url
        self._segments_client = segments_client
        self._type_override = type_override
        self._name_override = name_override
        self._network = (network or "").strip() or None
        self._resolve = resolver
        self._read_dns = dns_reader
        self._errors: list[CollectorError] = []
        self._raw_nodes: list[dict] = []

    def _step(self, name: str, fn: Callable[[], T], default: T) -> T:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one bad step must not sink the report
            logger.warning("collector step %s failed: %s", name, exc)
            self._errors.append(CollectorError(collector=name, error=str(exc)[:300]))
            return default

    def collect(self) -> ClusterReport:
        self._errors = []
        self._raw_nodes = []

        cluster_version = self._kube.get(f"{CONFIG_API}/clusterversions/version")
        if cluster_version is None:
            raise CollectionError("ClusterVersion 'version' not found: is this an OpenShift cluster?")
        cluster_id = (cluster_version.get("spec") or {}).get("clusterID")
        if not cluster_id:
            raise CollectionError("ClusterVersion has no spec.clusterID")

        infra = self._step("infrastructure", lambda: self._kube.get(f"{CONFIG_API}/infrastructures/cluster"), None) or {}
        infra_status = infra.get("status") or {}
        platform = (infra_status.get("platformStatus") or {}).get("type") or infra_status.get("platform")
        api_url = infra_status.get("apiServerURL")

        name, base_domain = self._name_and_domain()

        apps_domain = self._step("ingress", self._apps_domain, None)
        console_url = self._step("console", self._console_url, None)
        if not console_url and apps_domain:
            console_url = f"https://console-openshift-console.{apps_domain}"

        has_mce = self._step("multiClusterEngine", self._has_multicluster_engine, False)
        has_hco = self._step("hyperConverged", self._has_hyperconverged, False)
        cluster_type, detection = detect_type(
            control_plane_topology=infra_status.get("controlPlaneTopology"),
            has_multicluster_engine=has_mce,
            has_hyperconverged=has_hco,
            platform=platform,
            override=self._type_override,
        )

        nodes = self._step("nodes", self._nodes, [])
        router_lb = self._step("routerLb", lambda: self._resolve_url(console_url), [])
        addresses = [node.internal_ip for node in nodes if node.internal_ip] + router_lb
        site, segments = self._step("segments", lambda: self._segments(name, addresses), (None, []))

        return ClusterReport(
            cluster_id=cluster_id,
            name=name,
            base_domain=base_domain,
            type=cluster_type,
            detection=detection,
            openshift_version=_openshift_version(cluster_version),
            kubernetes_version=self._step("kubernetesVersion", self._kubernetes_version, None),
            console_url=console_url,
            api_url=api_url,
            router_lb=router_lb,
            api_addresses=self._step("apiAddresses", lambda: self._resolve_url(api_url), []),
            network=self._network,
            site=site,
            segments=segments,
            dns=self._step("dns", self._read_dns, None),
            nodes=nodes,
            resources=_total_resources(self._raw_nodes) if self._raw_nodes else None,
            storage_classes=self._step("storageClasses", self._storage_classes, []),
            identity_providers=self._step("identityProviders", self._identity_providers, []),
            hosted_clusters=self._step("hostedClusters", self._hosted_clusters, []) if has_mce else [],
            errors=self._errors,
            collector_version=__version__,
            collected_at=datetime.now(UTC),
        )

    # --- identity -----------------------------------------------------------

    def _name_and_domain(self) -> tuple[str, str | None]:
        dns = self._step("dnsConfig", lambda: self._kube.get(f"{CONFIG_API}/dnses/cluster"), None) or {}
        cluster_domain = ((dns.get("spec") or {}).get("baseDomain") or "").strip(".")
        derived_name, _, base_domain = cluster_domain.partition(".")
        name = (self._name_override or derived_name).strip().lower()
        if not name:
            raise CollectionError(
                "cannot work out the cluster name: DNS 'cluster' has no spec.baseDomain. "
                "Set CLUSTER_NAME to supply it."
            )
        return name, base_domain or None

    def _apps_domain(self) -> str | None:
        ingress = self._kube.get(f"{CONFIG_API}/ingresses/cluster") or {}
        return (ingress.get("spec") or {}).get("domain")

    def _console_url(self) -> str | None:
        console = self._kube.get(f"{CONFIG_API}/consoles/cluster") or {}
        return (console.get("status") or {}).get("consoleURL")

    def _kubernetes_version(self) -> str | None:
        return (self._kube.get("/version") or {}).get("gitVersion")

    def _resolve_url(self, url: str | None) -> list[str]:
        host = urlparse(url).hostname if url else None
        return self._resolve(host) if host else []

    # --- segments -----------------------------------------------------------

    def _segments(self, name: str, addresses: list[str]) -> tuple[str | None, list[SegmentReport]]:
        if not self._segments_url or self._segments_client is None:
            return None, []
        return fetch_segments(self._segments_client, self._segments_url, name, addresses)

    # --- type signals -------------------------------------------------------

    def _has_multicluster_engine(self) -> bool:
        return bool(self._kube.list("/apis/multicluster.openshift.io/v1/multiclusterengines"))

    def _has_hyperconverged(self) -> bool:
        return bool(self._kube.list("/apis/hco.kubevirt.io/v1beta1/hyperconvergeds"))

    # --- inventory ----------------------------------------------------------

    def _nodes(self) -> list[NodeReport]:
        self._raw_nodes = self._kube.list("/api/v1/nodes")
        return sorted((_node_report(node) for node in self._raw_nodes), key=lambda n: n.name)

    def _storage_classes(self) -> list[StorageClass]:
        classes = []
        for item in self._kube.list("/apis/storage.k8s.io/v1/storageclasses"):
            metadata = item.get("metadata") or {}
            annotations = metadata.get("annotations") or {}
            classes.append(
                StorageClass(
                    name=metadata.get("name", ""),
                    provisioner=item.get("provisioner", ""),
                    is_default=annotations.get(DEFAULT_CLASS_ANNOTATION) == "true",
                )
            )
        return sorted(classes, key=lambda c: c.name)

    def _identity_providers(self) -> list[str]:
        oauth = self._kube.get(f"{CONFIG_API}/oauths/cluster") or {}
        providers = (oauth.get("spec") or {}).get("identityProviders") or []
        return sorted(p["name"] for p in providers if p.get("name"))

    def _hosted_clusters(self) -> list[HostedClusterRef]:
        pools: dict[tuple[str, str], tuple[int, int]] = {}
        for pool in self._kube.list("/apis/hypershift.openshift.io/v1beta1/nodepools"):
            spec = pool.get("spec") or {}
            key = ((pool.get("metadata") or {}).get("namespace", ""), spec.get("clusterName", ""))
            count, replicas = pools.get(key, (0, 0))
            pools[key] = (count + 1, replicas + int(spec.get("replicas") or 0))

        hosted = []
        for item in self._kube.list("/apis/hypershift.openshift.io/v1beta1/hostedclusters"):
            metadata = item.get("metadata") or {}
            spec = item.get("spec") or {}
            name = metadata.get("name", "")
            namespace = metadata.get("namespace", "")
            history = ((item.get("status") or {}).get("version") or {}).get("history") or []
            oauth = (spec.get("configuration") or {}).get("oauth") or {}
            count, replicas = pools.get((namespace, name), (0, 0))
            hosted.append(
                HostedClusterRef(
                    name=name,
                    namespace=namespace,
                    version=history[0].get("version") if history else None,
                    platform=(spec.get("platform") or {}).get("type"),
                    node_pools=count,
                    replicas=replicas,
                    identity_providers=sorted(
                        p["name"] for p in oauth.get("identityProviders") or [] if p.get("name")
                    ),
                )
            )
        return sorted(hosted, key=lambda h: h.name)


def _openshift_version(cluster_version: dict) -> str | None:
    """The version the cluster actually runs: the newest completed update."""
    status = cluster_version.get("status") or {}
    for entry in status.get("history") or []:
        if entry.get("state") == "Completed" and entry.get("version"):
            return entry["version"]
    return (status.get("desired") or {}).get("version")


def _node_report(node: dict) -> NodeReport:
    metadata = node.get("metadata") or {}
    status = node.get("status") or {}
    labels = metadata.get("labels") or {}
    # Addresses are looked up by type. Their order is not guaranteed.
    addresses = {a.get("type"): a.get("address") for a in status.get("addresses") or []}
    conditions = {c.get("type"): c.get("status") for c in status.get("conditions") or []}
    node_info = status.get("nodeInfo") or {}
    capacity = status.get("capacity") or {}
    return NodeReport(
        name=metadata.get("name", ""),
        roles=sorted(k[len(ROLE_LABEL_PREFIX):] for k in labels if k.startswith(ROLE_LABEL_PREFIX)),
        internal_ip=addresses.get("InternalIP"),
        hostname=addresses.get("Hostname"),
        ready=conditions.get("Ready") == "True",
        kubelet_version=node_info.get("kubeletVersion"),
        os_image=node_info.get("osImage"),
        cpu=int(parse_quantity(capacity.get("cpu"))),
        memory_gi=to_gi(capacity.get("memory")),
    )


def _total_resources(nodes: list[dict]) -> Resources:
    cpu = memory = pods = storage = gpu = 0.0
    for node in nodes:
        status = node.get("status") or {}
        capacity = status.get("capacity") or {}
        allocatable = status.get("allocatable") or {}
        cpu += parse_quantity(capacity.get("cpu"))
        memory += parse_quantity(capacity.get("memory"))
        storage += parse_quantity(capacity.get("ephemeral-storage"))
        pods += parse_quantity(allocatable.get("pods"))
        gpu += parse_quantity(capacity.get(GPU_RESOURCE))
    return Resources(
        cpu=int(cpu),
        memory_gi=round(memory / 2**30, 1),
        pods=int(pods),
        ephemeral_storage_gi=round(storage / 2**30, 1),
        gpu=int(gpu),
    )
