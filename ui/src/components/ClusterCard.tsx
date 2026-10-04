import { CircleAlert } from "lucide-react";
import type { MouseEvent } from "react";
import type { ClusterCard as Cluster, ClusterStatus } from "../api";
import { timeAgo } from "../hooks";
import { GrafanaLogo, LinkButton, OpenShiftLogo, VersionBadge } from "./parts";

export const DETAILS_ID = "cluster-details";

const STATUS_NOTE: Partial<Record<ClusterStatus, { label: string; hint: string; tone: string }>> = {
  stale: {
    label: "Stale",
    hint: "The collector has stopped reporting. Details may be out of date.",
    tone: "bg-warn-soft text-warn",
  },
};

/** A one-word fact, such as the cluster's type or network: plain text, not an address. */
function Label({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-20 shrink-0 text-subtle">{label}</dt>
      <dd className="truncate leading-6" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Fact({ label, values, className = "" }: { label: string; values: string[]; className?: string }) {
  return (
    <div className={`flex gap-3 ${className}`}>
      <dt className="w-20 shrink-0 text-subtle">{label}</dt>
      <dd className="min-w-0 font-mono text-[13px] leading-6">
        {values.length ? (
          values.map((value) => (
            <span key={value} className="block truncate" title={value}>
              {value}
            </span>
          ))
        ) : (
          <span className="font-sans text-subtle">Not available</span>
        )}
      </dd>
    </div>
  );
}

interface Props {
  cluster: Cluster;
  /** Set where clusters of several types are listed together, to tell them apart. */
  typeLabel?: string;
  /** Whether this user is told which MCE a hosted cluster runs under. */
  canSeeMce: boolean;
  /** This cluster's details are the ones currently open. */
  selected: boolean;
  onToggle: () => void;
}

/** The cluster box: name, version, segment, router address, parent MCE, network and links. */
export function ClusterCard({ cluster, typeLabel, canSeeMce, selected, onToggle }: Props) {
  const note = STATUS_NOTE[cluster.status];
  // A hosted cluster runs under an MCE, so it shows which one, to those allowed to know.
  const showMce = canSeeMce && cluster.hosted;
  const hasLinks = Boolean(cluster.consoleUrl || cluster.grafanaUrl);

  // Pressing the box opens and closes the details. A press on a link is left
  // alone, and so is a drag that selected text (someone copying an address).
  function onCardClick(event: MouseEvent) {
    if ((event.target as HTMLElement).closest("a, button")) return;
    if (window.getSelection()?.toString()) return;
    onToggle();
  }

  return (
    <article
      data-cluster={cluster.id}
      onClick={onCardClick}
      // A column that fills its grid cell: boxes in one row are the same
      // height even when one has an extra line, and the links stay at the bottom.
      className={`relative flex h-full cursor-pointer flex-col rounded-[10px] border bg-surface px-[18px] pb-4 pt-[18px] transition-colors duration-150 ${
        selected ? "border-primary ring-1 ring-primary" : "border-line hover:border-subtle"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0">
          {/*
            The name is a button only so that keyboard and screen-reader users
            have something to operate. To the mouse it is just part of the box:
            it has no hover effect of its own.
          */}
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={selected}
            aria-controls={DETAILS_ID}
            className="block max-w-full truncate text-left font-mono text-[15px] font-medium text-fg"
            title={cluster.name}
          >
            {cluster.name}
          </button>
        </h3>
        <VersionBadge version={cluster.openshiftVersion} />
      </div>

      {/*
        A status chip sits under the version, in the top right corner. It is
        taken out of the flow so that a box with a chip is exactly the same
        height as one without, and the grid stays even.
      */}
      {note && (
        <p
          className={`absolute right-[18px] top-12 inline-flex items-center gap-1 rounded-[5px] px-[7px] py-0.5 text-xs font-semibold ${note.tone}`}
          title={`${note.hint}${cluster.lastSeen ? ` Last report ${timeAgo(cluster.lastSeen)}.` : ""}`}
        >
          <CircleAlert className="size-3.5" aria-hidden />
          {note.label}
        </p>
      )}

      <dl className="mb-4 mt-3 space-y-1 text-sm">
        {/* Leave room on the first row for the chip beside it. */}
        <Fact label="Segment" values={cluster.segments} className={note ? "pr-16" : ""} />
        <Fact label="Router LB" values={cluster.routerLb} />
        {showMce && <Fact label="MCE" values={cluster.mce ? [cluster.mce] : []} />}
        {/* Only where networks are set: a site with one network has nothing to tell apart. */}
        {cluster.network && <Label label="Network" value={cluster.network} />}
        {typeLabel && <Label label="Type" value={typeLabel} />}
      </dl>

      {hasLinks && (
        <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {cluster.consoleUrl && (
            <LinkButton href={cluster.consoleUrl} label={`OpenShift console for ${cluster.name}`}>
              <OpenShiftLogo />
              Console
            </LinkButton>
          )}
          {cluster.grafanaUrl && (
            <LinkButton href={cluster.grafanaUrl} label={`Moby for ${cluster.name}`}>
              <GrafanaLogo />
              Moby
            </LinkButton>
          )}
        </div>
      )}
    </article>
  );
}
