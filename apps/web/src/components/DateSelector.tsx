"use client";

import { Calendar } from "lucide-react";

type Props = {
  value: string;
  onChange: (iso: string) => void;
  max?: string;
};

export function DateSelector({ value, onChange, max }: Props) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-surface-border bg-white px-3 py-2 text-sm text-ink-soft transition-all focus-within:border-indigo-400 focus-within:shadow-ring">
      <Calendar size={16} className="text-ink-muted" />
      <input
        type="date"
        value={value}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-ink outline-none"
      />
    </label>
  );
}
