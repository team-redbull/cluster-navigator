import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ClusterFilters, Facets, TypeInfo } from "../api";
import { useDebounced } from "../hooks";

interface Props {
  filters: ClusterFilters;
  facets: Facets | null;
  showMce: boolean;
  showNetwork: boolean;
  /** Given in the all-clusters view: offers a filter by cluster type. */
  types?: TypeInfo[];
  type?: string;
  onTypeChange?: (type: string) => void;
  onChange: (patch: Partial<ClusterFilters>) => void;
  onClear: () => void;
}

const STATUSES = [
  { value: "reporting", label: "Reporting" },
  { value: "stale", label: "Stale" },
];

/** A text filter that waits for typing to pause before it searches. */
function TextFilter({
  id,
  label,
  value,
  placeholder,
  mono,
  onCommit,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  mono?: boolean;
  onCommit: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const debounced = useDebounced(draft);

  // Follow outside changes: the Clear button, or the browser's back button.
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (debounced !== value) onCommit(debounced);
    // Only react to the debounced text. `value` changing is handled above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-[12.5px] font-medium text-muted">
        {label}
      </label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
        <input
          id={id}
          type="search"
          className={`field pl-9 ${mono ? "font-mono text-[13px]" : ""}`}
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          spellCheck={false}
          autoComplete="off"
        />
      </div>
    </div>
  );
}

function SelectFilter({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-[12.5px] font-medium text-muted">
        {label}
      </label>
      <select id={id} className="field pr-8" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {/* Keep a selected value visible even when it has dropped out of the options. */}
        {value && !options.some((option) => option.value === value) && <option value={value}>{value}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

const plain = (values: string[]) => values.map((value) => ({ value, label: value }));

export function FilterBar({
  filters,
  facets,
  showMce,
  showNetwork,
  types,
  type = "",
  onTypeChange,
  onChange,
  onClear,
}: Props) {
  const active = Object.values(filters).some(Boolean) || Boolean(type);
  return (
    <section aria-label="Filters" className="rounded-[10px] border border-line bg-surface p-3 sm:p-3.5">
      {/* Text filters take the spare width, selects stay compact, and it all wraps on narrow screens. */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-[2_1_10.5rem]">
          <TextFilter
            id="filter-name"
            label="Name"
            value={filters.q}
            placeholder="Cluster name"
            onCommit={(q) => onChange({ q })}
          />
        </div>
        <div className="min-w-0 flex-[2_1_10.5rem]">
          <TextFilter
            id="filter-segment"
            label="Segment"
            value={filters.segment}
            placeholder="IP or CIDR"
            mono
            onCommit={(segment) => onChange({ segment })}
          />
        </div>
        {types && onTypeChange && (
          <div className="min-w-0 flex-[1_1_7rem]">
            <SelectFilter
              id="filter-type"
              label="Type"
              value={type}
              options={types.map((entry) => ({ value: entry.id, label: entry.label }))}
              onChange={onTypeChange}
            />
          </div>
        )}
        {showNetwork && (
          <div className="min-w-0 flex-[1_1_7rem]">
            <SelectFilter
              id="filter-network"
              label="Network"
              value={filters.network}
              options={plain(facets?.networks ?? [])}
              onChange={(network) => onChange({ network })}
            />
          </div>
        )}
        <div className="min-w-0 flex-[1_1_7rem]">
          <SelectFilter
            id="filter-site"
            label="Site"
            value={filters.site}
            options={plain(facets?.sites ?? [])}
            onChange={(site) => onChange({ site })}
          />
        </div>
        {showMce && (
          <div className="min-w-0 flex-[1_1_7rem]">
            <SelectFilter
              id="filter-mce"
              label="MCE"
              value={filters.mce}
              options={plain(facets?.mces ?? [])}
              onChange={(mce) => onChange({ mce })}
            />
          </div>
        )}
        <div className="min-w-0 flex-[1_1_7rem]">
          <SelectFilter
            id="filter-version"
            label="Version"
            value={filters.version}
            options={plain(facets?.versions ?? [])}
            onChange={(version) => onChange({ version })}
          />
        </div>
        <div className="min-w-0 flex-[1_1_7rem]">
          <SelectFilter
            id="filter-status"
            label="Status"
            value={filters.status}
            options={STATUSES}
            onChange={(status) => onChange({ status })}
          />
        </div>
        <button
          type="button"
          onClick={onClear}
          disabled={!active}
          className="btn flex-none px-2.5 text-muted enabled:hover:bg-surface-2 enabled:hover:text-fg"
        >
          <X className="size-4" aria-hidden />
          Clear
        </button>
      </div>
    </section>
  );
}
