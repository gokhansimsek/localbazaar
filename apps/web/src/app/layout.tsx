import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import { SiteHeader } from "@/components/SiteHeader";
import "./globals.css";

const inter = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Semt Pazarı — Türkiye hal fiyatları, pazar yerleri ve daha fazlası",
  description:
    "Semt Pazarı, Türkiye'deki semt pazarlarını harita üzerinde keşfetmek, hal fiyatlarını günlük ve tarihsel olarak izlemek için tek noktadan platform.",
};

const ADSENSE_CLIENT_ID = process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID ?? "";
const ADSENSE_CMP_ENABLED = process.env.NEXT_PUBLIC_ADSENSE_CMP_ENABLED === "1";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className={inter.variable}>
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
        <div className="min-h-screen">
          <SiteHeader />
          <main className="px-6 pb-20 pt-8 lg:px-12">
            <div className="mx-auto max-w-7xl">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
