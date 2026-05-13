"use client";

import { useEffect, useRef } from "react";

const CLIENT_ID = process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID ?? "";

/**
 * Single Google AdSense ad unit.
 *
 * Renders an ``<ins class="adsbygoogle">`` and pushes the standard
 * ``(adsbygoogle = window.adsbygoogle || []).push({})`` initialization on
 * mount, the same handshake AdSense's HTML snippet uses.
 *
 * Stays inert when ``NEXT_PUBLIC_ADSENSE_CLIENT_ID`` is empty so previews and
 * local dev never reach out to Google. Pair this component with the loader
 * Script in ``app/layout.tsx`` — the loader makes ``window.adsbygoogle``
 * available.
 *
 * Props:
 *   - ``slot``      The AdSense ad unit slot id (required).
 *   - ``layout``    Optional ``"display"`` / ``"in-article"`` / etc. for non-display formats.
 *   - ``format``    The ``data-ad-format`` value; defaults to ``"auto"``.
 *   - ``responsive``Whether to set ``data-full-width-responsive``. Defaults to ``true``.
 *   - ``className`` Extra Tailwind classes to wrap the ad in.
 */
type AdSlotProps = {
  slot: string;
  layout?: string;
  format?: string;
  responsive?: boolean;
  className?: string;
};

declare global {
  interface Window {
    adsbygoogle?: Array<Record<string, unknown>>;
  }
}

export function AdSlot({
  slot,
  layout,
  format = "auto",
  responsive = true,
  className,
}: AdSlotProps) {
  const pushedRef = useRef(false);

  useEffect(() => {
    if (!CLIENT_ID || !slot || pushedRef.current) return;
    pushedRef.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle ?? []).push({});
    } catch {
      // Adsbygoogle throws on duplicate pushes or before the loader script
      // is parsed; we swallow silently because the unit still renders.
    }
  }, [slot]);

  if (!CLIENT_ID || !slot) return null;

  return (
    <ins
      className={`adsbygoogle ${className ?? ""}`.trim()}
      style={{ display: "block" }}
      data-ad-client={CLIENT_ID}
      data-ad-slot={slot}
      {...(layout ? { "data-ad-layout": layout } : {})}
      data-ad-format={format}
      data-full-width-responsive={responsive ? "true" : "false"}
    />
  );
}
