import { LoaderCircle, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useSession } from "../session";

/**
 * Username and password sign-in. Built on the native <dialog>, which gives a
 * focus trap, Escape to close and a backdrop without any extra code.
 */
export function LoginDialog() {
  const { loginOpen, closeLogin, completeLogin } = useSession();
  const dialog = useRef<HTMLDialogElement>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (loginOpen && !element.open) {
      setError(null);
      setPassword("");
      element.showModal();
    } else if (!loginOpen && element.open) {
      element.close();
    }
  }, [loginOpen]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      completeLogin(await api.login(username, password));
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      onClose={closeLogin}
      onClick={(event) => event.target === dialog.current && closeLogin()}
      aria-labelledby="login-title"
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-0 text-fg shadow-pop backdrop:bg-black/60"
    >
      <form onSubmit={submit} className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="login-title" className="text-lg font-semibold">
              Sign in
            </h2>
            <p className="mt-1 text-sm text-muted">
              What you see depends on the groups you belong to. Some groups show more clusters, and more
              detail on each one.
            </p>
          </div>
          <button
            type="button"
            onClick={closeLogin}
            aria-label="Close"
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="login-username" className="mb-1.5 block text-sm font-medium">
              Username
            </label>
            <input
              id="login-username"
              className="field"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="login-password" className="mb-1.5 block text-sm font-medium">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              className="field"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && (
            <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={closeLogin} className="btn btn-ghost">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn btn-primary min-w-24">
            {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
            Sign in
          </button>
        </div>
      </form>
    </dialog>
  );
}
