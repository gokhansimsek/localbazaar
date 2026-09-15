"use client";

import "react-day-picker/style.css";

import { useEffect, useRef, useState } from "react";
import { Calendar as CalendarIcon } from "lucide-react";
import { DayPicker } from "react-day-picker";
import { tr } from "date-fns/locale";
import { format, parseISO } from "date-fns";

type Props = {
  value: string; // ISO YYYY-MM-DD or empty string
  onChange: (iso: string) => void;
  max?: string; // ISO YYYY-MM-DD
};

function trDisplay(iso: string): string {
  if (!iso) return "Tarih seçin";
  try {
    return format(parseISO(iso), "dd MMMM yyyy", { locale: tr });
  } catch {
    return "Tarih seçin";
  }
}

export function DateSelector({ value, onChange, max }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = value ? parseISO(value) : undefined;
  const disabled = max ? { after: parseISO(max) } : undefined;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-xl border border-surface-border bg-white px-3 py-2 text-sm transition-all hover:border-ink-faint focus:border-crate-400 focus:shadow-ring focus:outline-none"
      >
        <CalendarIcon size={16} className="text-ink-muted" />
        <span className={value ? "text-ink" : "text-ink-faint"}>{trDisplay(value)}</span>
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Tarih seç"
          className="absolute left-0 top-full z-30 mt-2 rounded-xl border border-surface-border bg-white p-2 shadow-soft"
        >
          <DayPicker
            mode="single"
            selected={selected}
            onSelect={(d) => {
              if (d) {
                onChange(format(d, "yyyy-MM-dd"));
                setOpen(false);
              }
            }}
            locale={tr}
            disabled={disabled}
            weekStartsOn={1}
            showOutsideDays
          />
        </div>
      )}
    </div>
  );
}
