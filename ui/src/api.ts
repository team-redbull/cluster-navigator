// The API contract. Mirrors navigator/server/views.py.

export type ClusterType = "generic" | "click" | "mce" | "kubevirt";
export type ClusterStatus = "reporting" | "stale";
export type LoginMode = "password" | "redirect" | "disabled";

/** A cluster type this user may open. Types they may not open are not sent at all. */
export interface TypeInfo {
  id: ClusterType;
  label: string;
}

export interface Me {
  authenticated: boolean;
  username: string | null;
  roles: string[];
  types: TypeInfo[];
  audiences: string[];
  loginMode: LoginMode;
}

export interface ClusterCard {
  id: string;
  name: string;
  type: ClusterType;
  site: string | null;
  status: ClusterStatus;
  openshiftVersion: string | null;
  segments: string[];
  routerLb: string[];
  /** The control plane runs on an MCE: every Click Cluster, and a KubeVirt cluster that is not standalone. */
  hosted: boolean;
  /** That MCE, when it reports and this user may know it. */
  mce: string | null;
  consoleUrl: string | null;
  grafanaUrl: string | null;
  lastSeen: string | null;
}

export type Scalar = string | number | boolean | null;

export interface KeyValue {
  label: string;
  value: Scalar | string[];
  mono: boolean;
}

export interface Column {
  key: string;
  label: string;
  mono: boolean;
}

export interface Section {
  id: string;
  title: string;
  audience: string;
  kind: "kv" | "stats" | "table" | "tags";
  items: KeyValue[];
  columns: Column[];
  rows: Record<string, Scalar>[];
  tags: string[];
}

export interface ClusterDetail extends ClusterCard {
  sections: Section[];
}

export interface Facets {
  sites: string[];
  mces: string[];
  versions: string[];
}

export interface ClusterList {
  items: ClusterCard[];
  total: number;
  facets: Facets;
  counts: Partial<Record<ClusterType, number>>;
}

export interface ClusterFilters {
  q: string;
  network: string;
  site: string;
  mce: string;
  version: string;
  status: string;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      ...init,
    });
  } catch {
    throw new ApiError(0, "The server is not reachable. Check your connection and try again.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Not JSON: keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** The query string for a cluster list. `type` null means every type the caller may see. */
function listQuery(type: ClusterType | null, filters: ClusterFilters): string {
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return params.toString();
}

/** Where to download the list as a CSV file: the same clusters, with the same filters. */
export function exportUrl(type: ClusterType | null, filters: ClusterFilters): string {
  return `/api/v1/clusters.csv?${listQuery(type, filters)}`;
}

export const api = {
  me: () => request<Me>("/me"),

  clusters: (type: ClusterType | null, filters: ClusterFilters, signal?: AbortSignal) =>
    request<ClusterList>(`/clusters?${listQuery(type, filters)}`, { signal }),

  cluster: (id: string, signal?: AbortSignal) =>
    request<ClusterDetail>(`/clusters/${encodeURIComponent(id)}`, { signal }),

  login: (username: string, password: string) =>
    request<Me>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),
};

export function loginRedirectUrl(returnTo: string): string {
  return `/api/v1/auth/login?return_to=${encodeURIComponent(returnTo)}`;
}
