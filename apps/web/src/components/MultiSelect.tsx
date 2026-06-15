"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

type Option = { value: string; label: string };

type Props = {
  label: string;
  options: Option[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  className?: string;
};

/**
 * Compact multiselect dropdown with checkboxes. Shows a summary ("Tümü",
 * "N seçili", or a single label) on the trigger button and a checkbox list in
 * the popover. Keeps at least one option selected so the consumer never has to
 * handle an empty selection, and closes on outside click.
 */
export function MultiSelect({ label, options, selected, onChange, className }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent): void {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const allSelected = options.length > 0 && selected.size >= options.length;
  const summary =
    selected.size === 0
      ? "Hiçbiri"
      : allSelected
        ? "Tümü"
        : selected.size === 1
          ? (options.find((o) => selected.has(o.value))?.label ?? "1 seçili")
          : `${selected.size} seçili`;

  const toggle = (value: string): void => {
    const next = new Set(selected);
    if (next.has(value)) {
      next.delete(value);
    } else {
      next.add(value);
    }
    onChange(next);
  };

  return (
    <div ref={ref} className={cn("relative", className)}>
      <label htmlFor={id} className="text-xs text-ink-muted">
        {label}
      </label>
      <button
        id={id}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="mt-1 flex w-full items-center justify-between gap-2 rounded-xl border border-surface-border bg-white px-3 py-2 text-sm outline-none transition-all focus:border-indigo-400 focus:shadow-ring"
      >
        <span className="truncate text-ink">{summary}</span>
        <ChevronDown size={16} className="shrink-0 text-ink-faint" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-multiselectable
          className="absolute z-20 mt-1 max-h-72 w-max min-w-full max-w-[22rem] overflow-y-auto rounded-xl border border-surface-border bg-white p-1 shadow-soft"
        >
          <div className="mb-1 flex items-center justify-between gap-2 px-1">
            <button
              type="button"
              onClick={() => onChange(new Set(options.map((o) => o.value)))}
              disabled={allSelected}
              className="rounded-lg px-1.5 py-1 text-xs font-medium text-indigo-600 transition-colors hover:bg-indigo-50 disabled:opacity-40"
            >
              Tümünü seç
            </button>
            <button
              type="button"
              onClick={() => onChange(new Set())}
              disabled={selected.size === 0}
              className="rounded-lg px-1.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-muted disabled:opacity-40"
            >
              Temizle
            </button>
          </div>
          {options.map((o) => {
            const checked = selected.has(o.value);
            return (
              <button
                key={o.value}
                type="button"
                role="option"
                aria-selected={checked}
                onClick={() => toggle(o.value)}
                className={cn(
                  "flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-indigo-50",
                  checked ? "text-ink" : "text-ink-muted",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                    checked
                      ? "border-indigo-500 bg-indigo-500 text-white"
                      : "border-surface-border",
                  )}
                >
                  {checked && <Check size={12} strokeWidth={3} />}
                </span>
                <span className="whitespace-normal break-words leading-snug">{o.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
