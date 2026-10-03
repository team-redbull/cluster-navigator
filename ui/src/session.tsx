import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, loginRedirectUrl, type ClusterType, type Me } from "./api";

interface Session {
  me: Me | null;
  loading: boolean;
  error: string | null;
  counts: Partial<Record<ClusterType, number>>;
  setCounts: (counts: Partial<Record<ClusterType, number>>) => void;
  refresh: () => Promise<void>;
  signIn: () => void;
  signOut: () => Promise<void>;
  loginOpen: boolean;
  closeLogin: () => void;
  completeLogin: (me: Me) => void;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [counts, setCounts] = useState<Partial<Record<ClusterType, number>>>({});
  const [loginOpen, setLoginOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your session");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(() => {
    if (me?.loginMode === "redirect") {
      // Sign-in happens on the identity provider's page, then comes back here.
      window.location.assign(loginRedirectUrl(window.location.pathname + window.location.search));
    } else if (me?.loginMode === "password") {
      setLoginOpen(true);
    }
  }, [me?.loginMode]);

  const signOut = useCallback(async () => {
    await api.logout();
    setCounts({});
    await refresh();
  }, [refresh]);

  const value = useMemo<Session>(
    () => ({
      me,
      loading,
      error,
      counts,
      setCounts,
      refresh,
      signIn,
      signOut,
      loginOpen,
      closeLogin: () => setLoginOpen(false),
      completeLogin: (next: Me) => {
        setMe(next);
        setLoginOpen(false);
      },
    }),
    [me, loading, error, counts, refresh, signIn, signOut, loginOpen],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
