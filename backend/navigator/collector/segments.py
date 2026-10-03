"""Looks up this cluster's segments in Segments Manager.

Segments Manager is the authority for which segments a cluster holds. Each
collector asks it about its own cluster only, once per run, and sends the
answer with the rest of its report. Nothing else in the platform talks to
Segments Manager.
"""

import ipaddress

import httpx

from navigator.models import SegmentReport

SEARCH_PATH = "/api/segments/search"
ALLOCATED = "Allocated"


def fetch_segments(
    client: httpx.Client, url: str, cluster_name: str, addresses: list[str]
) -> tuple[str | None, list[SegmentReport]]:
    """Return (site, segments) for ``cluster_name``.

    ``addresses`` are this cluster's node and router addresses. They are only
    used when the same cluster name exists at more than one site, to tell
    which site this cluster is at.
    """
    response = client.get(url.rstrip("/") + SEARCH_PATH, params={"q": cluster_name, "status": ALLOCATED})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of segments, got {type(payload).__name__}")

    wanted = cluster_name.strip().lower()
    by_site: dict[str, list[SegmentReport]] = {}
    for raw in payload:
        # The search matches parts of names, so "ocp4-a" also returns "ocp4-a-test".
        if str(raw.get("cluster_name") or "").strip().lower() != wanted:
            continue
        if raw.get("status", ALLOCATED) != ALLOCATED:
            continue
        site = str(raw.get("site") or "").strip()
        cidr = str(raw.get("segment") or "").strip()
        if not site or not cidr:
            continue
        segments = by_site.setdefault(site, [])
        if all(existing.cidr != cidr for existing in segments):
            segments.append(
                SegmentReport(
                    cidr=cidr,
                    site=site,
                    type=raw.get("type"),
                    vlan_id=raw.get("vlan_id"),
                    epg_name=raw.get("epg_name"),
                    dhcp=raw.get("dhcp"),
                )
            )

    if not by_site:
        return None, []
    site = _pick_site(by_site, addresses)
    return site, sorted(by_site[site], key=lambda segment: segment.cidr)


def _pick_site(by_site: dict[str, list[SegmentReport]], addresses: list[str]) -> str:
    """The same name can exist at two sites. Our own addresses say which one we are."""
    sites = sorted(by_site)
    if len(sites) == 1:
        return sites[0]
    for site in sites:
        if _contains_any(by_site[site], addresses):
            return site
    return sites[0]


def _contains_any(segments: list[SegmentReport], addresses: list[str]) -> bool:
    networks = []
    for segment in segments:
        try:
            networks.append(ipaddress.ip_network(segment.cidr, strict=False))
        except ValueError:
            continue
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if any(ip in network for network in networks):
            return True
    return False
