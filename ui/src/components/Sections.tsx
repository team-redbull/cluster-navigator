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
          <li key={entry} className={`break-all ${item.mono ? "font-mono text-[13px]" : ""}`}>
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

function KeyValues({ section }: { section: Section }) {
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      {section.items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-muted">{item.label}</dt>
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
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
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

function Table({ section }: { section: Section }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-max border-collapse text-left text-sm">
        <caption className="sr-only">{section.title}</caption>
        <thead>
          <tr className="border-b border-line text-xs text-muted">
            {section.columns.map((column) => (
              <th key={column.key} scope="col" className="py-2 pr-6 font-medium last:pr-0">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {section.rows.map((row, index) => (
            <tr key={index} className="border-b border-line last:border-0">
              {section.columns.map((column) => (
                <td key={column.key} className="py-2 pr-6 align-top tabular-nums last:pr-0">
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
  return (
    <section
      aria-labelledby={`section-${section.id}`}
      className={`min-w-0 rounded-[10px] border border-line bg-surface p-4 ${
        section.kind === "table" ? "col-span-full" : ""
      }`}
    >
      <div className="mb-3 flex items-center gap-2">
        <h4 id={`section-${section.id}`} className="text-sm font-semibold">
          {section.title}
        </h4>
        {/* Marks what a client does not get to see. The same black tag as the version. */}
        {restricted && (
          <span className="rounded-[5px] bg-tag px-1.5 py-0.5 text-[11px] font-medium text-on-tag first-letter:uppercase">
            {section.audience} only
          </span>
        )}
      </div>
      <Body section={section} />
    </section>
  );
}
