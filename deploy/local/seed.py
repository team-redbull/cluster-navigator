"""Plays the part of every collector in the fake fleet.

Builds one report per cluster, looks up that cluster's segments in (the mock)
Segments Manager with the collector's own code, and sends the report through
the real ingest endpoint with the collector's own push code. So the local
stack exercises the same path a real cluster does. The only shortcut is at
the end: a few reports are
back-dated in MongoDB to show what a stale cluster looks like, because the
server (rightly) stamps arrival time itself.
"""

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from pymongo import MongoClient

import fixtures
from navigator.collector.push import push
from navigator.collector.segments import fetch_segments
from navigator.models import (
    ClusterReport,
    ClusterType,
    CollectorError,
    Detection,
    DnsConfig,
    HostedClusterRef,
    NodeReport,
    Resources,
    StorageClass,
)

URL = os.environ.get("NAVIGATOR_URL", "http://navigator:8080")
TOKEN = os.environ.get("INGEST_TOKEN", "local-ingest-token")
SEGMENTS_MANAGER_URL = os.environ.get("SEGMENTS_MANAGER_URL", "http://segments-manager:8000")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
DB_NAME = os.environ.get("DB_NAME", "cluster-navigator")

KUBELET = {"4.14": "v1.27.16", "4.15": "v1.28.15", "4.16": "v1.29.10", "4.17": "v1.30.7", "4.18": "v1.31.5"}
RHCOS = {"4.14": "414.92", "4.15": "415.92", "4.16": "416.94", "4.17": "417.94", "4.18": "418.94"}
CEPH = [
    StorageClass(name="ocs-storagecluster-ceph-rbd", provisioner="openshift-storage.rbd.csi.ceph.com", is_default=True),
    StorageClass(name="ocs-storagecluster-cephfs", provisioner="openshift-storage.cephfs.csi.ceph.com"),
]
NETAPP = [StorageClass(name="trident-nas", provisioner="csi.trident.netapp.io", is_default=True)]
LVM = [StorageClass(name="lvms-vg1", provisioner="topolvm.io", is_default=True)]


def build(
    name: str,
    site: str,
    octet: int,
    version: str,
    cluster_type: ClusterType,
    *,
    masters: int,
    workers: int,
    hosted: bool,
    extras: dict,
    hosted_clusters: list[HostedClusterRef] | None = None,
) -> ClusterReport:
    net = fixtures.network(site, octet)
    minor = ".".join(version.split(".")[:2])
    fqdn = f"{name}.{fixtures.DOMAIN}"
    worker_cpu, worker_mem = (96, 503.5) if extras.get("gpu") else (48, 251.6)

    nodes = [
        NodeReport(
            name=f"master-{i}.{fqdn}", roles=["control-plane", "master"], internal_ip=f"{net}.{11 + i}",
            hostname=f"master-{i}.{fqdn}", ready=True, kubelet_version=KUBELET[minor],
            os_image=f"Red Hat Enterprise Linux CoreOS {RHCOS[minor]}", cpu=16, memory_gi=62.5,
        )
        for i in range(masters)
    ] + [
        NodeReport(
            name=f"worker-{i}.{fqdn}", roles=["worker"], internal_ip=f"{net}.{21 + i}",
            hostname=f"worker-{i}.{fqdn}", ready=not (extras.get("degraded") and i == 0),
            kubelet_version=KUBELET[minor], os_image=f"Red Hat Enterprise Linux CoreOS {RHCOS[minor]}",
            cpu=worker_cpu, memory_gi=worker_mem,
        )
        for i in range(workers)
    ]
    errors = []
    if not extras.get("segment", True):
        errors.append(CollectorError(collector="apiAddresses", error="[Errno -2] Name or service not known"))

    return ClusterReport(
        cluster_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, fqdn)),
        name=name,
        base_domain=fixtures.DOMAIN,
        type=cluster_type,
        detection=Detection(
            source="auto",
            signals={
                "controlPlaneTopology": "External" if hosted else ("SingleReplica" if masters == 1 else "HighlyAvailable"),
                "multiClusterEngine": cluster_type == ClusterType.MCE,
                "hyperConverged": cluster_type == ClusterType.KUBEVIRT,
                "platform": "None",
            },
        ),
        openshift_version=version,
        kubernetes_version=f"{KUBELET[minor]}+{uuid.uuid5(uuid.NAMESPACE_DNS, version).hex[:7]}",
        console_url=f"https://console-openshift-console.apps.{fqdn}",
        api_url=f"https://api.{fqdn}:6443",
        router_lb=[f"{net}.100"],
        api_addresses=[] if errors else [f"{net}.101"],
        dns=DnsConfig(servers=["10.50.1.5", "10.50.1.6"], search_domains=[fqdn, fixtures.DOMAIN]),
        nodes=nodes,
        resources=Resources(
            cpu=sum(n.cpu for n in nodes),
            memory_gi=round(sum(n.memory_gi for n in nodes), 1),
            pods=250 * len(nodes),
            ephemeral_storage_gi=round(446.6 * len(nodes), 1),
            gpu=extras.get("gpu", 0),
        ),
        storage_classes=LVM if masters == 1 else (NETAPP if site == "site3" else CEPH),
        # A hosted cluster's identity providers are set on its MCE, not inside it.
        identity_providers=[] if hosted else ["corp-ldap", "htpasswd-breakglass"],
        hosted_clusters=hosted_clusters or [],
        errors=errors,
        collector_version="0.1.0",
        collected_at=datetime.now(UTC),
    )


def fleet() -> list[tuple[ClusterReport, float]]:
    """Every report to send, with how many hours ago it should appear to have arrived."""
    reports = []
    for name, site, octet, version, workers, extras in fixtures.MCES:
        if not extras.get("report", True):
            continue
        hosted = [
            HostedClusterRef(
                name=h_name, namespace="clusters", version=h_version, platform="Agent",
                node_pools=1 if h_workers <= 4 else 2, replicas=h_workers, identity_providers=["corp-ldap"],
            )
            for h_name, _site, mce, _octet, h_version, h_workers, _extras in fixtures.HOSTED
            if mce == name
        ]
        report = build(name, site, octet, version, ClusterType.MCE, masters=3, workers=workers,
                       hosted=False, extras=extras, hosted_clusters=hosted)
        reports.append((report, extras.get("age_hours", 0)))

    for name, site, _mce, octet, version, workers, extras in fixtures.HOSTED:
        if not extras.get("report", True):
            continue
        cluster_type = ClusterType.KUBEVIRT if extras.get("kubevirt") else ClusterType.CLICK
        report = build(name, site, octet, version, cluster_type, masters=0, workers=workers, hosted=True, extras=extras)
        reports.append((report, extras.get("age_hours", 0)))

    for name, site, octet, version, workers, extras in fixtures.UPI:
        if not extras.get("report", True):
            continue
        report = build(name, site, octet, version, ClusterType.GENERIC, masters=extras.get("masters", 3),
                       workers=workers, hosted=False, extras=extras)
        reports.append((report, extras.get("age_hours", 0)))
    return reports


def wait_for_server() -> None:
    for _ in range(60):
        try:
            if httpx.get(f"{URL}/healthz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    sys.exit(f"server at {URL} did not become healthy")


def main() -> None:
    wait_for_server()
    reports = fleet()
    with httpx.Client(timeout=10) as segments_manager:
        for report, _ in reports:
            addresses = [node.internal_ip for node in report.nodes] + report.router_lb
            report.site, report.segments = fetch_segments(
                segments_manager, SEGMENTS_MANAGER_URL, report.name, addresses
            )
            push(report, url=URL, token=TOKEN, backoff=1)

    aged = [(report, hours) for report, hours in reports if hours]
    if aged:
        collection = MongoClient(MONGO_URI)[DB_NAME]["reports"]
        for report, hours in aged:
            collection.update_one(
                {"_id": report.cluster_id},
                {"$set": {"receivedAt": datetime.now(UTC) - timedelta(hours=hours)}},
            )
    print(f"seeded {len(reports)} cluster reports ({len(aged)} back-dated to look stale)", flush=True)


if __name__ == "__main__":
    main()
