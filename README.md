# Cluster Navigator

One place to see every OpenShift cluster: its segment, router address,
version, and the rest of its details on demand. Clients browse it without
signing in. Admins sign in with their LDAP account and see more.

It replaces two earlier tools: Axiom (deep per-cluster data from an operator)
and ClickCluster-Navigator (segments from Segments Manager).

## How it works

```
        every OpenShift cluster                         central
┌─────────────────────────────────────┐      ┌───────────────────────────┐
│ collector (CronJob, every 30 min)   │ POST │ server (API + UI)         │
│  1. reads the cluster's own APIs    ├─────►│  /api/v1/ingest/reports   │──► MongoDB
│  2. asks Segments Manager for this  │      └─────────────┬─────────────┘
│     cluster's segments              │                    │
└──────────────────┬──────────────────┘      browsers, and workflows via the API
                   ▼
           Segments Manager
```

- The **collector** runs in each cluster as a CronJob. It works out what kind
  of cluster it is in, gathers version, nodes, capacity, addresses, DNS,
  storage classes and identity providers, looks up the cluster's segments in
  Segments Manager, and sends one report.
- A cluster appears in the platform once its collector has reported. That is
  the only way a cluster gets in.
- The **server** stores the latest report from each cluster and serves it,
  filtered by what the caller is allowed to see. It never calls Segments
  Manager.

[ARCHITECTURE.md](ARCHITECTURE.md) explains the design and the reasons behind it.

## Try it locally

Needs Docker. Everything runs with fake data: 19 clusters across three sites,
a stand-in Segments Manager, and two test users.

```sh
cd deploy/local
docker compose up -d --build
```

Open <http://localhost:8100>.

| | |
|---|---|
| All clusters | The first menu entry lists every cluster you may see in one place, with a Type filter. |
| Client view | No sign-in. The menu shows Generic and Click Cluster only, and a Click Cluster does not show which MCE it runs under. |
| Admin view | **Sign in** with `admin` / `admin`. MCE and KubeVirt appear in the menu, hosted clusters show their MCE, and an MCE lists the clusters it hosts. |
| Cluster details | Press a cluster box. The details open in a window over the page. |
| Export | **Export CSV** downloads the clusters listed on the page, with the filters applied: name, version, segment, router LB, and the MCE when you may see it. |
| A user in no role group | `viewer` / `viewer`. Signs in, stays a client. |
| API docs | <http://localhost:8100/api/docs> |
| API as a workflow would call it | `curl -H 'Authorization: Bearer local-workflows-token' 'localhost:8100/api/v1/clusters?type=mce'` |
| The same list as CSV | `curl -H 'Authorization: Bearer local-workflows-token' 'localhost:8100/api/v1/clusters.csv?type=click'` |

Stop it with `docker compose down`.

## Repository layout

| Path | What it is |
|---|---|
| [backend/navigator/models](backend/navigator/models) | The report a collector sends. Shared by collector and server. |
| [backend/navigator/collector](backend/navigator/collector) | The collector. [detect.py](backend/navigator/collector/detect.py) holds the cluster-type rules. |
| [backend/navigator/server](backend/navigator/server) | The server. [policy.py](backend/navigator/server/policy.py) and [sections.py](backend/navigator/server/sections.py) define who sees what. |
| [ui](ui) | The web UI (React, Vite, Tailwind). |
| [charts/cluster-navigator](charts/cluster-navigator) | Helm chart for the server. |
| [charts/cluster-navigator-collector](charts/cluster-navigator-collector) | Helm chart for the collector. |
| [deploy/local](deploy/local) | The local stack and its fake data. |

## Development

```sh
# Server and collector
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest

# Run the server without Docker (keeps data in memory unless MONGO_URI is set)
INGEST_TOKEN=dev AUTH_PROVIDER=dev ADMIN_GROUPS=ocp-admins COOKIE_SECURE=false \
  DEV_USERS='{"admin": {"password": "admin", "groups": ["ocp-admins"]}}' \
  .venv/bin/uvicorn navigator.server.app:app_factory --factory --port 8100

# UI with hot reload, proxying /api to localhost:8100
cd ui && npm install && npm run dev      # http://localhost:4100
```

## Deploying

On the redbull platform this is automatic. Every push to `main` runs the tests,
builds both images to `ghcr.io/team-redbull/`, and writes the new tags into
the `cluster-navigator` and `cluster-navigator-collector` charts in
[redbull-platform](https://github.com/team-redbull/redbull-platform)
(`gitops/charts/`), where Argo CD picks them up. See
[.github/workflows/build.yml](.github/workflows/build.yml).

To install somewhere else by hand, build and push the two images, both from
the repository root:

```sh
docker build -t <registry>/cluster-navigator:0.1.0 .
docker build -t <registry>/cluster-navigator-collector:0.1.0 -f backend/Dockerfile.collector .
```

**Server**, once, on the cluster that hosts the platform:

```sh
helm upgrade --install cluster-navigator charts/cluster-navigator -n cluster-navigator --create-namespace \
  --set image.repository=<registry>/cluster-navigator \
  --set secret.mongoUri='mongodb://user:pass@mongo:27017' \
  --set secret.ingestToken="$(openssl rand -hex 32)" \
  --set 'auth.adminGroups={ocp-admins}'
```

**Collector**, on every cluster, with the same ingest token:

```sh
helm upgrade --install cluster-navigator-collector charts/cluster-navigator-collector \
  -n cluster-navigator --create-namespace \
  --set image.repository=<registry>/cluster-navigator-collector \
  --set navigatorUrl=https://cluster-navigator.apps.example.com \
  --set segmentsManagerUrl=https://segments-manager.apps.example.com \
  --set ingestToken.value=<the ingest token>
```

Both charts document every option in their `values.yaml`. Under Argo CD, give
the server chart `secret.existingSecret` (see the note in its values).

## Server configuration

Set through the chart, or as environment variables when run by hand.

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `DB_NAME` | MongoDB. Without `MONGO_URI` data is kept in memory. |
| `INGEST_TOKEN` | Required. The bearer token collectors send. |
| `AUTH_PROVIDER` | `openshift`, `dev` or `none`. |
| `ADMIN_GROUPS` | Comma-separated groups whose members are admins. |
| `ROLES`, `<ROLE>_GROUPS` | More roles. See [ARCHITECTURE.md](ARCHITECTURE.md#adding-a-new-kind-of-user). |
| `SESSION_SECRET` | Signs session cookies. Must be the same on every replica. |
| `SERVICE_TOKENS` | API tokens for machine callers, as JSON. |
| `GRAFANA_URL_TEMPLATE` | Where the **Moby** button on each cluster box points. Placeholders `{name}`, `{domain}`, `{clusterId}`. |
| `PRIMARY_SEGMENT_TYPES` | Segment types shown on the box. Default `UPI,HC,MCE,HUB`. |
| `STALE_AFTER_SECONDS` | How long before a silent cluster is shown as stale. Default 5400. |

The full list, with defaults, is in [settings.py](backend/navigator/server/settings.py).
