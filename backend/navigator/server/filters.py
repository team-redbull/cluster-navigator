"""Filtering of the cluster list. Runs on the server so API callers get it too."""

import ipaddress
from dataclasses import dataclass

from navigator.server.merge import MergedCluster


@dataclass(frozen=True)
class Filters:
    q: str | None = None
    site: str | None = None
    network: str | None = None
    mce: str | None = None
    segment: str | None = None
    version: str | None = None
    status: str | None = None


def minor_version(version: str | None) -> str | None:
    """'4.16.21' -> '4.16'."""
    if not version:
        return None
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def _addresses(cluster: MergedCluster) -> list[str]:
    addresses = list(cluster.card.router_lb)
    addresses += cluster.report.api_addresses
    addresses += [node.internal_ip for node in cluster.report.nodes if node.internal_ip]
    return addresses


def segment_matches(needle: str, cluster: MergedCluster) -> bool:
    """Match a cluster by its segments and addresses.

    * an IP address matches the cluster whose segment contains it, or that
      uses it as a router, API or node address
    * a CIDR matches any cluster with an overlapping segment
    * anything else is a plain text match on the segments and addresses
    """
    needle = needle.strip()
    if not needle:
        return True
    cidrs = [segment.cidr for segment in cluster.segments]

    try:
        ip = ipaddress.ip_address(needle)
    except ValueError:
        ip = None
    if ip is not None:
        if needle in _addresses(cluster):
            return True
        return any(_in_network(ip, cidr) for cidr in cidrs)

    if "/" in needle:
        try:
            wanted = ipaddress.ip_network(needle, strict=False)
        except ValueError:
            wanted = None
        if wanted is not None:
            return any(_overlaps(wanted, cidr) for cidr in cidrs)

    return any(needle in value for value in cidrs + _addresses(cluster))


def _in_network(ip, cidr: str) -> bool:
    try:
        return ip in ipaddress.ip_network(cidr, strict=False)
    except (ValueError, TypeError):
        return False


def _overlaps(wanted, cidr: str) -> bool:
    try:
        return wanted.overlaps(ipaddress.ip_network(cidr, strict=False))
    except (ValueError, TypeError):
        return False


def matches(cluster: MergedCluster, filters: Filters) -> bool:
    card = cluster.card
    if filters.q and filters.q.strip().lower() not in card.name.lower():
        return False
    if filters.site and card.site != filters.site:
        return False
    if filters.network and card.network != filters.network:
        return False
    if filters.mce and card.mce != filters.mce:
        return False
    if filters.version and minor_version(card.openshift_version) != filters.version:
        return False
    if filters.status and card.status.value != filters.status:
        return False
    if filters.segment and not segment_matches(filters.segment, cluster):
        return False
    return True
