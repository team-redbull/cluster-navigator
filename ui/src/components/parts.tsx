import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { siGrafana, siRedhatopenshift, type SimpleIcon } from "simple-icons";
import { KUBEVIRT_PATHS, KUBEVIRT_VIEWBOX } from "../kubevirt-logo";

/**
 * A product's own logo, in its own brand colour. The shapes come from the
 * simple-icons set and are bundled with the app, so nothing is fetched at
 * run time.
 */
function BrandIcon({ icon }: { icon: SimpleIcon }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill={`#${icon.hex}`} aria-hidden>
      <path d={icon.path} />
    </svg>
  );
}

export const OpenShiftLogo = () => <BrandIcon icon={siRedhatopenshift} />;
export const GrafanaLogo = () => <BrandIcon icon={siGrafana} />;

/**
 * The KubeVirt logo. It sits in the menu beside line icons, so it takes the
 * colour of the text around it, like they do.
 */
export function KubeVirtLogo({ className }: { className?: string }) {
  return (
    <svg viewBox={KUBEVIRT_VIEWBOX} className={className} fill="currentColor" aria-hidden>
      {KUBEVIRT_PATHS.map((path, index) => (
        <path key={index} d={path} />
      ))}
    </svg>
  );
}

/** The OpenShift version tag shown at the top right of a cluster. */
export function VersionBadge({ version }: { version: string | null }) {
  return (
    <span
      className="shrink-0 rounded-[5px] border border-line-strong bg-tag px-2 font-mono text-xs font-medium leading-6 tabular-nums text-on-tag"
      title="OpenShift version"
    >
      {version ?? "unknown"}
    </span>
  );
}

/**
 * Puts text on the clipboard. The Clipboard API exists only on https and
 * localhost, and a site may serve this over plain http, so there is a
 * fallback through a hidden text box.
 */
async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const box = document.createElement("textarea");
  box.value = text;
  box.setAttribute("readonly", "");
  box.style.position = "fixed";
  box.style.opacity = "0";
  document.body.appendChild(box);
  box.select();
  try {
    if (!document.execCommand("copy")) throw new Error("copy refused");
  } finally {
    box.remove();
  }
}

/** A small button that copies a value, and shows a tick for a moment once it has. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={() => copyText(value).then(() => setCopied(true), () => setCopied(false))}
      aria-label={copied ? `Copied ${value}` : `Copy ${label} ${value}`}
      title={copied ? "Copied" : `Copy ${label}`}
      className={`inline-flex size-6 shrink-0 items-center justify-center rounded transition-colors duration-150 hover:bg-surface-2 ${
        copied ? "text-ok" : "text-subtle hover:text-fg"
      }`}
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
    </button>
  );
}

/** A link that leaves the app (the console, Moby). Opens in a new tab. */
export function LinkButton({ href, label, children }: { href: string; label: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={`${label} (opens in a new tab)`}
      className="inline-flex h-10 items-center gap-2 rounded-md border border-line-strong bg-surface px-3.5 text-sm font-medium text-fg transition-colors duration-150 hover:border-subtle"
    >
      {children}
    </a>
  );
}
