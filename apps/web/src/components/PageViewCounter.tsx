"use client";

import { useEffect } from "react";
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

/**
 * Fire-and-forget page-view tracker for internal audit. Records each
 * navigation into the ``page_views`` table but renders nothing — the count is
 * never shown to visitors. Read the numbers via the page-views API.
 */
export function PageViewCounter() {
  const pathname = usePathname();

  useEffect(() => {
    const bucket = bucketPath(pathname);
    if (!bucket) return;
    recordPageView(bucket).catch(() => {
      // Audit ping is best-effort — swallow errors so a flaky backend never
      // breaks the page.
    });
  }, [pathname]);

  return null;
}
