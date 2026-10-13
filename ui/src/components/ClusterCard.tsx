import { CircleAlert, CircleCheck, CircleX, type LucideIcon } from "lucide-react";
import type { MouseEvent } from "react";
import type { ClusterCard as Cluster, ClusterStatus } from "../api";
import { timeAgo } from "../hooks";
import { GrafanaLogo, LinkButton, OpenShiftLogo, VersionBadge } from "./parts";

export const DETAILS_ID = "cluster-details";

const STATUS_CHIP: Record<ClusterStatus, { label: string; hint: string; tone: string; Icon: LucideIcon }> = {
  available: {
    label: "Available",
    hint: "The console answers and the collector reports.",
    tone: "bg-ok-soft text-ok",
    Icon: CircleCheck,
  },
  down: {
    label: "Down",
    hint: "The console does not answer, but the collector still reports.",
    tone: "bg-danger-soft text-danger",
    Icon: CircleX,
  },
  "not-reporting": {
    label: "Not reporting",
    hint: "The collector has stopped reporting. Details may be out of date.",
    tone: "bg-warn-soft text-warn",
    Icon: CircleAlert,
  },
};

export function StatusChip({ status, lastSeen }: { status: ClusterStatus; lastSeen: string | null }) {
  const { label, hint, tone, Icon } = STATUS_CHIP[status];
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-0.5 text-xs font-semibold ${tone}`}
      title={`${hint}${lastSeen ? ` Last report ${timeAgo(lastSeen)}.` : ""}`}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </span>
  );
}

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

function Fact({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="flex gap-3">
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
      className={`flex h-full cursor-pointer flex-col rounded-[10px] border bg-surface px-[18px] pb-4 pt-[18px] transition-colors duration-150 ${
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
        {/* The status above the version, in the top right corner. Every box has both, so the grid stays even. */}
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusChip status={cluster.status} lastSeen={cluster.lastSeen} />
          <VersionBadge version={cluster.openshiftVersion} />
        </div>
      </div>

      <dl className="mb-4 mt-3 space-y-1 text-sm">
        <Fact label="Segment" values={cluster.segments} />
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
