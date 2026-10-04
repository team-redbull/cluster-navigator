import { CircleAlert, RefreshCw, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { api, type ClusterCard as Cluster } from "../api";
import { useLoad } from "../hooks";
import { useSession } from "../session";
import { DETAILS_ID } from "./ClusterCard";
import { GrafanaLogo, LinkButton, OpenShiftLogo, VersionBadge } from "./parts";
import { SectionView } from "./Sections";

interface Props {
  id: string;
  /** What the list already knows, shown at once while the rest loads. */
  cluster: Cluster | undefined;
  onClose: () => void;
}

/**
 * A cluster's details, in a window over the page. The grid behind it does
 * not move. Built on the native <dialog>, which traps focus, closes on
 * Escape, and puts focus back where it was when it closes.
 */
export function ClusterDetails({ id, cluster, onClose }: Props) {
  const { viewer } = useSession();
  const { data, loading, error, reload } = useLoad(`cluster|${id}|${viewer}`, (signal) => api.cluster(id, signal));
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const shown = data ?? cluster;

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    // Start on the title, not on the first button, so nothing looks pre-selected.
    title.current?.focus({ preventScroll: true });
  }, []);

  // Closing goes through the dialog itself. Its `close` event then tells us.
  const requestClose = () => dialog.current?.close();

  return (
    <dialog
      ref={dialog}
      id={DETAILS_ID}
      onClose={onClose}
      // A press on the dimmed page around the window closes it.
      onClick={(event) => event.target === dialog.current && requestClose()}
      aria-label={`Details for ${shown?.name ?? "cluster"}`}
      className="m-auto max-h-[calc(100dvh-3rem)] w-[min(76rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-line bg-surface p-0 text-fg shadow-pop backdrop:bg-black/60 open:flex"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-3">
        <h2
          ref={title}
          tabIndex={-1}
          className="min-w-0 truncate font-mono text-base font-medium outline-none"
          title={shown?.name}
        >
          {shown?.name ?? "Cluster"}
        </h2>
        {shown && <VersionBadge version={shown.openshiftVersion} />}
        <div className="ml-auto flex items-center gap-2">
          {shown?.consoleUrl && (
            <LinkButton href={shown.consoleUrl} label={`OpenShift console for ${shown.name}`}>
              <OpenShiftLogo />
              Console
            </LinkButton>
          )}
          {shown?.grafanaUrl && (
            <LinkButton href={shown.grafanaUrl} label={`Moby for ${shown.name}`}>
              <GrafanaLogo />
              Moby
            </LinkButton>
          )}
          <button
            type="button"
            onClick={requestClose}
            aria-label="Close details"
            title="Close"
            className="inline-flex size-10 items-center justify-center rounded-md text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-fg"
          >
            <X className="size-[18px]" aria-hidden />
          </button>
        </div>
      </div>

      <div className="overflow-y-auto bg-bg p-5">
        {error && !data ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[10px] bg-danger-soft px-4 py-3 text-sm text-danger">
            <CircleAlert className="size-4 shrink-0" aria-hidden />
            <span className="flex-1">Could not load the details. {error}</span>
            <button type="button" onClick={reload} className="btn btn-ghost h-9">
              <RefreshCw className="size-4" aria-hidden />
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading details">
            {[0, 1, 2].map((index) => (
              <div key={index} className="skeleton h-36" />
            ))}
          </div>
        ) : (
          <div className="grid grid-flow-row-dense items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data?.sections.map((section) => (
              <SectionView key={section.id} section={section} />
            ))}
          </div>
        )}
      </div>
    </dialog>
  );
}
