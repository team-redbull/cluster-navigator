import { CircleAlert, RefreshCw, X } from "lucide-react";
import { Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { ClustersPage } from "./components/ClustersPage";
import { Layout } from "./components/Layout";
import { LoginDialog } from "./components/LoginDialog";
import { useSession } from "./session";
import { ALL } from "./types";

function LoginFailedBanner() {
  const [params, setParams] = useSearchParams();
  if (params.get("login") !== "failed") return null;
  const dismiss = () =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("login");
        return next;
      },
      { replace: true },
    );
  return (
    <div role="alert" className="flex items-center gap-3 bg-danger-soft px-4 py-3 text-sm text-danger sm:px-6">
      <CircleAlert className="size-4 shrink-0" aria-hidden />
      <span className="flex-1">Sign-in did not complete. Try again, and contact the platform team if it keeps failing.</span>
      <button type="button" onClick={dismiss} aria-label="Dismiss" className="inline-flex size-9 items-center justify-center rounded-md hover:bg-danger/10">
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}

function Home() {
  const [params] = useSearchParams();
  // Keep ?login=failed across the redirect so the banner can show it.
  const query = params.get("login") ? `?login=${params.get("login")}` : "";
  return <Navigate to={`/${ALL}${query}`} replace />;
}

export function App() {
  const { me, loading, error, refresh } = useSession();

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" aria-busy="true" aria-label="Loading">
        <RefreshCw className="size-6 animate-spin text-subtle" aria-hidden />
      </div>
    );
  }

  if (!me) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <div role="alert" className="max-w-sm text-center">
          <CircleAlert className="mx-auto size-8 text-danger" aria-hidden />
          <h1 className="mt-3 text-lg font-semibold">Cluster Navigator is not reachable</h1>
          <p className="mt-1 text-sm text-muted">{error}</p>
          <button type="button" onClick={() => void refresh()} className="btn btn-primary mt-5">
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <Layout>
      <LoginFailedBanner />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/:type" element={<ClustersPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <LoginDialog />
    </Layout>
  );
}
