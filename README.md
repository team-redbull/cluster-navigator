# Cluster Navigator

One place to see every OpenShift cluster: its type, segment, router address,
version, network, and the rest of its details on demand. Clients browse it
without signing in. Admins sign in with their LDAP account and see more
clusters, and more about each one.

It replaces two earlier tools: Axiom (deep per-cluster data from an operator)
and ClickCluster-Navigator (segments from Segments Manager).

This README is the technical guide for working on it: how data flows from a
cluster to the screen, how each cluster type is handled, who sees what and
how that is enforced, and where each part lives in the code.

## Contents

- [Architecture at a glance](#architecture-at-a-glance)
- [The flow, end to end](#the-flow-end-to-end)
  - [1. Collect: the collector in each cluster](#1-collect-the-collector-in-each-cluster)
  - [2. Ingest: the server receives a report](#2-ingest-the-server-receives-a-report)
  - [3. Merge: from reports to a cluster list](#3-merge-from-reports-to-a-cluster-list)
  - [4. Serve: one request, from caller to response](#4-serve-one-request-from-caller-to-response)
  - [5. Show: the UI](#5-show-the-ui)
- [Cluster types](#cluster-types)
- [Segments, sites and networks](#segments-sites-and-networks)
- [Who sees what: the client and admin views](#who-sees-what-the-client-and-admin-views)
- [Sign-in and `AUTH_PROVIDER`](#sign-in-and-auth_provider)
- [Reporting, stale and removal](#reporting-stale-and-removal)
- [API](#api)
- [The report and storage](#the-report-and-storage)
- [Code map](#code-map)
- [Running locally](#running-locally)
- [Configuration](#configuration)
- [Deploying](#deploying)
- [Why it is built this way](#why-it-is-built-this-way)
- [Known limits and what is not yet verified](#known-limits-and-what-is-not-yet-verified)

## Architecture at a glance

```
         every OpenShift cluster                          the platform cluster
┌──────────────────────────────────────┐          ┌──────────────────────────────────┐
│ collector (CronJob, every 30 min)    │   POST   │ server (FastAPI, also serves UI) │
│  1. read the cluster's own APIs      │  report  │                                  │
│  2. work out the cluster type        ├─────────►│  /api/v1/ingest/reports          ├──► MongoDB
│  3. look up its segments ──────┐     │  Bearer  │  /api/v1/clusters, /me, ...      │    (latest report
│  4. send one report, exit      │     │  INGEST_ │  /  (the web UI)                 │     per cluster)
└────────────────────────────────┼─────┘  TOKEN   └─────────────────▲────────────────┘
                                 ▼                                  │
                         Segments Manager              browsers, and workflows with an
                                                       API token (SERVICE_TOKENS)
```

Two deployables, one shared data contract:

| Part | Runs as | Image | Chart |
|---|---|---|---|
| Collector | A CronJob in every cluster | `cluster-navigator-collector` ([backend/Dockerfile.collector](backend/Dockerfile.collector)) | [charts/cluster-navigator-collector](charts/cluster-navigator-collector) |
| Server and UI | One Deployment and Route, on the platform cluster | `cluster-navigator` ([Dockerfile](Dockerfile)) | [charts/cluster-navigator](charts/cluster-navigator) |
| The report | The JSON body the collector posts | shared Python models | [backend/navigator/models](backend/navigator/models) |

Three rules explain most of the design:

1. **A cluster exists once its collector reports.** There is no registration,
   inventory file or scan. The server never calls a cluster or Segments
   Manager. It reads its own database and nothing else.
2. **The collector works out the facts itself**, the cluster type included,
   from the cluster's own APIs. Nobody has to set a flag correctly at install
   time. The exception is what a cluster cannot know about itself: which
   network it is on (`network` in the chart), plus overrides for the rare
   cluster the rules get wrong.
3. **Access is decided on the server.** Data a caller may not see is removed
   before the response is built, so it never reaches the browser, an API
   caller or a CSV file. The UI makes no access decisions.

## The flow, end to end

### 1. Collect: the collector in each cluster

The CronJob starts one pod every 30 minutes. The pod runs
`python -m navigator.collector` ([\_\_main\_\_.py](backend/navigator/collector/__main__.py))
once and exits:

1. Read the cluster's own APIs with the pod's ServiceAccount, which has a
   read-only ClusterRole ([collect.py](backend/navigator/collector/collect.py)).
2. Decide the cluster type ([detect.py](backend/navigator/collector/detect.py),
   see [Cluster types](#cluster-types)).
3. Ask Segments Manager for this cluster's segments
   ([segments.py](backend/navigator/collector/segments.py)).
4. Post one `ClusterReport` to the server
   ([push.py](backend/navigator/collector/push.py)).

What it reads:

| Fact | From |
|---|---|
| Cluster ID | `ClusterVersion/version` `.spec.clusterID` |
| OpenShift version | `ClusterVersion/version`: the newest `Completed` entry in `.status.history`, else `.status.desired` |
| Kubernetes version | `GET /version` |
| Name and base domain | `DNS/cluster` `.spec.baseDomain`, read as `<name>.<base domain>`. `clusterName` in the chart overrides the name. |
| Platform, API URL, control plane topology | `Infrastructure/cluster` |
| Console URL | `Console/cluster`, else `console-openshift-console.<apps domain>` from `Ingress/cluster` |
| Router LB and API addresses | A DNS lookup of the console and API hostnames |
| Nodes and capacity | The `Node` list. Addresses are read by type, never by position. CPU, memory and ephemeral storage are summed from capacity, pods from allocatable, GPUs from `nvidia.com/gpu`. |
| DNS servers and search domains | The pod's `/etc/resolv.conf`, which is the node's own because the pod runs with `dnsPolicy: Default` |
| Storage classes | The `StorageClass` list, with the default taken from its annotation |
| Identity providers | `OAuth/cluster` |
| Type signals | Whether a `MultiClusterEngine` or a `HyperConverged` object exists, and the control plane topology |
| Hosted clusters (MCE only) | `HostedCluster` and `NodePool` |
| Segments and site | Segments Manager |
| Network | The chart's `network` value, passed as `CLUSTER_NETWORK` |

How a run behaves:

- **Each fact is its own step.** A step that fails (a missing permission, a
  failed DNS lookup) is recorded in the report's `errors` list and the rest of
  the report is still sent. The errors are stored with the report but not
  shown in the UI. Only the cluster ID and name are required. Without them
  the run fails with exit code 1 and nothing is sent.
- **Segment lookup.** `GET <segmentsManagerUrl>/api/segments/search?q=<name>&status=Allocated`.
  The search matches parts of names, so the collector keeps only segments
  whose `cluster_name` equals its own name. If that name exists at two sites,
  it picks the site whose segments contain its own node or router addresses.
  With no `segmentsManagerUrl` there is no lookup and no segments.
- **Delivery.** Three attempts, 5 then 10 seconds apart, on a connection error
  or a 5xx. A 4xx (bad token, invalid report) fails at once, since a retry
  would get the same answer.
- **Scheduling.** `concurrencyPolicy: Forbid` stops runs piling up.
  `backoffLimit: 0` means the next tick is the retry, and a failed run stays
  visible as a failed Job. One run may take at most 300 seconds.
- **DNS side effect.** With `dnsPolicy: Default`, in-cluster Service names do
  not resolve in the collector pod. `navigatorUrl` and `segmentsManagerUrl`
  must be Route or other external hostnames.
- **Trying it by hand.** `DRY_RUN=true` prints the report instead of sending it.

### 2. Ingest: the server receives a report

`POST /api/v1/ingest/reports` (`ingest` in [app.py](backend/navigator/server/app.py)):

1. Checks `Authorization: Bearer <INGEST_TOKEN>` with a constant-time compare.
   A wrong token gets `401`.
2. Validates the body against `ClusterReport`
   ([report.py](backend/navigator/models/report.py)). An invalid body gets `422`.
   Unknown fields are ignored, so a newer collector can talk to an older
   server and the other way around.
3. If the segment lookup failed on this run (no segments, and an error from
   the `segments` step), it keeps the segments and site from the previous
   report. One run that cannot reach Segments Manager does not blank a
   cluster's segments. A lookup that succeeds and finds nothing does clear them.
4. Stores the report as the cluster's only report, keyed by cluster ID, with
   `receivedAt` set to the server's clock, not the cluster's. A report with
   the same name and base domain under a different ID (a reinstalled cluster)
   deletes the old one.
5. Drops the cached cluster list, so the next read includes the new report.

Nothing derived is stored. The raw report is kept and everything else is
worked out on read.

### 3. Merge: from reports to a cluster list

On every read, [merge.py](backend/navigator/server/merge.py) turns the stored
reports into a list of `MergedCluster` objects. Each holds a `ClusterCard`
(what the box shows) and the full report (what the details are built from).
The result is cached for 3 seconds, so a burst of requests reads the store once.

- **Status.** `reporting` when the last report arrived within
  `STALE_AFTER_SECONDS` (default 5400, 90 minutes). Otherwise `stale`. See
  [Reporting, stale and removal](#reporting-stale-and-removal).
- **Parent MCE.** Every MCE's report lists the `HostedCluster` objects it runs.
  A cluster whose name is in such a list gets that MCE as its parent. The
  parent is never guessed from a naming convention.
- **`hosted` flag.** True when the cluster has a parent MCE, is a Click
  Cluster, or reports `controlPlaneTopology: External`.
- **Fallbacks for hosted clusters.** Version and identity providers are
  configured on the MCE, so when a hosted cluster's own report lacks them,
  they come from what its MCE reports about it.
- **Segments on the box.** Only the cluster-facing types: `UPI`, `HC`, `MCE`
  and `HUB` (`PRIMARY_SEGMENT_TYPES` in merge.py, fixed in code). If none
  match, all of them. Inventory and PXE segments appear in the details.
- **Moby link.** `GRAFANA_URL_TEMPLATE` with `{name}`, `{domain}` and
  `{clusterId}` filled in.
- **On an MCE,** which of its hosted clusters have their own collector reporting.

### 4. Serve: one request, from caller to response

```
request
  │
  ├─ Who is calling?               Navigator.principal()             app.py
  │    Bearer <service token>   →  the roles listed in SERVICE_TOKENS
  │    cn_session cookie        →  username → live group lookup → roles
  │    neither                  →  anonymous → the client role
  │
  ├─ What may they see?            visible()                         app.py
  │    drop clusters of types none of their roles grant
  │    remove the parent MCE name if they may not open MCE clusters
  │
  ├─ What did they ask for?        selection(), matches()            app.py, filters.py
  │    type, q, segment, network, site, mce, version, status
  │
  └─ Build the response
       list     cards, plus facets (dropdown options) and a count per type
       CSV      the same rows as the list                            export.py
       details  the card, plus the sections whose audience they hold sections.py
```

Details worth knowing:

- Every endpoint that returns clusters reads them through `visible()`. A new
  endpoint inherits the access rules by using it.
- Asking for a type you may not open (`?type=mce` as a client) gets `403`.
  Asking for one cluster you may not see gets `404`, the same answer as for a
  cluster that does not exist.
- `counts` covers every cluster you may see, whatever the filters. The menu
  shows these numbers.
- `facets` covers the requested type before the other filters are applied, so
  the dropdowns do not shrink as you filter.

### 5. Show: the UI

React, Vite and Tailwind, in [ui](ui). The build is copied into the server
image and served from the same origin as the API (`UI_DIR`). There is no
separate frontend deployment and no CORS.

- **Start.** The UI calls `GET /api/v1/me` ([session.tsx](ui/src/session.tsx)).
  `types` holds the cluster types this user may open, and the menu is built
  from it: "All clusters" first, then one entry per type. `loginMode` decides
  what **Sign in** does.
- **Routes.** `/all` and `/<type>`. A type that is not in `me.types` redirects
  to `/all` ([ClustersPage.tsx](ui/src/components/ClustersPage.tsx)).
- **State lives in the URL.** The filters (`q`, `segment`, `network`, `site`,
  `mce`, `version`, `status`, and `type` on `/all`) and the open cluster
  (`open=<id>`) are query parameters, so any view can be shared or bookmarked.
- **List.** `GET /clusters` with the same parameters. It reloads every 60
  seconds while the tab is visible. A `401` or `403` means access was lost
  mid-session, so the UI reloads `/me` and the menu follows.
- **Cache** (`useLoad` in [hooks.ts](ui/src/hooks.ts)). The UI keeps the last
  answer for each list and each cluster's details, in memory. A view seen
  before shows at once and refreshes in the background. Once the first page
  has loaded, every menu entry is loaded once in the background too, so the
  first visit to each is instant as well. Cache keys include the user and
  their roles, so an answer is never reused across access levels, and
  signing in or out clears it.
- **Box** ([ClusterCard.tsx](ui/src/components/ClusterCard.tsx)). Name,
  version, segment, router LB, the MCE (hosted clusters, for users who may
  know it), the network (when set), the type (on "All clusters"), Console and
  Moby links, and a **Stale** chip.
- **Details** ([ClusterDetails.tsx](ui/src/components/ClusterDetails.tsx)).
  A dialog that loads `GET /clusters/{id}`. [Sections.tsx](ui/src/components/Sections.tsx)
  has one renderer per section `kind` (`kv`, `stats`, `table`, `tags`) and
  nothing per section, so a section added on the server needs no UI change.
  A section whose audience is not `public` carries an "*audience* only" tag.
- **Export CSV** is a link to `/clusters.csv` with the same parameters.
- The UI hides controls that the server's answers make pointless: the MCE
  filter when `me.types` has no MCE, the Network filter when no cluster has a
  network. These are conveniences. The server enforces access either way.

## Cluster types

| Type | What it is | Hosted? | Client view | Admin view |
|---|---|---|---|---|
| **Generic** | A standalone cluster (UPI) | No | Yes | Yes |
| **Click Cluster** | A hosted cluster. Its control plane runs on an MCE. | Always | Yes | Yes |
| **MCE** | A hub running the multicluster engine. It hosts Click Clusters. | No | No | Yes |
| **KubeVirt** | A cluster with OpenShift Virtualization installed | Standalone or hosted | No | Yes |

The type list is `ClusterType` in [types.py](backend/navigator/models/types.py).
The UI menu is built from it.

### How the type is decided

The collector works it out from the cluster's own APIs. The rules live in one
function, [detect.py](backend/navigator/collector/detect.py), and the first
match wins:

| # | Signal | Type |
|---|---|---|
| 1 | `clusterType` set in the collector chart (anything but `auto`) | whatever was set |
| 2 | A `MultiClusterEngine` object exists | MCE |
| 3 | A `HyperConverged` object exists (OpenShift Virtualization) | KubeVirt |
| 4 | `Infrastructure/cluster` has `controlPlaneTopology: External` | Click Cluster |
| 5 | none of the above | Generic |

The signals behind each decision are stored in the report's `detection` field,
with `source` set to `auto` or `override`. A wrong type can be traced to the
rule that produced it. Some consequences of the order:

- An MCE that also runs OpenShift Virtualization stays an MCE.
- Installing OpenShift Virtualization changes a cluster's type. A Generic or
  Click Cluster becomes KubeVirt on its next report and leaves the client view.
- A KubeVirt cluster's "hosted" status comes from its control plane, not its
  type. A hosted one shows its MCE the way a Click Cluster does.

### Hosted clusters and their MCE

- An MCE's collector reads `HostedCluster` and `NodePool` and reports each
  hosted cluster's name, namespace, version, platform, node pool count,
  replicas and identity providers.
- The server links a hosted cluster to its MCE by name, using that list (see
  [Merge](#3-merge-from-reports-to-a-cluster-list)). If the MCE does not
  report, the hosted cluster has no MCE and its MCE line reads "Not available".
- A hosted cluster with no collector of its own does not appear as a cluster.
  Admins still see it in the MCE's **Hosted clusters** table, with
  **Collector reporting** set to No. That is how a missing collector gets noticed.

### What differs by type

| | Generic | Click Cluster | MCE | KubeVirt |
|---|---|---|---|---|
| MCE line on the box (admins only) | | Yes | | If hosted |
| Version and identity providers fall back to the MCE's | | Yes | | If hosted |
| **Hosted clusters** section (admins only) | | | Yes | |
| Detected by | nothing else matching | external control plane | `MultiClusterEngine` | `HyperConverged` |

## Segments, sites and networks

These are three different things:

| | Where it comes from | Shown | Filter |
|---|---|---|---|
| **Segment** | Segments Manager, looked up by the collector | On the box: the cluster-facing ones (`UPI`, `HC`, `MCE`, `HUB`). In the details: all of them, with VLAN, EPG and site. | **Segment**: an IP, a CIDR, or part of one |
| **Site** | Segments Manager: the site the segments belong to | In the details | **Site** dropdown |
| **Network** | The collector chart's `network` value | On the box, in the details and in the CSV, when set | **Network** dropdown |

The **Segment** filter (`segment=` in the API, `segment_matches` in
[filters.py](backend/navigator/server/filters.py)) accepts:

- an IP address: matches a cluster whose segment contains it, or that uses it
  as a router, API or node address
- a CIDR: matches a cluster with an overlapping segment
- anything else: a text match on segments and addresses, for example `192.10.5`

A **network** separates clusters on sites that run several separate networks
(domains), as an air-gapped site does. The cluster cannot tell which one it is
on, so it is set per cluster at install time:

```sh
helm upgrade --install cluster-navigator-collector charts/cluster-navigator-collector ... \
  --set network=<network name>
```

It is free text, and the filter is an exact match, so use the same spelling on
every cluster of a network. Clusters without one show no Network line. The
Network filter appears only once at least one cluster has a network.

## Who sees what: the client and admin views

Access is defined in one file, [policy.py](backend/navigator/server/policy.py).
A **role** grants two things:

- **cluster types** it may list and open
- **audiences**: tags on the sections of a cluster's details

| Role | Who holds it | Cluster types | Audiences |
|---|---|---|---|
| `client` | Everyone, signed in or not | Generic, Click Cluster | `public` |
| `admin` | Members of the groups in `ADMIN_GROUPS`, and service tokens granted `admin` | All four | All |

A caller's access is the union of every role they hold (`Principal`). In
practice the two views differ like this:

| | Client view | Admin view |
|---|---|---|
| Menu | All clusters, Generic, Click Cluster | Also MCE and KubeVirt |
| A hosted cluster's MCE | Never named: not on the box, in the details, in the filter options or in the CSV | Shown |
| MCE filter | Not offered. `?mce=` matches nothing | Offered |
| CSV columns | `name, version, segment, router_lb, network` | The same, plus `mce` |
| Details sections | The `public` ones | Also **Hosted clusters** on an MCE |
| `GET /api/v1/status` | `403` | Cluster counts by state |
| Bottom of the menu | "Viewing as client" and **Sign in** | Username, roles and **Sign out** |

Every section of the details is declared in
[sections.py](backend/navigator/server/sections.py) with its audience:

| Section | Kind | Audience |
|---|---|---|
| Overview (type, site, network, parent MCE, versions, URLs, status) | `kv` | `public` |
| Addresses and DNS | `kv` | `public` |
| Capacity | `stats` | `public` |
| Identity providers | `tags` | `public` |
| Segments, Nodes, Storage classes | `table` | `public` |
| Hosted clusters | `table` | `admin` |

**One rule follows from the cluster types:** a caller who may not open MCE
clusters is not told which MCE a hosted cluster runs under, because that would
name a cluster they may not see (`Principal.can_see_parent_mce`). `visible()`
removes it in the one place every endpoint reads clusters from.

Where access is enforced:

| What | Where |
|---|---|
| Which clusters are returned | `visible()` in [app.py](backend/navigator/server/app.py) |
| `403` for a type you may not open | `selection()` in app.py |
| `404` for a cluster you may not see | `get_cluster()` in app.py |
| Which sections are built | `build_sections()` in [sections.py](backend/navigator/server/sections.py) |
| Which types the menu offers | `GET /me` returns only the types you may open |
| The `mce` CSV column | `clusters_csv(include_mce=...)` in [export.py](backend/navigator/server/export.py) |

### Adding a new kind of user

Say a storage team should see an extra *Storage backend* section on every
cluster.

1. **Write the section** in `sections.py`, with a new audience name:

   ```python
   def _storage_backend(d, c, now): ...
   SectionDef("storageBackend", "Storage backend", "storage", _storage_backend),
   ```

2. **Define the role and its groups** in configuration:

   ```yaml
   # charts/cluster-navigator values
   auth:
     roles:
       storage:
         clusterTypes: ["*"]
         audiences: ["public", "storage"]
     roleGroups:
       storage: ["storage-team"]
   ```

   or as environment variables:
   `ROLES='{"storage": {"clusterTypes": ["*"], "audiences": ["public", "storage"]}}'`
   and `STORAGE_GROUPS='["storage-team"]'`.

No UI change is needed. Admins see the new section too, because the admin role
holds every audience.

## Sign-in and `AUTH_PROVIDER`

`AUTH_PROVIDER` chooses **how a person proves who they are**. It does not
decide what they see. A provider ([auth/base.py](backend/navigator/server/auth/base.py))
answers two questions:

1. **Who is this user?** By checking a password, or by sending the browser
   to an identity provider and back.
2. **Which of the groups that grant a role are they in?** `groups_for()` is
   called on every request, with only the groups named in `ADMIN_GROUPS` and
   `<ROLE>_GROUPS`.

[policy.py](backend/navigator/server/policy.py) then turns those groups into
roles. So the same `ADMIN_GROUPS` works the same way under any provider that
supports sign-in.

| | `none` | `dev` | `openshift` |
|---|---|---|---|
| Meant for | Sign-in switched off: tests, quick local runs | Local runs (the compose stack) | Production. The default, and the only one the chart uses. |
| The **Sign in** button | Hidden | Opens a username and password form | Sends the browser to the cluster's own login page |
| `loginMode` in `/me` | `disabled` | `password` | `redirect` |
| Sign-in endpoints | none | `POST /auth/login` | `GET /auth/login`, `GET /auth/callback` |
| Users come from | | `DEV_USERS` (JSON) | The cluster's identity provider (LDAP) |
| Groups come from | | `DEV_USERS` | OpenShift `Group` objects |

Because `openshift` is the default, a server started outside OpenShift
without `AUTH_PROVIDER` stops at startup with a message saying to set
`AUTH_PROVIDER=dev` or `none`.

Common to all three:

- Anonymous visitors are clients. Signing in can only add access.
- Service tokens (`SERVICE_TOKENS`) work under every provider. With `none`
  they are the only way to get admin access, and `ADMIN_GROUPS` has no effect.
- A signed-in user gets a `cn_session` cookie, signed with `SESSION_SECRET`
  and valid for `SESSION_TTL_HOURS` (12). It holds **only the username**.
  Roles are worked out again on every request from live group membership, so
  removing someone from a group takes their access away within
  `GROUP_CACHE_SECONDS` (60), even mid-session. `SESSION_SECRET` must be the
  same on every replica.

### `openshift`: log in with OpenShift

The same experience as the Temporal UI: users type their LDAP credentials into
the normal OpenShift login page. Temporal puts an oauth-proxy sidecar in front
of the whole UI, which cannot let anonymous clients through. Here the server
runs the OAuth flow itself ([openshift.py](backend/navigator/server/auth/openshift.py)):

1. **Sign in** sends the browser to `GET /api/v1/auth/login?return_to=<page>`.
   The server sets a short-lived signed state cookie and redirects to the
   cluster's OAuth server, which it finds through
   `<API>/.well-known/oauth-authorization-server`.
2. The OAuth client is the server's own ServiceAccount
   (`client_id = system:serviceaccount:<namespace>:<name>`). No `OAuthClient`
   object is needed.
3. The user signs in. OpenShift redirects to `/api/v1/auth/callback?code=...&state=...`.
4. The server checks the state against the cookie, then exchanges the code
   for a token, using the ServiceAccount's own token as the client secret.
5. It uses that token once, on `GET /apis/user.openshift.io/v1/users/~`, to
   learn the username. It never sees a password, and it keeps no user token.
6. It sets the session cookie and redirects back to the page the user started
   on. Any failure redirects to `/?login=failed`, which shows a banner.

Group membership is read with the ServiceAccount's own token:
`GET /apis/user.openshift.io/v1/groups/<name>` for each group that grants a
role. If the Group does not exist, nobody gets that role and a warning is
logged. If the API cannot be reached, the last cached answer is used. With no
cached answer the user is treated as a client, so an outage never grants access.

What the chart sets up for `openshift`
([charts/cluster-navigator/templates](charts/cluster-navigator/templates)):

| Object | Why |
|---|---|
| An annotation on the ServiceAccount, pointing at the Route | Allows the Route as the OAuth redirect target |
| A `kubernetes.io/service-account-token` Secret for that ServiceAccount | The OAuth server refuses the token exchange without one. OpenShift 4.16 and later no longer create it. |
| A ClusterRole with `get` on exactly the named Groups | The server can read those Groups and nothing else, and cannot list Groups |
| The Route | Always created, since sign-in redirects back to it. `route.host` also sets `PUBLIC_URL`, which builds the callback URL. |

Prerequisites:

- **The OpenShift Groups must exist.** On an LDAP-backed cluster they are
  created by `oc adm groups sync` or the group-sync operator, not by logging
  in. Check with `oc get group <name> -o jsonpath='{.users}'`.
- **TLS.** The server trusts the public CAs, the cluster CA and, if set,
  `OPENSHIFT_CA_FILE`. The OAuth server is reached through the router. If the
  site signs router certificates with its own CA, pass that CA in
  `OPENSHIFT_CA_FILE`.

### `dev`: fixed users

For local runs only. Users, passwords and groups come from `DEV_USERS`:

```sh
DEV_USERS='{"admin": {"password": "admin", "groups": ["ocp-admins"]}}'
```

The UI shows a username and password form that posts to `/api/v1/auth/login`.

### Machine callers

The workflows and other scripts send `Authorization: Bearer <token>`, with a
token from `SERVICE_TOKENS`:

```json
{"workflows": {"token": "<long random value>", "roles": ["admin"]}}
```

The token grants the listed roles directly, with no group lookup. An unknown
bearer token gets `401`. It is not treated as an anonymous caller.

### Adding another provider

To add one, for example the `redbull-ldap` checker, subclass
`PasswordProvider` or `RedirectProvider` in
[auth/base.py](backend/navigator/server/auth/base.py), add it to
`build_provider()` in [auth/\_\_init\_\_.py](backend/navigator/server/auth/__init__.py),
and add its name to `auth_provider` in [settings.py](backend/navigator/server/settings.py).
Roles and views do not change.

## Reporting, stale and removal

| State | Meaning |
|---|---|
| **Reporting** | The collector sent a report within `STALE_AFTER_SECONDS` (90 minutes by default). What is shown is current. |
| **Stale** | No report for longer than that, which is three missed runs. What is shown is the last thing the cluster said and may be out of date. |

A cluster goes stale when its CronJob is failing or suspended, when it cannot
reach the server, when it is down, or when it was decommissioned. A stale
cluster stays visible, marked **Stale**, until `REPORT_TTL_DAYS` (7) pass
without a report. Then MongoDB's TTL index deletes its report and it
disappears, so a decommissioned cluster cleans itself up.

## API

Everything is under `/api/v1`. Interactive docs are at `/api/docs`, and the
schema at `/api/openapi.json`.

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /clusters` | anyone | The cluster list: `items` (cards), `total`, `facets` (`sites`, `networks`, `mces`, `versions`) and `counts` per type. Without `type`, every cluster the caller may see. |
| `GET /clusters.csv` | anyone | The same list as a CSV file, with the same filters. Several segments or addresses in one cell are separated by `; `. |
| `GET /clusters/{id}` | anyone | One cluster, with its sections. `id` is the cluster ID or its name. |
| `GET /me` | anyone | The caller's username, roles, the types they may open, their audiences and `loginMode` |
| `POST /ingest/reports` | collectors | Bearer `INGEST_TOKEN` |
| `POST /auth/login` | `dev` | Username and password sign-in |
| `GET /auth/login`, `GET /auth/callback` | `openshift` | Redirect sign-in |
| `POST /auth/logout` | anyone | Clears the session cookie |
| `GET /status` | admin | Cluster counts by state |
| `GET /healthz` (no prefix) | probes | `200`, or `503` when MongoDB is unreachable. Used for readiness. |

List filters, shared by `/clusters` and `/clusters.csv`:

| Parameter | Matches |
|---|---|
| `type` | `generic`, `click`, `mce` or `kubevirt`. `403` if you may not open it. |
| `q` | Part of the cluster name, ignoring case |
| `segment` | An IP, a CIDR, or part of one (see [above](#segments-sites-and-networks)) |
| `network` | The network, exactly |
| `site` | The site, exactly |
| `mce` | The parent MCE, exactly. Matches nothing for a caller who may not see MCEs. |
| `version` | The OpenShift minor version, for example `4.16` |
| `status` | `reporting` or `stale` |

```sh
curl -H 'Authorization: Bearer <token>' 'https://<host>/api/v1/clusters?type=click&network=prod-net'
curl -H 'Authorization: Bearer <token>' 'https://<host>/api/v1/clusters.csv?segment=192.10.0.0/16'
```

## The report and storage

The report is the contract between collector and server: `ClusterReport` in
[report.py](backend/navigator/models/report.py). Both sides import the same
models. On the wire it is camelCase JSON (`clusterId`, `routerLb`, ...).
Unknown fields are ignored on both sides, so a new optional field can ship in
either the collector or the server first. Make new fields optional, and bump
`SCHEMA_VERSION` only for a change an older reader would misread.

MongoDB holds one collection:

| Collection | Document | Indexes |
|---|---|---|
| `reports` | `_id` (the cluster ID), `name`, `baseDomain`, `receivedAt`, `report` (the report as received) | A TTL index on `receivedAt` (`REPORT_TTL_DAYS`). `(name, baseDomain)`, to find the old report of a reinstalled cluster. |

Without `MONGO_URI` the server keeps reports in memory
([store.py](backend/navigator/server/store.py)). That is for tests and quick
local runs only: nothing survives a restart, and nothing expires.

## Code map

| Path | What it is |
|---|---|
| [backend/navigator/models](backend/navigator/models) | The report (`report.py`), the cluster types and their labels (`types.py`), and the camelCase base model. Shared by collector and server. |
| [collector/\_\_main\_\_.py](backend/navigator/collector/__main__.py) | Entry point: reads the environment, collects once, pushes once |
| [collector/collect.py](backend/navigator/collector/collect.py) | Builds the report, one step per fact |
| [collector/detect.py](backend/navigator/collector/detect.py) | The cluster type rules |
| [collector/segments.py](backend/navigator/collector/segments.py) | The Segments Manager lookup and site choice |
| [collector/kube.py](backend/navigator/collector/kube.py) | A minimal read-only Kubernetes client (httpx) |
| [collector/push.py](backend/navigator/collector/push.py) | Delivery to the server, with retries |
| [server/app.py](backend/navigator/server/app.py) | The FastAPI app: every endpoint, caller resolution, `visible()`, serving the UI |
| [server/settings.py](backend/navigator/server/settings.py) | Every server setting, with defaults |
| [server/policy.py](backend/navigator/server/policy.py) | Roles, groups and the `Principal` |
| [server/auth/](backend/navigator/server/auth) | Sign-in providers (`none`, `dev`, `openshift`) and the session cookie |
| [server/merge.py](backend/navigator/server/merge.py) | Reports to cluster list: status, parent MCE, fallbacks |
| [server/sections.py](backend/navigator/server/sections.py) | The details sections and their audiences |
| [server/filters.py](backend/navigator/server/filters.py) | The list filters |
| [server/views.py](backend/navigator/server/views.py) | Response models: card, details, section, `/me` |
| [server/export.py](backend/navigator/server/export.py) | The CSV export |
| [server/store.py](backend/navigator/server/store.py) | MongoDB and in-memory storage |
| [backend/tests](backend/tests) | Collector tests against a fake Kubernetes API, and server tests through the real app |
| [ui/src/api.ts](ui/src/api.ts) | The API types and calls. Mirrors `views.py`. |
| [ui/src/session.tsx](ui/src/session.tsx) | `/me`, sign-in and sign-out |
| [ui/src/hooks.ts](ui/src/hooks.ts) | `useLoad`: loading with the in-memory cache, and background preload |
| [ui/src/components](ui/src/components) | `Layout` (menu), `ClustersPage`, `FilterBar`, `ClusterCard`, `ClusterDetails`, `Sections`, `LoginDialog` |
| [charts/cluster-navigator](charts/cluster-navigator) | Helm chart for the server |
| [charts/cluster-navigator-collector](charts/cluster-navigator-collector) | Helm chart for the collector |
| [deploy/local](deploy/local) | The local stack: compose file, fake fleet, mock Segments Manager, seed |

## Running locally

Needs Docker. Everything runs with fake data: 19 clusters across three sites
and two networks, a stand-in Segments Manager, and two test users.

```sh
cd deploy/local
docker compose up -d --build
```

Open <http://localhost:8100>. The `seed` container plays every collector once:
it looks up each fake cluster's segments in the mock Segments Manager with the
collector's own code, and posts each report through the real ingest endpoint.

| | |
|---|---|
| All clusters | The first menu entry lists every cluster you may see, with a Type filter. |
| Client view | No sign-in. The menu shows Generic and Click Cluster only, and a Click Cluster does not show which MCE it runs under. |
| Admin view | **Sign in** with `admin` / `admin`. MCE and KubeVirt appear in the menu, hosted clusters show their MCE, and an MCE lists the clusters it hosts. |
| A user in no role group | `viewer` / `viewer`. Signs in, stays a client. |
| Cluster details | Press a cluster box. The details open in a window over the page. |
| Filters | **Segment** takes an IP or CIDR, for example `193.51.20.5`. **Network** offers `prod-net` and `lab-net`. One cluster has no network. |
| Stale clusters | Two clusters are back-dated to show the **Stale** chip. |
| Export | **Export CSV** downloads the clusters listed on the page, with the filters applied. |
| API docs | <http://localhost:8100/api/docs> |
| API as a workflow would call it | `curl -H 'Authorization: Bearer local-workflows-token' 'localhost:8100/api/v1/clusters?type=mce'` |
| The same list as CSV | `curl -H 'Authorization: Bearer local-workflows-token' 'localhost:8100/api/v1/clusters.csv?type=click'` |

Stop it with `docker compose down`.

### Development without Docker

```sh
# Server and collector
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest

# Run the server (keeps data in memory unless MONGO_URI is set)
INGEST_TOKEN=dev AUTH_PROVIDER=dev ADMIN_GROUPS='["ocp-admins"]' COOKIE_SECURE=false \
  DEV_USERS='{"admin": {"password": "admin", "groups": ["ocp-admins"]}}' \
  .venv/bin/uvicorn navigator.server.app:app_factory --factory --port 8100

# UI with hot reload, proxying /api to localhost:8100
cd ui && npm install && npm run dev      # http://localhost:4100
```

To try the collector against a real cluster without sending anything, run it
in a pod with the collector's ServiceAccount and `DRY_RUN=true`. It prints the
report it would send.

## Configuration

### Server

Set through the chart, or as environment variables when run by hand. Lists
and maps are JSON. The full list, with defaults, is in
[settings.py](backend/navigator/server/settings.py).

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `DB_NAME` | MongoDB. Without `MONGO_URI` data is kept in memory. |
| `REPORT_TTL_DAYS` | How long a silent cluster's last report is kept. Default 7. |
| `INGEST_TOKEN` | Required. The bearer token collectors send. |
| `AUTH_PROVIDER` | `openshift` (the default; the chart does not set it), or `dev` or `none` for local runs. See [Sign-in](#sign-in-and-auth_provider). |
| `ADMIN_GROUPS` | A JSON list of the OpenShift Groups whose members are admins: `["ocp-admins", "platform-team"]` |
| `ROLES` | More roles, as a JSON object. See [Adding a new kind of user](#adding-a-new-kind-of-user). |
| `<ROLE>_GROUPS` | A JSON list of the groups that grant role `<role>`, for example `STORAGE_GROUPS='["storage-team"]'` |
| `SERVICE_TOKENS` | API tokens for machine callers, as JSON |
| `SESSION_SECRET` | Signs session cookies. Must be the same on every replica. |
| `SESSION_TTL_HOURS` | Session length. Default 12. |
| `GROUP_CACHE_SECONDS` | How long a group lookup is cached. Default 60. |
| `COOKIE_SECURE` | Send cookies over HTTPS only. Default true. Set false for plain-HTTP local runs. |
| `DEV_USERS` | Users for `AUTH_PROVIDER=dev`, as JSON |
| `PUBLIC_URL` | The public base URL, used to build the OAuth callback. The chart sets it from `route.host`. |
| `OPENSHIFT_API_URL`, `OPENSHIFT_CA_FILE` | The API server, and an extra CA to trust for the OAuth route |
| `STALE_AFTER_SECONDS` | How long before a silent cluster is shown as stale. Default 5400. |
| `GRAFANA_URL_TEMPLATE` | Where the **Moby** button on each box points. Placeholders `{name}`, `{domain}`, `{clusterId}`. |
| `UI_DIR` | Where the built UI is. The image sets it. |

### Collector

Set through the collector chart's [values.yaml](charts/cluster-navigator-collector/values.yaml):

| Value | Purpose |
|---|---|
| `navigatorUrl` | Required. The server's Route URL. |
| `ingestToken.value` or `ingestToken.existingSecret` | The ingest token |
| `segmentsManagerUrl` | Segments Manager's URL. Empty: no segments are reported. |
| `network` | The network this cluster belongs to. Empty: none. |
| `clusterType` | `auto` (the default), or `generic`, `click`, `mce`, `kubevirt` to force a type |
| `clusterName` | Overrides the name read from `DNS/cluster` |
| `schedule` | Default every 30 minutes. Keep `staleAfterSeconds` on the server at about three intervals. |
| `tls.caBundle`, `tls.insecureSkipVerify` | TLS towards the server and Segments Manager |
| `dnsPolicy` | `Default`, so the reported DNS servers are the node's. See [Collect](#1-collect-the-collector-in-each-cluster). |

## Deploying

On the redbull platform this is automatic
([.github/workflows/build.yml](.github/workflows/build.yml)). Every push runs
the tests, then builds both images to `ghcr.io/team-redbull/`. A red test
stops the build. On `main`, the new tags are written into the
`cluster-navigator` and `cluster-navigator-collector` charts in
[redbull-platform](https://github.com/team-redbull/redbull-platform)
(`gitops/charts/`), where Argo CD picks them up.

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
  --set ingestToken.value=<the ingest token> \
  --set network=<network name>          # only where a site has several networks
```

Both charts document every option in their `values.yaml`. Under Argo CD, give
the server chart `secret.existingSecret`. Argo renders without cluster access,
so a session secret generated by the chart would change on every sync and
sign everyone out.

## Why it is built this way

- **A CronJob, not an operator.** The old operator had a custom resource with
  a single boolean and no desired state to converge on. It was a timer. A
  CronJob is that timer without the CRD, the leader election, or a pod that
  sits idle.
- **The collector pushes to the server, not to MongoDB.** A cluster then holds
  one bearer token and needs to reach two HTTPS endpoints: the server and
  Segments Manager. The server owns the database, validates every report, and
  stamps the arrival time itself.
- **The collector is read-only.** Its ClusterRole grants `get` and `list` on
  the objects it reports and nothing else. It creates nothing and needs no
  privileged SCC. It reads DNS servers from its own `resolv.conf` instead of
  from a node.
- **Each cluster looks up its own segments.** Segments Manager is asked about
  one cluster, once per run, by that cluster. The server never depends on it.
- **The type is detected, not declared.** A chart parameter alone (Axiom's
  `hostedCluster`) is wrong whenever someone forgets it. A label has the same
  problem. A naming convention breaks on the first cluster that does not
  follow it, and a rename would change the type. `controlPlaneTopology:
  External` is how OpenShift itself marks a hosted control plane. The chart
  parameter remains, as an override.
- **The parent MCE comes from the MCE.** The MCE's own `HostedCluster` list
  is a fact. A name pattern is a guess.
- **Access is applied on the server, and sections carry their audience.** A
  new kind of user is configuration plus, at most, one new section. The UI
  draws what it is sent.
- **The session holds the username, not the role.** Roles come from live
  group membership, so a session cannot outlive the access it was given.

## Known limits and what is not yet verified

Everything above is covered by automated tests and by running the local
stack. These parts have not been run against real infrastructure:

- **The collector on a real OpenShift cluster.** It is tested against a fake
  API with realistic objects. The API paths and field names should be checked
  on one standalone cluster, one hosted cluster and one MCE. Run it with
  `DRY_RUN=true` to print the report without sending it.
- **OpenShift sign-in.** The flow is tested against a fake OAuth server. On a
  real cluster, check that the pod trusts the certificate of the OAuth route.
  If it does not, set `OPENSHIFT_CA_FILE` to a bundle that includes the
  ingress CA.
- **Segments Manager's search response** is taken from its code. The local
  instance had no allocated segments to compare against. Each cluster also
  needs to be able to reach Segments Manager, and to trust its certificate.

Known limits of this first version:

- **One shared ingest token.** Any cluster holding it could send a report
  under another cluster's name. This matches how Segments Manager's API token
  works. Per-cluster tokens would close it.
- **The API docs page** (`/api/docs`) loads its viewer from a public CDN, so
  it does not render at an air-gapped site. The schema itself is served at
  `/api/openapi.json`.
- **No history.** Each report replaces the previous one.
