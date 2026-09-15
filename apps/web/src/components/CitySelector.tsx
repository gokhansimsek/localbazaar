"use client";

import type { City } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  cities: City[];
  value: string;
  onChange: (slug: string) => void;
};

export function CitySelector({ cities, value, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {cities.map((city) => (
        <button
          key={city.slug}
          type="button"
          onClick={() => onChange(city.slug)}
          aria-pressed={value === city.slug}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            value === city.slug
              ? "bg-ink text-surface-subtle"
              : "border border-surface-border bg-white text-ink-soft hover:border-ink-faint hover:text-ink",
          )}
        >
          {city.name}
        </button>
      ))}
    </div>
  );
}
