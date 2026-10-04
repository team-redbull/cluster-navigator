import httpx
import pytest

from navigator.collector.collect import CollectionError, Collector
from navigator.collector.detect import detect_type
from navigator.collector.push import PushError, push
from navigator.collector.quantity import parse_quantity, to_gi
from navigator.collector.resolvconf import parse_resolv_conf
from navigator.collector.segments import fetch_segments
from navigator.models import ClusterType, DnsConfig
from tests import kube_fixtures as fx

RESOLVED = {"192.10.5.100"}


def collect(api, **kwargs):
    return Collector(
        fx.kube_client(api, forbidden=kwargs.pop("forbidden", ())),
        resolver=lambda host: sorted(RESOLVED),
        dns_reader=lambda: DnsConfig(servers=["10.50.1.5"], search_domains=["example.com"]),
        **kwargs,
    ).collect()


# --- type detection ----------------------------------------------------------


@pytest.mark.parametrize(
    ("topology", "mce", "hco", "expected"),
    [
        ("HighlyAvailable", False, False, ClusterType.GENERIC),
        ("SingleReplica", False, False, ClusterType.GENERIC),
        ("External", False, False, ClusterType.CLICK),
        ("External", False, True, ClusterType.KUBEVIRT),
        ("HighlyAvailable", False, True, ClusterType.KUBEVIRT),
        ("HighlyAvailable", True, False, ClusterType.MCE),
        # An MCE that also runs virtualization is still an MCE.
        ("HighlyAvailable", True, True, ClusterType.MCE),
        (None, False, False, ClusterType.GENERIC),
    ],
)
def test_detect_type(topology, mce, hco, expected):
    cluster_type, detection = detect_type(
        control_plane_topology=topology, has_multicluster_engine=mce, has_hyperconverged=hco
    )
    assert cluster_type == expected
    assert detection.source == "auto"


def test_override_beats_detection():
    cluster_type, detection = detect_type(
        control_plane_topology="External", has_multicluster_engine=True, has_hyperconverged=True, override="Generic"
    )
    assert cluster_type == ClusterType.GENERIC
    assert detection.source == "override"
    # The signals are still recorded, so the override can be questioned later.
    assert detection.signals["multiClusterEngine"] is True


def test_override_auto_means_detect():
    cluster_type, detection = detect_type(
        control_plane_topology="External", has_multicluster_engine=False, has_hyperconverged=False, override="auto"
    )
    assert cluster_type == ClusterType.CLICK
    assert detection.source == "auto"


def test_unknown_override_is_rejected():
    with pytest.raises(ValueError):
        detect_type(
            control_plane_topology=None, has_multicluster_engine=False, has_hyperconverged=False, override="hub"
        )


# --- collection --------------------------------------------------------------


def test_standalone_cluster():
    report = collect(fx.standalone())
    assert report.type == ClusterType.GENERIC
    assert report.name == "ocp4-prod-core-site1"
    assert report.base_domain == "example.com"
    assert report.cluster_id == "11111111-2222-3333-4444-555555555555"
    # The running version is the last completed update, not the one in progress.
    assert report.openshift_version == "4.16.21"
    assert report.kubernetes_version == "v1.29.10+abc"
    assert report.console_url == "https://console-openshift-console.apps.ocp4-prod-core-site1.example.com"
    assert report.router_lb == ["192.10.5.100"]
    assert report.identity_providers == ["htpasswd", "ldap"]
    assert report.dns.servers == ["10.50.1.5"]
    assert [s.name for s in report.storage_classes if s.is_default] == ["ceph-rbd"]
    assert report.errors == []


def test_node_addresses_are_read_by_type_not_position():
    report = collect(fx.standalone())
    master = next(n for n in report.nodes if n.name == "master-0")
    assert master.internal_ip == "192.10.5.11"
    assert master.hostname == "master-0"
    assert master.roles == ["control-plane", "master"]
    assert master.ready is True
    assert report.resources.cpu == 32
    assert report.resources.pods == 500


def test_hosted_cluster_is_click():
    report = collect(fx.hosted())
    assert report.type == ClusterType.CLICK
    assert report.detection.signals["controlPlaneTopology"] == "External"
    assert report.hosted_clusters == []


def test_hosted_cluster_with_virtualization_is_kubevirt():
    api = fx.hosted("ocp4-prod-kubevirt-site1-a")
    api["/apis/hco.kubevirt.io/v1beta1/hyperconvergeds"] = {"items": [{"metadata": {"name": "kubevirt-hyperconverged"}}]}
    assert collect(api).type == ClusterType.KUBEVIRT


def test_mce_reports_the_clusters_it_hosts():
    report = collect(fx.mce())
    assert report.type == ClusterType.MCE
    (hosted,) = report.hosted_clusters
    assert hosted.name == "ocp4-prod-tomer-site1-a"
    assert hosted.version == "4.16.18"
    assert hosted.platform == "Agent"
    assert (hosted.node_pools, hosted.replicas) == (2, 5)
    assert hosted.identity_providers == ["corp-ldap"]


def test_a_failing_step_is_recorded_and_the_rest_is_sent():
    report = collect(fx.standalone(), forbidden=("/apis/storage.k8s.io/v1/storageclasses",))
    assert report.storage_classes == []
    assert [e.collector for e in report.errors] == ["storageClasses"]
    assert len(report.nodes) == 2


def test_missing_optional_apis_are_not_errors():
    # No MCE, HyperShift or virtualization CRDs: every one of them answers 404.
    report = collect(fx.standalone())
    assert report.errors == []


def test_name_can_be_overridden():
    assert collect(fx.standalone(), name_override="Custom-Name").name == "custom-name"


def test_network_is_what_the_chart_sets():
    assert collect(fx.standalone(), network=" prod-net ").network == "prod-net"
    assert collect(fx.standalone(), network="").network is None
    assert collect(fx.standalone()).network is None


def test_not_openshift_fails_loudly():
    with pytest.raises(CollectionError):
        collect({})


# --- segments ----------------------------------------------------------------


def sm_row(cluster, site, cidr, seg_type, status="Allocated") -> dict:
    return {"cluster_name": cluster, "site": site, "segment": cidr, "type": seg_type, "status": status,
            "vlan_id": 105, "epg_name": "EPG_105", "dhcp": False}


def segments_manager(rows, calls=None, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(status_code, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_segments_are_looked_up_by_cluster_name():
    calls = []
    rows = [
        sm_row("ocp4-prod-core-site1", "site1", "192.10.5.0/24", "UPI"),
        # The search matches parts of names. Only an exact name is ours.
        sm_row("ocp4-prod-core-site1-test", "site1", "192.10.9.0/24", "UPI"),
        sm_row("OCP4-PROD-CORE-SITE1", "site1", "192.10.6.0/24", "PXE"),
        sm_row("ocp4-prod-core-site1", "site1", "192.10.7.0/24", "UPI", status="Available"),
    ]
    site, segments = fetch_segments(segments_manager(rows, calls), "https://sm.example.com/", "ocp4-prod-core-site1", [])
    assert site == "site1"
    assert [(s.cidr, s.type, s.vlan_id) for s in segments] == [("192.10.5.0/24", "UPI", 105), ("192.10.6.0/24", "PXE", 105)]
    (request,) = calls
    assert request.url.path == "/api/segments/search"
    assert dict(request.url.params) == {"q": "ocp4-prod-core-site1", "status": "Allocated"}


def test_same_name_at_two_sites_is_told_apart_by_our_own_addresses():
    rows = [sm_row("dup", "site1", "192.10.5.0/24", "UPI"), sm_row("dup", "site2", "193.51.5.0/24", "UPI")]
    site, segments = fetch_segments(segments_manager(rows), "https://sm", "dup", ["193.51.5.11"])
    assert (site, [s.cidr for s in segments]) == ("site2", ["193.51.5.0/24"])


def test_no_segment_allocated_is_not_an_error():
    assert fetch_segments(segments_manager([]), "https://sm", "ocp4-new", []) == (None, [])


def test_collector_reports_its_segments():
    rows = [sm_row("ocp4-prod-core-site1", "site1", "192.10.5.0/24", "UPI")]
    report = collect(fx.standalone(), segments_manager_url="https://sm", segments_client=segments_manager(rows))
    assert (report.site, [s.cidr for s in report.segments]) == ("site1", ["192.10.5.0/24"])
    assert report.errors == []


def test_segments_manager_down_is_recorded_and_the_report_still_goes():
    report = collect(fx.standalone(), segments_manager_url="https://sm", segments_client=segments_manager([], status_code=503))
    assert report.segments == [] and [e.collector for e in report.errors] == ["segments"]
    assert len(report.nodes) == 2


def test_without_a_segments_manager_url_nothing_is_looked_up():
    report = collect(fx.standalone())
    assert report.segments == [] and report.errors == []


# --- helpers -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("64", 64), ("500m", 0.5), ("1Ki", 1024), ("2Gi", 2 * 2**30), ("3k", 3000), (None, 0), ("", 0), (8, 8)],
)
def test_parse_quantity(value, expected):
    assert parse_quantity(value) == expected


def test_to_gi():
    assert to_gi("65536000Ki") == 62.5


def test_parse_resolv_conf():
    config = parse_resolv_conf(
        "# generated\nsearch example.com lab.local\nnameserver 10.50.1.5\nnameserver 10.50.1.6 # secondary\noptions ndots:5\n"
    )
    assert config.servers == ["10.50.1.5", "10.50.1.6"]
    assert config.search_domains == ["example.com", "lab.local"]


# --- push --------------------------------------------------------------------


def _client(responses):
    calls = []

    def handler(request):
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_push_sends_token_and_camel_case_body():
    client, calls = _client([httpx.Response(202, json={})])
    push(collect(fx.standalone()), url="https://nav.example.com/", token="secret", client=client)
    (request,) = calls
    assert str(request.url) == "https://nav.example.com/api/v1/ingest/reports"
    assert request.headers["Authorization"] == "Bearer secret"
    assert b'"clusterId"' in request.content and b'"routerLb"' in request.content


def test_push_retries_server_errors():
    client, calls = _client([httpx.Response(503), httpx.Response(202, json={})])
    push(collect(fx.standalone()), url="https://nav", token="t", client=client, backoff=0)
    assert len(calls) == 2


def test_push_does_not_retry_a_refusal():
    client, calls = _client([httpx.Response(401, json={"detail": "Invalid ingest token"})])
    with pytest.raises(PushError, match="refused"):
        push(collect(fx.standalone()), url="https://nav", token="bad", client=client, backoff=0)
    assert len(calls) == 1
