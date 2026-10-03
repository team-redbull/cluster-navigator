# Architecture

This document explains how Cluster Navigator is put together and why.

## Contents

- [Where the data comes from](#where-the-data-comes-from)
- [The collector](#the-collector)
- [How the cluster type is decided](#how-the-cluster-type-is-decided)
- [Who sees what](#who-sees-what)
- [Adding a new kind of user](#adding-a-new-kind-of-user)
- [Sign-in](#sign-in)
- [API](#api)
- [Storage](#storage)
- [Not yet verified](#not-yet-verified)

## Where the data comes from

**Everything comes from the collector in each cluster.** A cluster appears
once its collector has sent a report, and not before. The server talks to
nothing but its database.

The report holds two kinds of fact:

| Fact | Where the collector gets it |
|---|---|
| Version, nodes, capacity, router and API addresses, DNS, storage classes, identity providers, cluster type, and (on an MCE) the clusters it hosts | The cluster's own APIs |
| The cluster's segments, with VLAN, EPG and site | Segments Manager, asked once per run for this cluster's name |

Rules the server applies when it builds the list
([merge.py](backend/navigator/server/merge.py)):

- The box shows the cluster-facing segments (types `UPI`, `HC`, `MCE`,
  `HUB`). Inventory and PXE segments appear in the details.
- **The parent MCE is never guessed from a name.** Each MCE's collector lists
  the `HostedCluster` objects it runs, and the server links them. Admins see
  that list on the MCE, including whether each hosted cluster's own collector
  is reporting.
- A hosted cluster's version and identity providers fall back to what its MCE
  reports, since both are configured on the MCE.

### Reporting and stale

Every cluster is in one of two states:

| State | Meaning |
|---|---|
| **Reporting** | Its collector sent a report within the last 90 minutes. What is shown is current. |
| **Stale** | No report for more than 90 minutes, which is three missed runs. What is shown is the last thing the cluster said and may be out of date. |

A cluster goes stale when its CronJob is failing or suspended, when the
cluster cannot reach the server, when the cluster is down, or when it was
decommissioned. The threshold is `STALE_AFTER_SECONDS`.

A stale cluster stays visible, marked **Stale**, for 7 days. If no report
arrives in that time it is deleted, so a decommissioned cluster disappears by
itself.

## The collector

**A CronJob, not an operator.** The old operator had a custom resource with a
single boolean and no desired state to converge on. It was a timer. A CronJob
is that timer without the CRD, the leader election or a pod that sits idle:

- every 30 minutes it starts, collects, sends one report and exits
- `concurrencyPolicy: Forbid` stops runs piling up
- a failed run stays visible as a failed Job, and the next tick is the retry

**It pushes to the server, not to MongoDB.** Clusters hold one bearer token
and need to reach two HTTPS endpoints: the server and Segments Manager. The server owns the database, validates
every report, and stamps the arrival time itself.

**It is read-only.** The ClusterRole grants `get` and `list` on the objects it
reports and nothing else. It creates no pods and needs no privileged SCC.

**Each fact is collected independently.** A step that fails (a missing
permission, a DNS lookup) is recorded in the report's `errors` list, which is
stored with the report but not shown in the UI. The rest of the report is
still sent.

**DNS servers without a privileged pod.** The CronJob runs with
`dnsPolicy: Default`, so its own `/etc/resolv.conf` is the node's. The
collector reads that file. A side effect: in-cluster Service names do not
resolve in the collector pod, so `navigatorUrl` must be a Route hostname.

**It looks up its own segments.** Each run asks Segments Manager
(`GET /api/segments/search?q=<cluster name>&status=Allocated`) and keeps the
segments whose cluster name matches exactly
([segments.py](backend/navigator/collector/segments.py)). So Segments Manager
is asked about one cluster, once per run, by that cluster. Two details:

- If the same cluster name exists at two sites, the collector picks the site
  whose segment contains its own node addresses.
- If Segments Manager cannot be reached, the failure is recorded in the
  report and the server keeps the segments from the cluster's previous
  report, so one bad run does not blank them out. A successful lookup that
  finds nothing does clear them.

This needs a network path from every cluster to Segments Manager.

What it reads:

| Fact | From |
|---|---|
| Cluster ID, OpenShift version | `ClusterVersion/version` (version = newest completed update) |
| Name, base domain | `DNS/cluster` `.spec.baseDomain` |
| Topology, API URL, platform | `Infrastructure/cluster` |
| Console URL | `Console/cluster` |
| Router and API addresses | DNS lookup of the console and API hostnames |
| Nodes and capacity | `Node` list (addresses read by type, never by position) |
| Storage classes | `StorageClass` list |
| Identity providers | `OAuth/cluster` |
| Hosted clusters (MCE only) | `HostedCluster` and `NodePool` |
| Segments and site | Segments Manager |

## How the cluster type is decided

The collector works it out from the cluster's own APIs. Nobody has to declare
it at install time, which is the mistake that is easy to make and silent when
made. The rules live in one function,
[detect.py](backend/navigator/collector/detect.py), and are checked in order:

| # | Signal | Type |
|---|---|---|
| 1 | `clusterType` set in the chart | whatever was set |
| 2 | A `MultiClusterEngine` object exists | **MCE** |
| 3 | A `HyperConverged` object exists (OpenShift Virtualization) | **KubeVirt** |
| 4 | `Infrastructure/cluster` has `controlPlaneTopology: External` | **Click Cluster** |
| 5 | none of the above | **Generic** |

Why this and not the alternatives:

- **A chart parameter alone** is what Axiom had (`hostedCluster`). It is wrong
  whenever someone forgets it. It is kept only as an override.
- **A label on some object** has the same problem: a person must set it.
- **Inferring from the name** breaks on the first cluster that does not follow
  the convention, and a rename would change its type.
- **First-class APIs** are facts about the cluster that cannot drift.
  `controlPlaneTopology: External` is how OpenShift itself marks a hosted
  control plane.

The signals behind each decision are stored with the report, so a wrong type
can be traced to the rule that produced it.

**KubeVirt means a cluster that has OpenShift Virtualization installed.** Two
things follow from that:

- A KubeVirt cluster can be standalone or hosted. Whether it is hosted is read
  from its control plane, not from its type. A hosted one shows its MCE the way
  a Click Cluster does. A standalone one has no MCE line.
- Installing OpenShift Virtualization changes a cluster's type. A cluster that
  was Generic or Click Cluster becomes KubeVirt on its next report. Clients do
  not see KubeVirt, so that cluster leaves the client view. An MCE hub stays an
  MCE, because that rule is checked first.

## Who sees what

Access is decided on the server, in one file:
[policy.py](backend/navigator/server/policy.py). Data a caller may not see is
never sent to the browser.

A **role** grants two things:

- **cluster types** it may list and open
- **audiences**, which are tags on the sections of a cluster's expanded view

| Role | Who | Cluster types | Audiences |
|---|---|---|---|
| `client` | everyone, signed in or not | Generic, Click Cluster | `public` |
| `admin` | members of `ADMIN_GROUPS` | all four | all |

Every section of the expanded view is declared in
[sections.py](backend/navigator/server/sections.py) with its audience:

| Section | Audience |
|---|---|
| Overview, Network, Capacity, Identity providers, Segments, Nodes, Storage classes | `public` |
| Hosted clusters | `admin` |

The server also tells the UI how to draw each section (a key-value list, a
row of numbers, a table, or tags). The UI has one renderer per shape and no
knowledge of individual sections.

The menu works the same way. The server sends only the cluster types the
caller may open, and the UI builds the menu from that list. A client is never
shown, or told about, MCE and KubeVirt. They appear after an admin signs in.

One more rule follows from the cluster types: **a caller who may not open MCE
clusters is not told which MCE a hosted cluster runs under**, because that
would name a cluster they may not see. For a client the parent MCE is left out
of the box, the details, the filter options and the CSV export, and filtering
by an MCE name returns nothing. The server removes it in one place, where
every endpoint reads the cluster list, so a new endpoint inherits the rule.

A cluster the caller may not see answers `404`, the same as one that does not
exist.

## Adding a new kind of user

Say a storage team should see an extra *Storage backend* section on every
cluster.

1. **Write the section**, in `sections.py`, with a new audience name:

   ```python
   def _storage_backend(d, c, now): ...
   SectionDef("storageBackend", "Storage backend", "storage", _storage_backend),
   ```

2. **Define the role and its groups**, in configuration:

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

   or as environment variables: `ROLES='{"storage": {...}}'` and
   `STORAGE_GROUPS=storage-team`.

No UI change is needed. Admins see the new section too, because the admin
role holds every audience. A user in several groups gets the union of their
roles.

## Sign-in

Anonymous visitors are clients. Signing in can only add access.

**In production: log in with OpenShift** (`AUTH_PROVIDER=openshift`). This is
the same experience as the Temporal UI: the user is sent to the cluster's own
login page and types LDAP credentials there. The difference is where it is
done. Temporal puts an oauth-proxy sidecar in front of the whole UI, which
cannot let anonymous clients through. Here the server runs the OAuth flow
itself ([openshift.py](backend/navigator/server/auth/openshift.py)):

1. The browser is redirected to the cluster's OAuth server.
2. The server's ServiceAccount is the OAuth client. An annotation on it allows
   the Route as the redirect target. No `OAuthClient` object is needed.
3. The server exchanges the returned code for a token and uses it once, to
   ask the API for the username. It never sees a password.
4. It then reads the OpenShift `Group` objects named in `ADMIN_GROUPS` with
   its own token and checks whether the user is a member.

Prerequisite, same as for Temporal: the OpenShift Groups must exist. On an
LDAP-backed cluster they are created by `oc adm groups sync` or the
group-sync operator, not by the login. Check with
`oc get group <name> -o jsonpath='{.users}'`.

Group membership is cached for 60 seconds and re-checked on every request.
The session cookie holds only the username, never the role. Removing someone
from the group therefore takes their admin view away within a minute, even
mid-session. If the API cannot be reached and nothing is cached, the user is
treated as a client.

The chart grants the server `get` on exactly the listed Groups and nothing
else.

**Locally: `AUTH_PROVIDER=dev`**, with fixed users from `DEV_USERS`.

**Machine callers** (the workflows) send `Authorization: Bearer <token>` with
a token from `SERVICE_TOKENS`, which maps each token to roles.

Adding another provider, for example the `redbull-ldap` checker, means
implementing one small class
([base.py](backend/navigator/server/auth/base.py)): it says who the user is
and which groups they are in. Roles and views are untouched.

## API

All under `/api/v1`. Interactive docs at `/api/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /clusters` | List. Filters: `type`, `q`, `site`, `mce`, `network`, `version`, `status`. Without `type` it lists every cluster the caller may see, which is what the UI's "All clusters" view shows. Returns the cards, the filter options, and a count per type. |
| `GET /clusters.csv` | The same list as a CSV file, with the same filters. Columns: `name`, `version`, `segment`, `router_lb`, and `mce` only for callers who may see it. Several segments or addresses in one cell are separated by `; `. |
| `GET /clusters/{id}` | One cluster with its sections. `id` may be the cluster ID or its name. |
| `GET /me` | The caller's roles, the cluster types they may open, and how to sign in. |
| `POST /ingest/reports` | Collectors only. Bearer `INGEST_TOKEN`. |
| `POST /auth/login`, `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout` | Sign-in. |
| `GET /status` | Admin only. Cluster counts by state. |

The `network` filter accepts an IP address (finds the cluster whose segment
contains it, or that uses it as a router, API or node address), a CIDR
(finds clusters with an overlapping segment), or a fragment such as
`192.10.5`.

## Storage

MongoDB, one collection:

| Collection | Holds |
|---|---|
| `reports` | The latest report per cluster, keyed by cluster ID. A TTL index deletes reports not refreshed for `REPORT_TTL_DAYS`. A reinstalled cluster (same name, new ID) replaces its old report. |

The cluster list is built from the reports on read and cached for three
seconds. Nothing derived is stored.

## Not yet verified

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
  it does not render in an air-gapped site. The schema itself is served at
  `/api/openapi.json`.
- **No history.** Each report replaces the previous one.
