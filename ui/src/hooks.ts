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

interface Loaded<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Loads data and reloads it whenever ``key`` changes. A request that is
 * overtaken by a newer one is cancelled, so a slow answer can never replace
 * a fresher one. Existing data stays on screen while a reload is in flight.
 */
export function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>, refreshMs = 0): Loaded<T> {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null; loading: boolean }>({
    key,
    data: null,
    error: null,
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({
      key,
      data: prev.key === key ? prev.data : null,
      error: null,
      loading: true,
    }));
    loadRef.current(controller.signal).then(
      (data) => setState({ key, data, error: null, loading: false }),
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : "Something went wrong";
        setState((prev) => ({ key, data: prev.key === key ? prev.data : null, error: message, loading: false }));
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

  return { data: state.key === key ? state.data : null, loading: state.loading, error: state.error, reload };
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 90) return "just now";
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
