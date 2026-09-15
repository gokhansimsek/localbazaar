import type { Metadata, Viewport } from "next";
import { Fraunces, Public_Sans } from "next/font/google";
import Script from "next/script";
import { MobileTabBar } from "@/components/MobileTabBar";
import { PageViewCounter } from "@/components/PageViewCounter";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import "./globals.css";

// latin-ext carries the Turkish glyphs (ğ, ş, ı, İ) both faces need.
const display = Fraunces({
  subsets: ["latin", "latin-ext"],
  variable: "--font-display",
  display: "swap",
});

const body = Public_Sans({
  subsets: ["latin", "latin-ext"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Semt Pazarı — Türkiye hal fiyatları, pazar yerleri ve daha fazlası",
  description:
    "Semt Pazarı, Türkiye'deki semt pazarlarını harita üzerinde keşfetmek, hal fiyatlarını günlük ve tarihsel olarak izlemek için tek noktadan platform.",
};

// viewport-fit=cover exposes env(safe-area-inset-bottom) so the mobile tab bar
// can clear the iOS home indicator.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

const ADSENSE_CLIENT_ID = process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID ?? "";
const ADSENSE_CMP_ENABLED = process.env.NEXT_PUBLIC_ADSENSE_CMP_ENABLED === "1";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className={`${display.variable} ${body.variable}`}>
      <head>
        {/*
          Google Funding Choices CMP loader. Must execute before the AdSense
          loader so the consent gate is in place. The actual consent messages
          are configured in the AdSense console (Privacy & messaging → IAB
          TCF). Strategy "beforeInteractive" gives the CMP a head start.
        */}
        {ADSENSE_CLIENT_ID && ADSENSE_CMP_ENABLED && (
          <Script
            id="adsense-cmp"
            strategy="beforeInteractive"
            src={`https://fundingchoicesmessages.google.com/i/${ADSENSE_CLIENT_ID}?ers=1`}
          />
        )}
        {/*
          AdSense loader. ``afterInteractive`` is the strategy AdSense
          recommends for the auto-ads snippet. The ad-unit ``<ins>`` elements
          rendered by <AdSlot/> read ``window.adsbygoogle`` from this script.
        */}
        {ADSENSE_CLIENT_ID && (
          <Script
            id="adsense-loader"
            strategy="afterInteractive"
            crossOrigin="anonymous"
            src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT_ID}`}
          />
        )}
      </head>
      <body>
        {/* On phones, bottom padding reserves the fixed tab bar's height so it never covers the footer. */}
        <div className="flex min-h-screen flex-col pb-[calc(3.75rem+env(safe-area-inset-bottom))] sm:pb-0">
          <SiteHeader />
          <main className="flex-1 px-6 pt-8 lg:px-12">
            <div className="mx-auto max-w-7xl">{children}</div>
          </main>
          <SiteFooter />
          <MobileTabBar />
          <PageViewCounter />
        </div>
      </body>
    </html>
  );
}
