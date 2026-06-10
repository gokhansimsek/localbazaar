"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { recordPageView } from "@/lib/api";

/**
 * Normalize a Next.js pathname into one of the buckets the backend accepts.
 *
 * Dynamic routes like ``/products/Domates`` collapse to ``/products/[name]``
 * so the ``page_views`` table stays small (one row per route, not one row
 * per product). Anything that isn't on the allow-list returns ``null``;
 * the caller skips the ping in that case.
 */
function bucketPath(pathname: string): string | null {
  if (pathname === "/") return "/";
  if (pathname === "/prices") return "/prices";
  if (pathname === "/trends") return "/trends";
  if (pathname === "/markets") return "/markets";
  if (pathname === "/privacy") return "/privacy";
  if (pathname.startsWith("/products/")) return "/products/[name]";
  return null;
}

function formatCount(n: number): string {
  return new Intl.NumberFormat("tr-TR").format(n);
}

export function PageViewCounter() {
  const pathname = usePathname();
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    const bucket = bucketPath(pathname);
    if (!bucket) {
      setCount(null);
      return;
    }
    let cancelled = false;
    recordPageView(bucket)
      .then((res) => {
        if (!cancelled) setCount(res.visit_count);
      })
      .catch(() => {
        // Counter is decorative — swallow errors so a flaky backend never
        // breaks the page.
        if (!cancelled) setCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (count === null) return null;

  return (
    <div className="mx-auto max-w-7xl px-6 pb-6 lg:px-12">
      <div className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink-faint">
        <span className="h-1 w-1 rounded-full bg-ink-faint/60" />
        Bu sayfa <span className="font-mono text-ink-muted">{formatCount(count)}</span> kez
        görüntülendi
      </div>
    </div>
  );
}
