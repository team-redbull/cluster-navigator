import { CircleAlert, Download, RefreshCw, SearchX } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, exportUrl, listQuery, type ClusterFilters, type ClusterType } from "../api";
import { preload, useLoad } from "../hooks";
import { useSession } from "../session";
import { ALL, ALL_LABEL } from "../types";
import { ClusterCard } from "./ClusterCard";
import { ClusterDetails } from "./ClusterDetails";
import { FilterBar } from "./FilterBar";

const FILTER_KEYS = ["q", "segment", "network", "site", "mce", "version", "status", "type"] as const;
// The list reloads by itself this often while the page is in view, so there is no refresh button.
const REFRESH_MS = 60_000;
const NO_FILTERS: ClusterFilters = { q: "", segment: "", network: "", site: "", mce: "", version: "", status: "" };

/** The cache key of one list: the page, the query, and who is looking. */
function listKey(page: string | undefined, type: ClusterType | null, filters: ClusterFilters, viewer: string): string {
  return `clusters|${page}|${listQuery(type, filters)}|${viewer}`;
}

function Message({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: typeof SearchX;
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center rounded-[10px] border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
      <Icon className="size-6 text-subtle" aria-hidden />
      <h3 className="mt-3 text-base font-semibold">{title}</h3>
      <p className="mt-1 text-sm text-muted">{children}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ClustersPage() {
  const { type: typeParam } = useParams();
  const { me, viewer, setCounts, counts, refresh } = useSession();
  const [params, setParams] = useSearchParams();

  // The page is either one cluster type, or "all": every type this user may
  // open, with an extra filter to narrow by type. `me.types` holds only the
  // types this user may open.
  const isAll = typeParam === ALL;
  const typeInfo = me?.types.find((entry) => entry.id === (isAll ? params.get("type") : typeParam));
  const type: ClusterType | null = typeInfo?.id ?? null;
  const labels = useMemo(() => new Map(me?.types.map((entry) => [entry.id, entry.label])), [me?.types]);
  // The server names a hosted cluster's MCE only to those who may open MCE
  // clusters. For everyone else the MCE line and the MCE filter are left out.
  const canSeeMce = Boolean(me?.types.some((entry) => entry.id === "mce"));

  // Filters and the open cluster live in the URL, so a view can be shared,
  // bookmarked, and survives a reload or the back button.
  const filters = useMemo<ClusterFilters>(
    () => ({
      q: params.get("q") ?? "",
      segment: params.get("segment") ?? "",
      network: params.get("network") ?? "",
      site: params.get("site") ?? "",
      // A link shared by an admin may carry an MCE filter this user cannot use.
      mce: canSeeMce ? (params.get("mce") ?? "") : "",
      version: params.get("version") ?? "",
      status: params.get("status") ?? "",
    }),
    [params, canSeeMce],
  );
  const open = params.get("open");

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(patch)) {
            if (value) next.set(key, value);
            else next.delete(key);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const key = listKey(typeParam, type, filters, viewer);
  const { data, loading, error, reload } = useLoad(
    key,
    async (signal) => {
      if (!type && !isAll) return null;
      try {
        return await api.clusters(type, filters, signal);
      } catch (err) {
        // Access was lost while the page was open (signed out elsewhere, or
        // removed from the group). Reload who we are; the menu and this page follow.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) void refresh();
        throw err;
      }
    },
    REFRESH_MS,
  );

  useEffect(() => {
    if (data) setCounts(data.counts);
  }, [data, setCounts]);

  // Once this page has its data, load every menu entry in the background, so
  // the first visit to each is instant as well. Each refreshes when visited.
  const loaded = data !== null;
  useEffect(() => {
    if (!me || !loaded) return;
    for (const page of [ALL, ...me.types.map((entry) => entry.id)]) {
      const pageType = page === ALL ? null : (page as ClusterType);
      preload(listKey(page, pageType, NO_FILTERS, viewer), () => api.clusters(pageType, NO_FILTERS));
    }
  }, [me, viewer, loaded]);

  if (!me) return null;
  if (!isAll && !type) {
    // Not a type this user can open (or not a type at all): go to the full list.
    return <Navigate to={`/${ALL}`} replace />;
  }

  const openCluster = data?.items.find((cluster) => cluster.id === open);
  const close = () => {
    const closing = open;
    update({ open: null });
    // Put keyboard focus back on the box the details belonged to.
    if (closing) {
      requestAnimationFrame(() =>
        document
          .querySelector<HTMLElement>(`[data-cluster="${CSS.escape(closing)}"] h3 button`)
          ?.focus({ preventScroll: true }),
      );
    }
  };
  const heading = isAll ? ALL_LABEL : typeInfo!.label;
  // The MCE filter is offered where there is an MCE to choose: on any page that lists hosted clusters.
  const showMce = canSeeMce && (Boolean(data?.facets.mces.length) || Boolean(filters.mce));
  // Networks are set per cluster only at sites that run several. Elsewhere there is nothing to choose.
  const showNetwork = Boolean(data?.facets.networks.length) || Boolean(filters.network);
  const total = isAll
    ? Object.values(counts).reduce((sum, count) => sum + (count ?? 0), 0)
    : counts[type!];
  const filtered = Object.values(filters).some(Boolean) || (isAll && Boolean(type));

  return (
    <div className="mx-auto max-w-[1800px] space-y-[18px] p-4 sm:px-8 sm:py-7">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h1 className="text-[26px] font-semibold leading-9 tracking-tight">{heading}</h1>
        <div className="flex items-center gap-2">
          <p className="mr-1 text-sm tabular-nums text-muted" aria-live="polite">
            {data
              ? filtered && total !== undefined
                ? `${data.total} of ${total} clusters`
                : `${data.total} ${data.total === 1 ? "cluster" : "clusters"}`
              : " "}
          </p>
          {/* The file holds the clusters listed below: the same type and the same filters. */}
          {data && data.total > 0 && (
            <a href={exportUrl(type, filters)} download className="btn btn-ghost px-3.5">
              <Download className="size-4" aria-hidden />
              Export CSV
            </a>
          )}
        </div>
      </header>

      <FilterBar
        filters={filters}
        facets={data?.facets ?? null}
        showMce={showMce}
        showNetwork={showNetwork}
        types={isAll ? me.types : undefined}
        type={isAll ? (type ?? "") : undefined}
        onTypeChange={(next) => update({ type: next, open: null })}
        onChange={(patch) => update({ ...patch, open: null })}
        onClear={() => update(Object.fromEntries([...FILTER_KEYS, "open"].map((name) => [name, null])))}
      />

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[10px] bg-danger-soft px-4 py-3 text-sm text-danger">
          <CircleAlert className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">
            {data ? "Could not refresh. Showing the last loaded data." : "Could not load clusters."} {error}
          </span>
          <button type="button" onClick={reload} className="btn btn-ghost h-9">
            <RefreshCw className="size-4" aria-hidden />
            Try again
          </button>
        </div>
      )}

      {!data && loading ? (
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3 min-[1800px]:grid-cols-4" aria-busy="true" aria-label="Loading clusters">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="rounded-[10px] border border-line bg-surface p-[18px]">
              <div className="flex justify-between">
                <div className="skeleton h-5 w-48" />
                <div className="skeleton h-5 w-14" />
              </div>
              <div className="skeleton mt-5 h-4 w-56" />
              <div className="skeleton mt-2 h-4 w-44" />
              <div className="skeleton mt-6 h-10 w-full" />
            </div>
          ))}
        </div>
      ) : data && data.items.length === 0 ? (
        filtered ? (
          <Message
            icon={SearchX}
            title="No clusters match these filters"
            action={
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => update(Object.fromEntries([...FILTER_KEYS, "open"].map((name) => [name, null])))}
              >
                Clear filters
              </button>
            }
          >
            Try a different name or segment, or widen the other filters.
          </Message>
        ) : (
          <Message icon={SearchX} title={isAll ? "No clusters yet" : `No ${heading} clusters yet`}>
            A cluster appears here once its collector sends a first report.
          </Message>
        )
      ) : (
        // auto-rows-fr: every row is as tall as the tallest, so all boxes are one size.
        <div className="grid auto-rows-fr gap-3.5 sm:grid-cols-2 xl:grid-cols-3 min-[1800px]:grid-cols-4">
          {data?.items.map((cluster) => (
            <ClusterCard
              key={cluster.id}
              cluster={cluster}
              typeLabel={isAll ? labels.get(cluster.type) : undefined}
              canSeeMce={canSeeMce}
              selected={open === cluster.id}
              onToggle={() => update({ open: open === cluster.id ? null : cluster.id })}
            />
          ))}
        </div>
      )}

      {open && <ClusterDetails key={open} id={open} cluster={openCluster} onClose={close} />}
    </div>
  );
}
