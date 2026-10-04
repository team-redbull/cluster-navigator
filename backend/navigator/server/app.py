"""The HTTP API and, when built, the UI."""

import hmac
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, SecretStr

from navigator import __version__
from navigator.models import TYPE_LABELS, ClusterReport, ClusterType, Model
from navigator.server import policy
from navigator.server.auth import (
    AuthProvider,
    PasswordProvider,
    RedirectProvider,
    SessionCodec,
    build_provider,
)
from navigator.server.auth.base import AuthError
from navigator.server.auth.session import SESSION_COOKIE, STATE_COOKIE, STATE_TTL_SECONDS, safe_return_to
from navigator.server.export import clusters_csv
from navigator.server.filters import Filters, matches, minor_version
from navigator.server.merge import MergedCluster, MergeOptions, merge
from navigator.server.sections import build_sections
from navigator.server.settings import Settings, get_settings
from navigator.server.store import MemoryStore, MongoStore, Store
from navigator.server.views import ClusterDetail, ClusterList, ClusterStatus, Facets, Me, TypeInfo

logger = logging.getLogger("navigator.server")

SNAPSHOT_TTL_SECONDS = 3.0
CALLBACK_PATH = "/api/v1/auth/callback"


class LoginRequest(Model):
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr = Field(min_length=1, max_length=1024)


@dataclass(frozen=True)
class Selection:
    """What a list request asked for, after access and filters are applied."""

    principal: policy.Principal
    type: ClusterType | None
    allowed: list[MergedCluster]  # every cluster the caller may see
    scoped: list[MergedCluster]  # ... of the requested type
    matched: list[MergedCluster]  # ... that pass the filters


class Navigator:
    """Everything a request needs, built once at startup."""

    def __init__(self, settings: Settings, store: Store, provider: AuthProvider) -> None:
        self.settings = settings
        self.store = store
        self.provider = provider
        self.roles = policy.load_roles(settings)
        self.role_groups = policy.all_groups(self.roles)
        self.sessions = SessionCodec(
            settings.session_secret.get_secret_value() if settings.session_secret else None,
            settings.session_ttl_hours * 3600,
        )
        self.service_tokens: dict[str, dict] = settings.json_setting("service_tokens")
        self.merge_options = MergeOptions(
            stale_after=timedelta(seconds=settings.stale_after_seconds),
            grafana_url_template=settings.grafana_url_template,
        )
        self._snapshot: tuple[float, list[MergedCluster]] | None = None

    def invalidate(self) -> None:
        self._snapshot = None

    async def clusters(self) -> list[MergedCluster]:
        """The merged cluster list, cached briefly so a burst of requests reads the store once."""
        now = time.monotonic()
        if self._snapshot and now - self._snapshot[0] < SNAPSHOT_TTL_SECONDS:
            return self._snapshot[1]
        merged = merge(await self.store.list_reports(), now=datetime.now(UTC), options=self.merge_options)
        self._snapshot = (now, merged)
        return merged

    async def principal(self, request: Request) -> policy.Principal:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and token:
            for name, entry in self.service_tokens.items():
                if hmac.compare_digest(token.encode(), str(entry.get("token", "")).encode()):
                    return policy.resolve(
                        self.roles, username=f"service:{name}", granted=tuple(entry.get("roles") or []), via="token"
                    )
            raise HTTPException(status_code=401, detail="Invalid API token")

        username = self.sessions.decode(request.cookies.get(SESSION_COOKIE))
        if username:
            groups = await self.provider.groups_for(username, self.role_groups)
            return policy.resolve(self.roles, username=username, groups=groups, via="session")
        return policy.resolve(self.roles)


def _store_for(settings: Settings) -> Store:
    if settings.mongo_uri:
        return MongoStore(settings.mongo_uri, settings.db_name, settings.report_ttl_days)
    logger.warning("MONGO_URI is not set: keeping data in memory, it will be lost on restart")
    return MemoryStore()


def create_app(
    settings: Settings | None = None,
    *,
    store: Store | None = None,
    provider: AuthProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    store = store or _store_for(settings)
    provider = provider or build_provider(settings)

    nav = Navigator(settings, store, provider)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auth_provider != "none" and nav.sessions.generated:
            logger.warning("SESSION_SECRET is not set: sessions end on restart and break across replicas")
        if settings.auth_provider != "none" and not nav.roles["admin"].groups:
            logger.warning("ADMIN_GROUPS is empty: nobody can sign in as admin")
        await store.init()
        yield
        await provider.close()
        await store.close()

    app = FastAPI(
        title="Cluster Navigator",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.navigator = nav
    api = APIRouter(prefix="/api/v1")

    async def current(request: Request) -> policy.Principal:
        return await nav.principal(request)

    def visible(clusters: list[MergedCluster], principal: policy.Principal) -> list[MergedCluster]:
        """The clusters this caller may see, without the parts they may not.

        Every endpoint that returns clusters reads them through here, so what
        is removed here is never sent: not on the box, in the details, in the
        filter options, or in an export.
        """
        allowed = [c for c in clusters if principal.can_see_type(c.card.type)]
        if principal.can_see_parent_mce:
            return allowed
        return [replace(c, card=c.card.model_copy(update={"mce": None})) for c in allowed]

    async def selection(
        principal: policy.Principal = Depends(current),
        type: ClusterType | None = Query(default=None, description="Cluster type"),
        q: str | None = Query(default=None, description="Part of the cluster name"),
        site: str | None = None,
        network: str | None = Query(default=None, description="The network the cluster belongs to"),
        mce: str | None = Query(default=None, description="Parent MCE name"),
        segment: str | None = Query(default=None, description="An IP address, a CIDR, or part of one"),
        version: str | None = Query(default=None, description="OpenShift minor version, for example 4.16"),
        status: ClusterStatus | None = None,
    ) -> Selection:
        """The filters shared by the list and its export, so both return the same clusters."""
        if type is not None and not principal.can_see_type(type):
            raise HTTPException(status_code=403, detail="You do not have access to this cluster type")
        allowed = visible(await nav.clusters(), principal)
        scoped = [c for c in allowed if type is None or c.card.type == type]
        filters = Filters(
            q=q, site=site, network=network, mce=mce, segment=segment, version=version,
            status=status.value if status else None,
        )
        return Selection(
            principal=principal,
            type=type,
            allowed=allowed,
            scoped=scoped,
            matched=[c for c in scoped if matches(c, filters)],
        )

    def set_session(response: Response, username: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            nav.sessions.encode(username),
            max_age=nav.sessions.ttl_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )

    def callback_url(request: Request) -> str:
        base = settings.public_url or str(request.base_url)
        return base.rstrip("/") + CALLBACK_PATH

    # --- who am I -----------------------------------------------------------

    @api.get("/me", response_model=Me)
    async def me(principal: policy.Principal = Depends(current)) -> Me:
        return Me(
            authenticated=principal.authenticated,
            username=principal.username,
            roles=list(principal.roles),
            types=[TypeInfo(id=t, label=TYPE_LABELS[t]) for t in ClusterType if principal.can_see_type(t)],
            audiences=sorted(principal.audiences),
            login_mode=provider.mode,
        )

    # --- clusters -----------------------------------------------------------

    @api.get("/clusters", response_model=ClusterList)
    async def list_clusters(selected: Selection = Depends(selection)) -> ClusterList:
        principal, scoped = selected.principal, selected.scoped

        counts = {t.value: 0 for t in ClusterType if principal.can_see_type(t)}
        for cluster in selected.allowed:
            counts[cluster.card.type.value] += 1

        facets = Facets(
            sites=sorted({c.card.site for c in scoped if c.card.site}),
            networks=sorted({c.card.network for c in scoped if c.card.network}),
            mces=sorted({c.card.mce for c in scoped if c.card.mce}),
            versions=sorted(
                {v for c in scoped if (v := minor_version(c.card.openshift_version))},
                key=_version_key,
                reverse=True,
            ),
        )
        items = [c.card for c in selected.matched]
        return ClusterList(items=items, total=len(items), facets=facets, counts=counts)

    @api.get("/clusters.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
    async def export_clusters(selected: Selection = Depends(selection)) -> Response:
        """The same clusters as the list, with the same filters, as a file."""
        body = clusters_csv(
            [c.card for c in selected.matched], include_mce=selected.principal.can_see_parent_mce
        )
        scope = selected.type.value if selected.type else "all"
        filename = f"clusters-{scope}-{datetime.now(UTC):%Y-%m-%d}.csv"
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                # It holds what this caller may see, so it must not be reused for another.
                "Cache-Control": "no-store",
            },
        )

    @api.get("/clusters/{cluster_id}", response_model=ClusterDetail)
    async def get_cluster(cluster_id: str, principal: policy.Principal = Depends(current)) -> ClusterDetail:
        for cluster in visible(await nav.clusters(), principal):
            if cluster.card.id == cluster_id or cluster.card.name == cluster_id:
                return ClusterDetail(
                    **cluster.card.model_dump(),
                    sections=build_sections(cluster, principal, datetime.now(UTC)),
                )
        # A cluster the caller may not see answers the same as one that does not exist.
        raise HTTPException(status_code=404, detail="Cluster not found")

    # --- ingest -------------------------------------------------------------

    @api.post("/ingest/reports", status_code=202)
    async def ingest(report: ClusterReport, request: Request) -> dict:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        expected = settings.ingest_token.get_secret_value()
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid ingest token")
        # The segment lookup failed on this run (Segments Manager unreachable from
        # the cluster). Keep the segments from its previous report, so one bad
        # run does not blank out a cluster's segment.
        if not report.segments and any(error.collector == "segments" for error in report.errors):
            previous = await store.get_report(report.cluster_id)
            if previous and previous.report.segments:
                report = report.model_copy(
                    update={"segments": previous.report.segments, "site": previous.report.site}
                )
        await store.upsert_report(report, datetime.now(UTC))
        nav.invalidate()
        logger.info("report from %s (%s), type %s", report.name, report.cluster_id, report.type.value)
        return {"status": "accepted", "id": report.cluster_id}

    # --- sign-in ------------------------------------------------------------

    @api.post("/auth/login", response_model=Me)
    async def login(body: LoginRequest, response: Response) -> Me:
        if not isinstance(provider, PasswordProvider):
            raise HTTPException(status_code=404, detail="Password sign-in is not enabled")
        username = await provider.authenticate(body.username, body.password.get_secret_value())
        if not username:
            raise HTTPException(status_code=401, detail="Wrong username or password")
        set_session(response, username)
        groups = await provider.groups_for(username, nav.role_groups)
        return await me(policy.resolve(nav.roles, username=username, groups=groups, via="session"))

    @api.get("/auth/login", include_in_schema=False)
    async def login_redirect(request: Request, return_to: str = "/") -> Response:
        if not isinstance(provider, RedirectProvider):
            raise HTTPException(status_code=404, detail="Redirect sign-in is not enabled")
        state, cookie = nav.sessions.encode_state(safe_return_to(return_to))
        try:
            url = await provider.authorize_url(state=state, redirect_uri=callback_url(request))
        except Exception as exc:  # noqa: BLE001 - whatever went wrong, the user needs an answer
            logger.exception("could not start sign-in")
            raise HTTPException(status_code=502, detail="The identity provider is not reachable") from exc
        response = RedirectResponse(url, status_code=302)
        response.set_cookie(
            STATE_COOKIE, cookie, max_age=STATE_TTL_SECONDS, httponly=True,
            secure=settings.cookie_secure, samesite="lax", path=CALLBACK_PATH,
        )
        return response

    @api.get("/auth/callback", include_in_schema=False)
    async def login_callback(request: Request, code: str | None = None, state: str | None = None) -> Response:
        if not isinstance(provider, RedirectProvider):
            raise HTTPException(status_code=404, detail="Redirect sign-in is not enabled")
        return_to = nav.sessions.decode_state(request.cookies.get(STATE_COOKIE), state)
        if return_to is None or not code:
            return RedirectResponse("/?login=failed", status_code=302)
        try:
            username = await provider.exchange(code=code, redirect_uri=callback_url(request))
        except AuthError:
            return RedirectResponse("/?login=failed", status_code=302)
        response = RedirectResponse(safe_return_to(return_to), status_code=302)
        response.delete_cookie(STATE_COOKIE, path=CALLBACK_PATH)
        set_session(response, username)
        return response

    @api.post("/auth/logout", status_code=204)
    async def logout(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/")

    # --- operations ---------------------------------------------------------

    @api.get("/status")
    async def status(principal: policy.Principal = Depends(current)) -> dict:
        if not principal.can_see_audience(policy.ADMIN):
            raise HTTPException(status_code=403, detail="Admin only")
        clusters = await nav.clusters()
        by_status: dict[str, int] = {}
        for cluster in clusters:
            by_status[cluster.card.status.value] = by_status.get(cluster.card.status.value, 0) + 1
        return {"version": __version__, "clusters": {"total": len(clusters), **by_status}}

    app.include_router(api)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        healthy = await store.ping()
        return JSONResponse({"status": "ok" if healthy else "degraded"}, status_code=200 if healthy else 503)

    _mount_ui(app, settings.ui_dir)
    return app


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def _mount_ui(app: FastAPI, ui_dir: str | None) -> None:
    """Serve the built single-page app from the same origin as the API."""
    if not ui_dir:
        return
    root = Path(ui_dir)
    index = root / "index.html"
    if not index.is_file():
        logger.warning("UI_DIR %s has no index.html: the UI is not served", root)
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root.resolve() in candidate.parents:
            return FileResponse(candidate)
        # Client-side routes all load the app shell, which must not be cached
        # or a new release would keep loading the old bundle.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
