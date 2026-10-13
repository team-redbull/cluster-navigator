import { Check, Minus } from "lucide-react";
import type { KeyValue, Scalar, Section } from "../api";

/*
  The server describes each section by its kind, so there is one renderer per
  kind here and nothing per section. A section added on the server for a new
  audience shows up without touching this file.
*/

function Cell({ value, mono }: { value: Scalar; mono?: boolean }) {
  if (value === null || value === "") return <span className="text-subtle">-</span>;
  if (typeof value === "boolean") {
    return value ? (
      <span className="inline-flex items-center gap-1 text-ok">
        <Check className="size-4" aria-hidden />
        Yes
      </span>
    ) : (
      <span className="inline-flex items-center gap-1 text-subtle">
        <Minus className="size-4" aria-hidden />
        No
      </span>
    );
  }
  return <span className={mono ? "font-mono text-[13px]" : undefined}>{String(value)}</span>;
}

function Value({ item }: { item: KeyValue }) {
  if (Array.isArray(item.value)) {
    return (
      <ul className="space-y-0.5">
        {item.value.map((entry) => (
          <li key={entry} className={`[overflow-wrap:break-word] ${item.mono ? "font-mono text-[13px]" : ""}`}>
            {entry}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <span className="break-all">
      <Cell value={item.value} mono={item.mono} />
    </span>
  );
}

/** Label above value, one row each: three of these sit side by side, so a value gets the box's full width. */
function KeyValues({ section }: { section: Section }) {
  return (
    <dl className="divide-y divide-line text-sm">
      {section.items.map((item) => (
        <div key={item.label} className="py-2 first:pt-0 last:pb-0">
          <dt className="mb-0.5 text-xs text-subtle">{item.label}</dt>
          <dd className="min-w-0">
            <Value item={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Stats({ section }: { section: Section }) {
  return (
    // As many tiles in a row as fit, so six or seven figures share one row on a wide screen.
    <dl className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-2">
      {section.items.map((item) => (
        <div key={item.label} className="rounded-md bg-surface-2 px-3 py-2">
          <dt className="text-xs text-muted">{item.label}</dt>
          <dd className="font-mono text-lg font-medium tabular-nums">
            {typeof item.value === "number" ? item.value.toLocaleString() : String(item.value ?? "-")}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Cells wrap, so every column fits the window and there is nothing to scroll
 * sideways. A long table scrolls inside its own box, under a header that
 * stays in view, so its last rows and its columns are always in reach.
 */
function Table({ section }: { section: Section }) {
  return (
    <div className="max-h-[26rem] overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">{section.title}</caption>
        <thead>
          <tr className="text-xs text-muted">
            {section.columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className="sticky top-0 whitespace-nowrap border-b border-line bg-surface px-3 py-2 font-medium"
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {section.rows.map((row, index) => (
            <tr key={index} className="hover:bg-surface-2 [&:last-child>td]:border-0">
              {section.columns.map((column) => (
                <td key={column.key} className="border-b border-line px-3 py-2 align-top tabular-nums [overflow-wrap:break-word]">
                  <Cell value={row[column.key] ?? null} mono={column.mono} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Tags({ section }: { section: Section }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {section.tags.map((tag) => (
        <li key={tag} className="rounded-[5px] border border-line bg-surface-2 px-2.5 py-1 font-mono text-[13px]">
          {tag}
        </li>
      ))}
    </ul>
  );
}

const RENDERERS = { kv: KeyValues, stats: Stats, table: Table, tags: Tags } as const;

export function SectionView({ section }: { section: Section }) {
  const Body = RENDERERS[section.kind];
  if (!Body) return null;
  const restricted = section.audience !== "public";
  // Key-value blocks share a row, each one column wide. Figures and tables take the full width.
  const wide = section.kind !== "kv";
  return (
    <section
      aria-labelledby={`section-${section.id}`}
      className={`flex min-w-0 flex-col overflow-hidden rounded-[10px] border border-line bg-surface ${
        wide ? "col-span-full" : ""
      }`}
    >
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <h4 id={`section-${section.id}`} className="text-[13px] font-semibold tracking-wide text-muted uppercase">
          {section.title}
        </h4>
        {/* Marks what a client does not get to see. The same black tag as the version. */}
        {restricted && (
          <span className="rounded-[5px] bg-tag px-1.5 py-0.5 text-[11px] font-medium text-on-tag first-letter:uppercase">
            {section.audience} only
          </span>
        )}
      </div>
      {/* A table runs edge to edge, its cells carry their own padding. */}
      <div className={section.kind === "table" ? "" : "p-4"}>
        <Body section={section} />
      </div>
    </section>
  );
}
