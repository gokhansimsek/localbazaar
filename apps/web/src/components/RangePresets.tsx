"use client";

import { cn } from "@/lib/cn";

export type RangeKey = "1M" | "3M" | "6M" | "1Y" | "ALL";

const OPTIONS: { key: RangeKey; label: string }[] = [
  { key: "1M", label: "1 Ay" },
  { key: "3M", label: "3 Ay" },
  { key: "6M", label: "6 Ay" },
  { key: "1Y", label: "1 Yıl" },
  { key: "ALL", label: "Tümü" },
];

type Props = {
  value: RangeKey;
  onChange: (key: RangeKey) => void;
};

export function RangePresets({ value, onChange }: Props) {
  return (
    <div className="inline-flex rounded-xl border border-surface-border bg-white p-1">
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            value === o.key ? "bg-ink text-surface-subtle" : "text-ink-soft hover:bg-surface-muted",
          )}
          aria-pressed={value === o.key}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function rangeToFromDate(key: RangeKey): string | undefined {
  if (key === "ALL") return undefined;
  const now = new Date();
  const d = new Date(now);
  switch (key) {
    case "1M":
      d.setMonth(d.getMonth() - 1);
      break;
    case "3M":
      d.setMonth(d.getMonth() - 3);
      break;
    case "6M":
      d.setMonth(d.getMonth() - 6);
      break;
    case "1Y":
      d.setFullYear(d.getFullYear() - 1);
      break;
  }
  return d.toISOString().slice(0, 10);
}
