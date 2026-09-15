"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const NAV: { href: Route; label: string }[] = [
  { href: "/markets", label: "Pazarlar" },
  { href: "/prices", label: "Hal Fiyatları" },
  { href: "/trends", label: "Fiyat Geçmişi" },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-surface-border bg-surface-subtle/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-12">
        <Link
          href="/"
          aria-label="Semt Pazarı ana sayfa"
          className="flex shrink-0 items-center gap-2.5"
        >
          <span aria-hidden className="grid h-6 w-6 place-items-center rounded-[4px] bg-crate-500">
            <span className="block h-1.5 w-1.5 rounded-full bg-surface-subtle" />
          </span>
          <span className="font-display text-[17px] font-semibold text-ink">Semt Pazarı</span>
        </Link>

        {/* Phones navigate with MobileTabBar instead. */}
        <nav className="hidden items-center gap-1 sm:flex">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "px-2 py-1.5 text-[13px] font-medium underline-offset-[6px] transition-colors sm:px-3 sm:text-[14px]",
                  active
                    ? "text-ink underline decoration-crate-500 decoration-2"
                    : "text-ink-muted hover:text-ink",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
