import { LogIn, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { TypeInfo } from "../api";
import logoUrl from "../assets/redbull-logo.png";
import { useSession } from "../session";
import { ALL, ALL_ICON, ALL_LABEL, TYPE_ICONS } from "../types";

const COLLAPSED_KEY = "cn-menu-collapsed";

/** Whether the side menu is minimised. Remembered between visits. */
function useCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // Storage can be unavailable. The menu still toggles for this visit.
      }
      return next;
    });
  }, []);
  return [collapsed, toggle];
}

// An icon-only button on the black menu.
const iconButton =
  "inline-flex size-10 shrink-0 items-center justify-center rounded-md text-rail-muted transition-colors duration-150 hover:bg-rail-hover hover:text-rail-fg";

interface NavEntry {
  id: TypeInfo["id"] | typeof ALL;
  label: string;
}

function NavItem({ type, count, collapsed }: { type: NavEntry; count: number | undefined; collapsed?: boolean }) {
  const Icon = type.id === ALL ? ALL_ICON : TYPE_ICONS[type.id];
  return (
    <NavLink
      to={`/${type.id}`}
      // Minimised, only the icon shows, so the name moves to a tooltip and the accessible label.
      title={collapsed ? type.label : undefined}
      aria-label={collapsed ? type.label : undefined}
      className={({ isActive }) =>
        `group flex h-11 shrink-0 items-center rounded-md text-[14.5px] transition-colors duration-150 ${
          collapsed ? "justify-center px-0" : "gap-3 px-3"
        } ${
          isActive
            ? "bg-brand font-semibold text-on-brand"
            : "font-medium text-rail-muted hover:bg-rail-hover hover:text-rail-fg"
        }`
      }
    >
      <Icon className="size-[18px] shrink-0" aria-hidden />
      {!collapsed && (
        <>
          <span className="flex-1 truncate">{type.label}</span>
          {count !== undefined && (
            <span className="font-mono text-[12.5px] tabular-nums text-rail-subtle group-aria-[current=page]:text-on-brand">
              {count}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

function Account({ collapsed }: { collapsed: boolean }) {
  const { me, signIn, signOut } = useSession();
  if (!me) return null;

  if (!me.authenticated) {
    if (me.loginMode === "disabled") return null;
    return collapsed ? (
      <button type="button" onClick={signIn} className={iconButton} title="Sign in" aria-label="Sign in">
        <LogIn className="size-[18px]" aria-hidden />
      </button>
    ) : (
      <button type="button" onClick={signIn} className="btn btn-rail w-full">
        <LogIn className="size-4" aria-hidden />
        Sign in
      </button>
    );
  }

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => void signOut()}
        className={iconButton}
        title={`Sign out ${me.username ?? ""}`}
        aria-label={`Sign out ${me.username ?? ""}`}
      >
        <LogOut className="size-[18px]" aria-hidden />
      </button>
    );
  }
  return (
    <button type="button" onClick={() => void signOut()} className="btn btn-rail w-full">
      <LogOut className="size-4" aria-hidden />
      Sign out
    </button>
  );
}

/**
 * Who is looking: the signed-in user and the roles their groups give them, or
 * a note that this is the client view. Nothing here assumes the only role is
 * admin, so a role added on the server shows up by name.
 */
function Identity() {
  const { me } = useSession();
  if (!me?.authenticated) return <p className="text-[12.5px] text-rail-subtle">Viewing as client</p>;
  const elevated = me.roles.filter((role) => role !== "client");
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-medium" title={me.username ?? undefined}>
        {me.username}
      </p>
      <p className="text-[12.5px] text-rail-subtle first-letter:uppercase">
        {elevated.length ? elevated.join(", ") : "Client access"}
      </p>
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { me, counts } = useSession();
  const [collapsed, toggleCollapsed] = useCollapsed();
  // The server lists only the cluster types this user may open, so the menu
  // never mentions the others. "All clusters" comes first and covers them all.
  const types: NavEntry[] = me ? [{ id: ALL, label: ALL_LABEL }, ...me.types] : [];
  const totals: Record<string, number | undefined> = { ...counts };
  if (Object.keys(counts).length) {
    totals[ALL] = Object.values(counts).reduce((sum, count) => sum + (count ?? 0), 0);
  }

  const menuLabel = collapsed ? "Expand menu" : "Minimize menu";
  const collapseButton = (
    <button
      type="button"
      onClick={toggleCollapsed}
      aria-label={menuLabel}
      aria-expanded={!collapsed}
      aria-controls="side-menu"
      title={menuLabel}
      className={iconButton}
    >
      {collapsed ? (
        <PanelLeftOpen className="size-[18px]" aria-hidden />
      ) : (
        <PanelLeftClose className="size-[18px]" aria-hidden />
      )}
    </button>
  );

  // The team's mark, the same file the workflows docs use. It is wider than it
  // is tall, so only the height is set and the width follows.
  const logo = <img src={logoUrl} alt="" aria-hidden className="h-[18px] w-auto shrink-0" />;

  return (
    <div className="min-h-dvh lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
      >
        Skip to clusters
      </a>

      {/* Wide screens: a side menu that can be minimised to a strip of icons. */}
      <aside
        id="side-menu"
        className={`rail sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-rail-edge transition-[width] duration-200 ease-out lg:flex ${
          collapsed ? "w-[68px]" : "w-60"
        }`}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-1 pb-1 pt-4">
            <span className="inline-flex h-10 items-center justify-center">{logo}</span>
            {collapseButton}
          </div>
        ) : (
          <div className="px-3 pt-3.5">
            <div className="flex h-11 items-center gap-2.5 pl-3">
              {logo}
              <span className="truncate text-[15.5px] font-semibold">Cluster Navigator</span>
            </div>
            <div className="mt-3 flex h-11 items-center justify-between pl-3">
              <span className="text-[12.5px] text-rail-subtle">Clusters</span>
              {collapseButton}
            </div>
          </div>
        )}

        <nav aria-label="Cluster types" className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-2">
          {types.map((type) => (
            <NavItem key={type.id} type={type} count={totals[type.id]} collapsed={collapsed} />
          ))}
        </nav>

        <div
          className={`border-t border-rail-line ${
            collapsed ? "flex flex-col items-center gap-1 py-3" : "space-y-3 px-3 pb-5 pt-4"
          }`}
        >
          {collapsed ? (
            <Account collapsed />
          ) : (
            <>
              <div className="px-3">
                <Identity />
              </div>
              <Account collapsed={false} />
            </>
          )}
        </div>
      </aside>

      {/* Narrow screens: a top bar with the same destinations as tabs. */}
      <header className="rail sticky top-0 z-30 border-b border-rail-edge lg:hidden">
        <div className="flex h-14 items-center justify-between pl-4 pr-2">
          <div className="flex items-center gap-2.5">
            {logo}
            <span className="text-[15.5px] font-semibold">Cluster Navigator</span>
          </div>
          <MobileAccount />
        </div>
        <nav aria-label="Cluster types" className="flex gap-1 overflow-x-auto px-3 pb-2">
          {types.map((type) => (
            <NavItem key={type.id} type={type} count={totals[type.id]} />
          ))}
        </nav>
      </header>

      <main id="main" className="min-w-0 flex-1">
        {children}
      </main>
    </div>
  );
}

function MobileAccount() {
  const { me, signIn, signOut } = useSession();
  if (!me) return null;
  if (me.authenticated) {
    return (
      <button type="button" onClick={() => void signOut()} className="btn btn-rail px-3" title={me.username ?? ""}>
        <LogOut className="size-4" aria-hidden />
        <span className="max-w-24 truncate">{me.username}</span>
      </button>
    );
  }
  if (me.loginMode === "disabled") return null;
  return (
    <button type="button" onClick={signIn} className="btn btn-rail px-3">
      <LogIn className="size-4" aria-hidden />
      Sign in
    </button>
  );
}
