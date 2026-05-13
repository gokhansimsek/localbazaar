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
          className={cn(
            "rounded-full px-3.5 py-1.5 text-xs font-medium transition-all",
            value === city.slug
              ? "bg-indigo-500 text-white shadow-soft"
              : "border border-surface-border bg-white text-ink-soft hover:border-indigo-300 hover:text-indigo-700",
          )}
        >
          {city.name}
        </button>
      ))}
    </div>
  );
}
