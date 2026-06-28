"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const NAV: { href: Route; label: string }[] = [
  { href: "/markets", label: "Pazarlar" },
  { href: "/prices", label: "Hal Fiyatları" },
  { href: "/trends", label: "Trendler" },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-surface-border/70 bg-white/75 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6 lg:px-12">
        <Link href="/" className="group flex items-center gap-2.5">
          <span className="relative grid h-6 w-6 place-items-center overflow-hidden rounded-[7px] bg-ink">
            <span className="absolute inset-0 bg-[linear-gradient(135deg,#635BFF_0%,transparent_60%)] opacity-80" />
            <span className="relative block h-1.5 w-1.5 rounded-[1.5px] bg-white" />
          </span>
          <span className="text-[14.5px] font-semibold tracking-[-0.01em] text-ink">
            Semt Pazarı
          </span>
        </Link>

        <nav className="hidden items-center gap-0.5 md:flex">
          {NAV.map((item) => {
            const active =
              pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                  active ? "text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="hidden md:block" />
      </div>
    </header>
  );
}
