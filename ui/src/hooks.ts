import { useCallback, useEffect, useRef, useState } from "react";

/** Returns ``value`` once it has stopped changing for ``delay`` milliseconds. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/*
  The last answer for each key, newest last. A view seen before shows at once
  from here and refreshes in the background, so moving between menu entries
  does not wait on the network. Keys carry who is looking (see `viewer` in
  session.tsx), so an answer is only ever reused for the same access.
*/
const cache = new Map<string, unknown>();
const CACHE_SIZE = 50;

function remember(key: string, data: unknown) {
  cache.delete(key);
  cache.set(key, data);
  if (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value as string);
}

function cached<T>(key: string): T | null {
  return (cache.get(key) as T | undefined) ?? null;
}

/** Forget every cached answer, for example on sign-out. */
export function clearLoadCache(): void {
  cache.clear();
}

const preloading = new Set<string>();

/** Load into the cache ahead of time, so the first visit is instant too. Skips keys already cached or on their way. */
export function preload<T>(key: string, load: () => Promise<T>): void {
  if (cache.has(key) || preloading.has(key)) return;
  preloading.add(key);
  load()
    .then(
      (data) => remember(key, data),
      () => undefined, // The visit itself will load it, and show any error then.
    )
    .finally(() => preloading.delete(key));
}

interface Loaded<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Loads data and reloads it whenever ``key`` changes. A request that is
 * overtaken by a newer one is cancelled, so a slow answer can never replace
 * a fresher one. Existing data stays on screen while a reload is in flight,
 * and a key loaded before starts from its cached answer.
 */
export function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>, refreshMs = 0): Loaded<T> {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null; loading: boolean }>(() => ({
    key,
    data: cached<T>(key),
    error: null,
    loading: true,
  }));
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({
      key,
      data: prev.key === key ? prev.data : cached<T>(key),
      error: null,
      loading: true,
    }));
    loadRef.current(controller.signal).then(
      (data) => {
        remember(key, data);
        setState({ key, data, error: null, loading: false });
      },
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : "Something went wrong";
        setState((prev) => ({ key, data: prev.key === key ? prev.data : cached<T>(key), error: message, loading: false }));
      },
    );
    return () => controller.abort();
  }, [key, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    if (!refreshMs) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs, reload]);

  // Right after `key` changes, before the effect above runs, show the cached answer, not a blank.
  return { data: state.key === key ? state.data : cached<T>(key), loading: state.loading, error: state.error, reload };
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 90) return "just now";
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
