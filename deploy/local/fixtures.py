"""Fake data for the local stack: one description of a small fleet.

The mock Segments Manager and the seed script both read it, so the two
sources line up the way they would in a real environment.
"""

SITES = ["site1", "site2", "site3"]
DOMAIN = "lab.example.com"

# name, site, third octet of its segment, version, workers, extras
MCES = [
    ("ocp4-prod-mce-site1-a", "site1", 1, "4.16.21", 3, {}),
    ("ocp4-prep-mce-site1-a", "site1", 4, "4.17.9", 3, {}),
    ("ocp4-prod-mce-site2-a", "site2", 1, "4.16.21", 3, {}),
    # Has segments in Segments Manager, but no collector, so it does not appear in the platform.
    ("ocp4-prod-mce-site3-a", "site3", 1, None, 0, {"report": False}),
]

# name, site, parent MCE, octet, version, workers, extras
HOSTED = [
    ("ocp4-prod-tomer-site1-a", "site1", "ocp4-prod-mce-site1-a", 20, "4.16.18", 4, {}),
    ("ocp4-prod-payments-site1-a", "site1", "ocp4-prod-mce-site1-a", 21, "4.16.18", 6, {}),
    ("ocp4-prod-data-site1-a", "site1", "ocp4-prod-mce-site1-a", 22, "4.16.21", 8, {"gpu": 4}),
    ("ocp4-prep-tomer-site1-a", "site1", "ocp4-prep-mce-site1-a", 40, "4.17.9", 2, {}),
    ("ocp4-prep-ml-site1-a", "site1", "ocp4-prep-mce-site1-a", 41, "4.17.9", 3, {"gpu": 2}),
    ("ocp4-prod-web-site2-a", "site2", "ocp4-prod-mce-site2-a", 20, "4.16.18", 5, {}),
    # The collector stopped reporting two days ago.
    ("ocp4-prod-search-site2-a", "site2", "ocp4-prod-mce-site2-a", 21, "4.15.38", 3, {"age_hours": 50}),
    ("ocp4-prod-iot-site2-a", "site2", "ocp4-prod-mce-site2-a", 22, "4.16.18", 2, {}),
    # Freshly created, no collector yet: it does not appear as a cluster. Its MCE's
    # hosted-cluster table (admin only) lists it as not reporting.
    ("ocp4-prod-new-site2-a", "site2", "ocp4-prod-mce-site2-a", 23, "4.17.6", 2, {"report": False}),
    # Hosted clusters that run OpenShift Virtualization.
    ("ocp4-prod-kubevirt-site1-a", "site1", "ocp4-prod-mce-site1-a", 30, "4.18.4", 6, {"kubevirt": True}),
    ("ocp4-prod-kubevirt-site2-a", "site2", "ocp4-prod-mce-site2-a", 30, "4.18.4", 6, {"kubevirt": True}),
]

# name, site, octet, version, workers, extras
UPI = [
    ("ocp4-prod-core-site1", "site1", 60, "4.16.21", 9, {}),
    ("ocp4-prod-dmz-site2", "site2", 60, "4.16.21", 6, {}),
    ("ocp4-prod-legacy-site3", "site3", 60, "4.14.42", 12, {}),
    ("ocp4-dev-lab-site3", "site3", 61, "4.18.4", 3, {}),
    # Single node, collector stopped a day ago.
    ("ocp4-edge-sno-site3", "site3", 62, "4.15.38", 0, {"age_hours": 26, "masters": 1}),
    # Reporting, but nobody allocated it a segment in Segments Manager.
    ("ocp4-dev-sandbox-site1", "site1", 63, "4.18.4", 2, {"segment": False}),
    # In Segments Manager only: does not appear.
    ("ocp4-prod-billing-site2", "site2", 61, None, 0, {"report": False}),
]

SITE_PREFIX = {"site1": "192.10", "site2": "193.51", "site3": "194.52"}


def network(site: str, octet: int) -> str:
    return f"{SITE_PREFIX[site]}.{octet}"


def sm_segment(cluster: str, site: str, octet: int, seg_type: str) -> dict:
    return {
        "site": site,
        "vlan_id": 100 + octet,
        "epg_name": f"EPG_{site.upper()}_{100 + octet}",
        "segment": f"{network(site, octet)}.0/24",
        "dhcp": seg_type in ("HC", "PXE"),
        "cluster_name": cluster,
        "type": seg_type,
        "status": "Allocated",
        "allocated_at": "2026-08-14T09:30:00Z",
    }


def segments() -> list[dict]:
    """Every allocated segment the mock Segments Manager knows."""
    result = []
    for name, site, octet, *_ in MCES:
        result.append(sm_segment(name, site, octet, "MCE"))
        result.append(sm_segment(name, site, octet + 1, "INVENTORY"))
        result.append(sm_segment(name, site, octet + 2, "PXE"))
    for name, site, _mce, octet, *_ in HOSTED:
        result.append(sm_segment(name, site, octet, "HC"))
    for name, site, octet, _version, _workers, extras in UPI:
        if extras.get("segment", True):
            result.append(sm_segment(name, site, octet, "UPI"))
    return result
