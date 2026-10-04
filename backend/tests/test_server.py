import asyncio
import base64
import csv
import io
import json
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from navigator.models import (
    ClusterReport,
    ClusterType,
    CollectorError,
    Detection,
    HostedClusterRef,
    NodeReport,
    SegmentReport,
)
from navigator.server import policy
from navigator.server.app import create_app
from navigator.server.auth import build_provider
from navigator.server.auth.openshift import OpenShiftProvider, trust
from navigator.server.export import clusters_csv
from navigator.server.filters import segment_matches
from navigator.server.merge import MergedCluster, MergeOptions, merge
from navigator.server.settings import Settings, json_list
from navigator.server.store import MemoryStore, StoredReport
from navigator.server.views import ClusterCard, ClusterStatus

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
INGEST = {"Authorization": "Bearer ingest-secret"}


def report(name, cluster_type=ClusterType.GENERIC, *, cluster_id=None, **kwargs) -> ClusterReport:
    return ClusterReport(
        cluster_id=cluster_id or f"id-{name}",
        name=name,
        base_domain="example.com",
        type=cluster_type,
        openshift_version=kwargs.pop("version", "4.16.21"),
        collected_at=NOW,
        **kwargs,
    )


def stored(rep, age_minutes=5) -> StoredReport:
    return StoredReport(report=rep, received_at=NOW - timedelta(minutes=age_minutes))


def seg(cidr, seg_type, site="site1", vlan=100) -> SegmentReport:
    return SegmentReport(cidr=cidr, site=site, type=seg_type, vlan_id=vlan, epg_name=f"EPG_{vlan}")


def reports():
    return [
        stored(report(
            "ocp4-prod-core-site1", site="site1", network="prod-net", segments=[seg("192.10.5.0/24", "UPI", vlan=105)],
            router_lb=["192.10.5.100"], nodes=[NodeReport(name="master-0", internal_ip="192.10.5.11")],
            console_url="https://console-openshift-console.apps.ocp4-prod-core-site1.example.com",
        )),
        stored(report(
            "ocp4-prod-tomer-site1-a", ClusterType.CLICK, version=None,
            site="site1", segments=[seg("192.10.20.0/24", "HC", vlan=120)],
        )),
        stored(report(
            "ocp4-prod-mce-site1-a", ClusterType.MCE, site="site1",
            segments=[seg("192.10.1.0/24", "MCE", vlan=101), seg("192.10.2.0/24", "INVENTORY", vlan=102)],
            hosted_clusters=[
                HostedClusterRef(name="ocp4-prod-tomer-site1-a", version="4.16.18", identity_providers=["corp-ldap"]),
                HostedClusterRef(name="ocp4-prod-ghost-site1-a", version="4.17.2"),
            ],
        )),
        # No segment was found for this one, and its last report is old.
        stored(report("ocp4-prod-kubevirt-site1-a", ClusterType.KUBEVIRT), age_minutes=600),
    ]


def merged() -> dict[str, MergedCluster]:
    return {c.card.name: c for c in merge(reports(), now=NOW)}


# --- merge -------------------------------------------------------------------


def test_segments_and_site_come_from_the_report():
    card = merged()["ocp4-prod-core-site1"].card
    assert (card.site, card.segments, card.status) == ("site1", ["192.10.5.0/24"], ClusterStatus.REPORTING)
    assert card.router_lb == ["192.10.5.100"]


def test_network_comes_from_the_report():
    cards = {name: c.card for name, c in merged().items()}
    assert cards["ocp4-prod-core-site1"].network == "prod-net"
    assert cards["ocp4-prod-tomer-site1-a"].network is None


def test_parent_mce_comes_from_the_mce_report():
    cluster = merged()["ocp4-prod-tomer-site1-a"]
    assert cluster.card.mce == "ocp4-prod-mce-site1-a"
    # Version and identity providers fall back to what the MCE knows.
    assert cluster.card.openshift_version == "4.16.18"
    assert cluster.identity_providers == ["corp-ldap"]


def test_kubevirt_cluster_is_hosted_only_when_its_control_plane_is():
    clusters = merged()
    # A Click Cluster always has a parent MCE.
    assert clusters["ocp4-prod-tomer-site1-a"].card.hosted is True
    # KubeVirt means OpenShift Virtualization is installed. This one is standalone.
    standalone = clusters["ocp4-prod-kubevirt-site1-a"].card
    assert (standalone.hosted, standalone.mce) == (False, None)
    assert clusters["ocp4-prod-core-site1"].card.hosted is False

    # A hosted KubeVirt cluster is known by its control plane, even while its MCE is not reporting.
    external = Detection(signals={"controlPlaneTopology": "External", "hyperConverged": True})
    alone = merge([stored(report("ocp4-prod-virt-site1-a", ClusterType.KUBEVIRT, detection=external))], now=NOW)[0]
    assert (alone.card.hosted, alone.card.mce) == (True, None)

    # And it names its MCE once that MCE lists it.
    hub = report("ocp4-prod-mce-site1-a", ClusterType.MCE, hosted_clusters=[HostedClusterRef(name="ocp4-prod-virt-site1-a")])
    both = {c.card.name: c.card for c in merge(
        [stored(hub), stored(report("ocp4-prod-virt-site1-a", ClusterType.KUBEVIRT, detection=external))], now=NOW
    )}
    assert both["ocp4-prod-virt-site1-a"].mce == "ocp4-prod-mce-site1-a"
    assert both["ocp4-prod-mce-site1-a"].hosted is False


def test_mce_card_shows_only_its_cluster_facing_segment():
    cluster = merged()["ocp4-prod-mce-site1-a"]
    assert cluster.card.segments == ["192.10.1.0/24"]
    assert len(cluster.segments) == 2
    assert cluster.card.mce is None


def test_only_clusters_that_reported_exist():
    # ocp4-prod-ghost-site1-a is listed by its MCE but has no collector of its own.
    assert "ocp4-prod-ghost-site1-a" not in merged()
    assert len(merged()) == len(reports())


def test_mce_knows_which_of_its_hosted_clusters_report():
    assert merged()["ocp4-prod-mce-site1-a"].hosted_reporting == {"ocp4-prod-tomer-site1-a"}


def test_old_report_is_stale_and_cluster_without_segment_has_no_site():
    cluster = merged()["ocp4-prod-kubevirt-site1-a"]
    assert cluster.card.status == ClusterStatus.STALE
    assert cluster.card.site is None and cluster.card.segments == []


def test_grafana_link_template():
    options = MergeOptions(grafana_url_template="https://grafana.{domain}/d/ocp?var-cluster={name}")
    cards = {c.card.name: c.card for c in merge(reports(), now=NOW, options=options)}
    assert cards["ocp4-prod-core-site1"].grafana_url == "https://grafana.example.com/d/ocp?var-cluster=ocp4-prod-core-site1"
    assert merged()["ocp4-prod-core-site1"].card.grafana_url is None


# --- filters -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("needle", "expected"),
    [
        ("192.10.5.77", True),  # an address inside the segment
        ("192.10.5.100", True),  # the router address itself
        ("192.10.6.1", False),
        ("192.10.0.0/16", True),  # an overlapping network
        ("193.51.0.0/16", False),
        ("192.10.5", True),  # plain text
        ("", True),
    ],
)
def test_segment_filter(needle, expected):
    assert segment_matches(needle, merged()["ocp4-prod-core-site1"]) is expected


# --- policy ------------------------------------------------------------------


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, ingest_token="ingest-secret", cookie_secure=False, **overrides)


def test_group_lists_are_json(monkeypatch):
    monkeypatch.setenv("ADMIN_GROUPS", '["ocp-admins", " platform-team "]')
    assert settings().admin_groups == ["ocp-admins", "platform-team"]
    monkeypatch.setenv("ADMIN_GROUPS", "")
    assert settings().admin_groups == []
    # The old comma-separated form is refused at startup, with the expected form in the message.
    monkeypatch.setenv("ADMIN_GROUPS", "ocp-admins,platform-team")
    with pytest.raises(ValueError, match="ADMIN_GROUPS must be a JSON list"):
        settings()
    with pytest.raises(ValueError, match="STORAGE_GROUPS must be a JSON list"):
        json_list("storage-team", "STORAGE_GROUPS")
    with pytest.raises(ValueError, match="of strings"):
        json_list('{"a": 1}', "STORAGE_GROUPS")


def test_openshift_is_the_default_and_says_what_to_do_outside_a_cluster(tmp_path):
    assert settings().auth_provider == "openshift"
    with pytest.raises(RuntimeError, match="set AUTH_PROVIDER=dev or none"):
        build_provider(settings(openshift_sa_dir=str(tmp_path)))


def test_anonymous_is_a_client():
    roles = policy.load_roles(settings(admin_groups=["ocp-admins"]), environ={})
    principal = policy.resolve(roles)
    assert principal.roles == ("client",)
    assert principal.cluster_types == {ClusterType.GENERIC, ClusterType.CLICK}
    assert principal.can_see_audience("public") and not principal.can_see_audience("admin")


def test_admin_group_grants_everything():
    roles = policy.load_roles(settings(admin_groups=["ocp-admins", "platform-team"]), environ={})
    principal = policy.resolve(roles, username="dana", groups=frozenset({"platform-team"}), via="session")
    assert principal.roles == ("admin", "client")
    assert principal.cluster_types == set(ClusterType)
    assert principal.can_see_audience("admin") and principal.can_see_audience("anything")


def test_signed_in_without_a_group_stays_a_client():
    roles = policy.load_roles(settings(admin_groups=["ocp-admins"]), environ={})
    principal = policy.resolve(roles, username="guest", groups=frozenset(), via="session")
    assert principal.roles == ("client",) and principal.authenticated


def test_a_new_role_is_configuration_only():
    roles = policy.load_roles(
        settings(admin_groups=["ocp-admins"], roles='{"storage": {"clusterTypes": ["*"], "audiences": ["public", "storage"]}}'),
        environ={"STORAGE_GROUPS": '["storage-team"]'},
    )
    assert policy.all_groups(roles) == {"ocp-admins", "storage-team"}
    principal = policy.resolve(roles, username="sam", groups=frozenset({"storage-team"}), via="session")
    assert principal.roles == ("client", "storage")
    assert ClusterType.MCE in principal.cluster_types
    assert principal.can_see_audience("storage") and not principal.can_see_audience("admin")


# --- API ---------------------------------------------------------------------

DEV_USERS = json.dumps({
    "admin": {"password": "admin-pw", "groups": ["ocp-admins"]},
    "guest": {"password": "guest-pw", "groups": []},
})


@pytest.fixture
def client():
    store = MemoryStore()
    app = create_app(
        settings(
            auth_provider="dev", admin_groups=["ocp-admins"], dev_users=DEV_USERS,
            service_tokens='{"workflows": {"token": "wf-token", "roles": ["admin"]}}',
            stale_after_seconds=10**9,
        ),
        store=store,
    )
    with TestClient(app) as test_client:
        for item in reports():
            body = item.report.model_dump(mode="json", by_alias=True)
            assert test_client.post("/api/v1/ingest/reports", json=body, headers=INGEST).status_code == 202
        yield test_client


def login(client, username="admin", password="admin-pw"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_ingest_needs_the_token(client):
    body = report("x").model_dump(mode="json", by_alias=True)
    assert client.post("/api/v1/ingest/reports", json=body).status_code == 401
    assert client.post("/api/v1/ingest/reports", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/api/v1/ingest/reports", json={"name": "x"}, headers=INGEST).status_code == 422


def test_client_sees_only_generic_and_click(client):
    me = client.get("/api/v1/me").json()
    assert me["authenticated"] is False and me["loginMode"] == "password"
    # Types the caller may not open are not listed at all, so the menu never shows them.
    assert [t["id"] for t in me["types"]] == ["generic", "click"]
    listing = client.get("/api/v1/clusters").json()
    assert {c["type"] for c in listing["items"]} == {"generic", "click"}
    assert set(listing["counts"]) == {"generic", "click"}
    assert client.get("/api/v1/clusters", params={"type": "mce"}).status_code == 403
    # A hidden cluster looks exactly like a missing one.
    assert client.get("/api/v1/clusters/id-ocp4-prod-mce-site1-a").status_code == 404
    assert client.get("/api/v1/clusters/does-not-exist").status_code == 404


def test_client_detail_has_no_admin_sections(client):
    detail = client.get("/api/v1/clusters/id-ocp4-prod-core-site1").json()
    assert {s["audience"] for s in detail["sections"]} == {"public"}


def test_client_is_not_told_the_parent_mce(client):
    mce = "ocp4-prod-mce-site1-a"
    listing = client.get("/api/v1/clusters", params={"type": "click"}).json()
    assert [c["mce"] for c in listing["items"]] == [None]
    assert listing["facets"]["mces"] == []
    # Filtering by an MCE's name must not reveal which clusters it hosts.
    assert client.get("/api/v1/clusters", params={"mce": mce}).json()["items"] == []
    # Nor is it anywhere in the details.
    assert mce not in client.get("/api/v1/clusters/id-ocp4-prod-tomer-site1-a").text

    login(client)
    detail = client.get("/api/v1/clusters/id-ocp4-prod-tomer-site1-a").json()
    assert detail["mce"] == mce
    overview = next(s for s in detail["sections"] if s["id"] == "overview")
    assert {"label": "Parent MCE", "value": mce, "mono": True} in overview["items"]


def test_csv_export_follows_the_list(client):
    def table(**params):
        response = client.get("/api/v1/clusters.csv", params=params)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        return response, list(csv.reader(io.StringIO(response.text)))

    # A client gets the clusters they may see, and no MCE column.
    response, rows = table()
    assert rows == [
        ["name", "version", "segment", "router_lb", "network"],
        ["ocp4-prod-core-site1", "4.16.21", "192.10.5.0/24", "192.10.5.100", "prod-net"],
        ["ocp4-prod-tomer-site1-a", "4.16.18", "192.10.20.0/24", "", ""],
    ]
    assert "mce" not in response.text
    assert 'filename="clusters-all-' in response.headers["content-disposition"]
    assert client.get("/api/v1/clusters.csv", params={"type": "mce"}).status_code == 403

    # An admin gets the MCE column, and the filters work as they do on the list.
    login(client)
    response, rows = table(type="click")
    assert rows == [
        ["name", "version", "segment", "router_lb", "network", "mce"],
        ["ocp4-prod-tomer-site1-a", "4.16.18", "192.10.20.0/24", "", "", "ocp4-prod-mce-site1-a"],
    ]
    assert 'filename="clusters-click-' in response.headers["content-disposition"]
    assert [row[0] for row in table(q="core")[1][1:]] == ["ocp4-prod-core-site1"]
    assert len(table()[1]) == 5


def test_csv_cells_cannot_run_as_formulas():
    card = ClusterCard(
        id="x", name="=cmd()", type=ClusterType.GENERIC, status=ClusterStatus.REPORTING,
        openshift_version="4.16.1", segments=["10.0.0.0/24", "10.0.1.0/24"], router_lb=["10.0.0.5"],
    )
    rows = list(csv.reader(io.StringIO(clusters_csv([card], include_mce=True))))
    assert rows[1] == ["'=cmd()", "4.16.1", "10.0.0.0/24; 10.0.1.0/24", "10.0.0.5", "", ""]


def test_admin_sees_everything(client):
    signed_in = login(client).json()
    assert signed_in["roles"] == ["admin", "client"]
    assert [t["id"] for t in signed_in["types"]] == ["generic", "click", "mce", "kubevirt"]
    listing = client.get("/api/v1/clusters").json()
    assert set(listing["counts"]) == {"generic", "click", "mce", "kubevirt"}
    mce = client.get("/api/v1/clusters/id-ocp4-prod-mce-site1-a").json()
    assert "hostedClusters" in {s["id"] for s in mce["sections"]}
    hosted = next(s for s in mce["sections"] if s["id"] == "hostedClusters")
    assert {row["name"]: row["reporting"] for row in hosted["rows"]} == {
        "ocp4-prod-tomer-site1-a": True, "ocp4-prod-ghost-site1-a": False,
    }
    assert client.get("/api/v1/status").status_code == 200


def test_wrong_password_and_groupless_user(client):
    assert login(client, password="wrong").status_code == 401
    assert login(client, username="nobody", password="x").status_code == 401
    assert login(client, "guest", "guest-pw").json()["roles"] == ["client"]
    assert client.get("/api/v1/clusters", params={"type": "mce"}).status_code == 403
    assert client.get("/api/v1/status").status_code == 403


def test_logout_drops_access(client):
    login(client)
    assert client.get("/api/v1/clusters", params={"type": "mce"}).status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/clusters", params={"type": "mce"}).status_code == 403


def test_forged_session_cookie_is_ignored(client):
    client.cookies.set("cn_session", "forged.value.here")
    assert client.get("/api/v1/me").json()["authenticated"] is False


def test_service_token_for_api_callers(client):
    headers = {"Authorization": "Bearer wf-token"}
    assert client.get("/api/v1/me", headers=headers).json()["username"] == "service:workflows"
    assert client.get("/api/v1/clusters", params={"type": "mce"}, headers=headers).status_code == 200
    assert client.get("/api/v1/clusters", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_list_filters_and_facets(client):
    login(client)

    def names(**params):
        return [c["name"] for c in client.get("/api/v1/clusters", params=params).json()["items"]]

    assert names(type="click") == ["ocp4-prod-tomer-site1-a"]
    assert names(type="click", mce="ocp4-prod-mce-site1-a") == ["ocp4-prod-tomer-site1-a"]
    assert names(type="click", mce="some-other-mce") == []
    assert names(site="site1") == ["ocp4-prod-core-site1", "ocp4-prod-mce-site1-a", "ocp4-prod-tomer-site1-a"]
    assert names(segment="192.10.20.44") == ["ocp4-prod-tomer-site1-a"]
    assert names(network="prod-net") == ["ocp4-prod-core-site1"]
    assert names(network="lab-net") == []
    assert names(q="CORE") == ["ocp4-prod-core-site1"]
    assert names(version="4.17") == []
    assert names(status="stale") == []

    listing = client.get("/api/v1/clusters", params={"type": "click", "site": "nowhere"}).json()
    assert listing["items"] == []
    # Facets describe the whole type, so the dropdowns do not shrink as filters are applied.
    assert listing["facets"]["sites"] == ["site1"]
    assert listing["facets"]["mces"] == ["ocp4-prod-mce-site1-a"]
    assert listing["facets"]["versions"] == ["4.16"]
    # Only clusters whose chart names a network add to the network options.
    assert listing["facets"]["networks"] == []
    assert client.get("/api/v1/clusters").json()["facets"]["networks"] == ["prod-net"]


def test_reinstalled_cluster_replaces_its_old_report(client):
    body = report("ocp4-prod-core-site1", cluster_id="brand-new-id").model_dump(mode="json", by_alias=True)
    client.post("/api/v1/ingest/reports", json=body, headers=INGEST)
    ids = [c["id"] for c in client.get("/api/v1/clusters", params={"q": "core"}).json()["items"]]
    assert ids == ["brand-new-id"]


# --- segments survive a failed lookup -----------------------------------------


def test_failed_segment_lookup_keeps_the_previous_segments(client):
    def post(**kwargs):
        body = report("ocp4-prod-core-site1", **kwargs).model_dump(mode="json", by_alias=True)
        assert client.post("/api/v1/ingest/reports", json=body, headers=INGEST).status_code == 202
        return client.get("/api/v1/clusters/id-ocp4-prod-core-site1").json()

    # Segments Manager was unreachable from the cluster on this run: keep what we had.
    failed = post(errors=[CollectorError(collector="segments", error="ConnectError")])
    assert (failed["segments"], failed["site"]) == (["192.10.5.0/24"], "site1")

    # The lookup worked and found nothing: the segment really was released.
    released = post()
    assert (released["segments"], released["site"]) == ([], None)


# --- OpenShift sign-in -------------------------------------------------------


def _sa_dir(tmp_path):
    claims = base64.urlsafe_b64encode(json.dumps({"sub": "system:serviceaccount:navigator:cluster-navigator"}).encode())
    (tmp_path / "token").write_text(f"header.{claims.decode().rstrip('=')}.signature")
    (tmp_path / "namespace").write_text("navigator")
    return tmp_path


def test_openshift_sign_in_and_group_lookup(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "authorization_endpoint": "https://oauth.example.com/oauth/authorize",
                "token_endpoint": "https://oauth.example.com/oauth/token",
            })
        if path == "/oauth/token":
            seen["token_request"] = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(200, json={"access_token": "user-token"})
        if path == "/apis/user.openshift.io/v1/users/~":
            assert request.headers["Authorization"] == "Bearer user-token"
            return httpx.Response(200, json={"metadata": {"name": "dana"}})
        if path == "/apis/user.openshift.io/v1/groups/ocp-admins":
            seen["group_calls"] = seen.get("group_calls", 0) + 1
            return httpx.Response(200, json={"users": ["dana", "roi"]})
        return httpx.Response(404)

    async def run():
        provider = OpenShiftProvider(
            api_url="https://kube", sa_dir=str(_sa_dir(tmp_path)),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        url = await provider.authorize_url(state="abc", redirect_uri="https://nav/api/v1/auth/callback")
        username = await provider.exchange(code="the-code", redirect_uri="https://nav/api/v1/auth/callback")
        wanted = frozenset({"ocp-admins", "missing-group"})
        first = await provider.groups_for("dana", wanted)
        second = await provider.groups_for("eve", wanted)
        await provider.close()
        return url, username, first, second

    url, username, dana_groups, eve_groups = asyncio.run(run())
    assert url.startswith("https://oauth.example.com/oauth/authorize?")
    assert "client_id=system%3Aserviceaccount%3Anavigator%3Acluster-navigator" in url
    assert "scope=user%3Ainfo" in url and "state=abc" in url
    assert username == "dana"
    assert seen["token_request"]["client_id"] == "system:serviceaccount:navigator:cluster-navigator"
    assert seen["token_request"]["code"] == "the-code"
    assert dana_groups == {"ocp-admins"}
    assert eve_groups == frozenset()
    # The second lookup was answered from the cache.
    assert seen["group_calls"] == 1


def test_sign_in_trusts_public_cas_besides_the_cluster_ca(tmp_path):
    # The OAuth server sits behind the router, whose certificate is often a public
    # one. Trusting the cluster CA alone failed the token exchange on a real cluster.
    cluster_ca = tmp_path / "ca.crt"
    cluster_ca.write_text(ssl.DER_cert_to_PEM_cert(trust().get_ca_certs(binary_form=True)[0]))
    context = trust(str(cluster_ca), None)
    assert context.cert_store_stats()["x509_ca"] > 100


def test_redirect_flow_end_to_end(tmp_path):
    class FakeOpenShift(OpenShiftProvider):
        async def authorize_url(self, *, state, redirect_uri):
            return f"https://oauth.example.com/authorize?state={state}"

        async def exchange(self, *, code, redirect_uri):
            return "dana"

        async def groups_for(self, username, wanted):
            return frozenset({"ocp-admins"}) & wanted

    provider = FakeOpenShift(api_url="https://kube", sa_dir=str(_sa_dir(tmp_path)), client=httpx.AsyncClient())
    app = create_app(settings(auth_provider="openshift", admin_groups=["ocp-admins"]), store=MemoryStore(), provider=provider)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/v1/me").json()["loginMode"] == "redirect"
        start = client.get("/api/v1/auth/login", params={"return_to": "/mce"})
        state = start.headers["location"].split("state=")[1]

        # A callback with the wrong state is refused and signs nobody in.
        assert client.get("/api/v1/auth/callback", params={"code": "c", "state": "wrong"}).headers["location"] == "/?login=failed"
        assert client.get("/api/v1/me").json()["authenticated"] is False

        done = client.get("/api/v1/auth/callback", params={"code": "c", "state": state})
        assert done.headers["location"] == "/mce"
        me = client.get("/api/v1/me").json()
        assert (me["username"], me["roles"]) == ("dana", ["admin", "client"])


def test_return_to_cannot_leave_the_site(tmp_path):
    from navigator.server.auth.session import safe_return_to

    assert safe_return_to("/click?site=site1") == "/click?site=site1"
    for bad in ("https://evil.example.com", "//evil.example.com", "/\\evil", "", None):
        assert safe_return_to(bad) == "/"
