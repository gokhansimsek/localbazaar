"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarCheck, House, MapPin, Tag, TrendingUp, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Tab = {
  href: Route;
  label: string;
  icon: LucideIcon;
  /** Path prefixes that mark this tab active. Omitted = exact match on href. */
  match?: string[];
};

// "Bugün açık" shares /markets with "Pazarlar"; only "Pazarlar" highlights there
// (reading the query here would force a Suspense boundary around the layout).
const TABS: Tab[] = [
  { href: "/", label: "Ana sayfa", icon: House },
  { href: "/markets", label: "Pazarlar", icon: MapPin, match: ["/markets"] },
  { href: "/markets?gun=bugun" as Route, label: "Bugün açık", icon: CalendarCheck, match: [] },
  { href: "/prices", label: "Fiyatlar", icon: Tag, match: ["/prices", "/products"] },
  { href: "/trends", label: "Geçmiş", icon: TrendingUp, match: ["/trends"] },
];

/** Phone-only fixed bottom navigation; the header's links are hidden below `sm`. */
export function MobileTabBar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Alt gezinme"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-surface-border bg-surface-subtle/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden"
    >
      <ul className="grid grid-cols-5">
        {TABS.map((tab) => {
          const active = tab.match
            ? tab.match.some((p) => pathname === p || pathname.startsWith(`${p}/`))
            : pathname === tab.href;
          const Icon = tab.icon;
          return (
            <li key={tab.label}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-[3.75rem] flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                  active ? "text-crate-600" : "text-ink-muted",
                )}
              >
                <Icon size={20} strokeWidth={active ? 2.25 : 1.75} aria-hidden />
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
