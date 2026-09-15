import type { Route } from "next";
import Link from "next/link";
import { CookieSettingsButton } from "@/components/CookieSettingsButton";
import { NewsletterForm } from "@/components/NewsletterForm";

// Mirrors the condition app/layout.tsx uses to load the consent (CMP) script.
const CMP_ACTIVE =
  Boolean(process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID) &&
  process.env.NEXT_PUBLIC_ADSENSE_CMP_ENABLED === "1";

const CITY_LINKS: { href: Route; label: string }[] = [
  { href: "/markets?il=istanbul" as Route, label: "İstanbul pazarları" },
  { href: "/markets?il=ankara" as Route, label: "Ankara pazarları" },
  { href: "/markets?il=izmir" as Route, label: "İzmir pazarları" },
  { href: "/markets?gun=bugun" as Route, label: "Bugün açık pazarlar" },
];

const INFO_LINKS: { href: Route; label: string }[] = [
  { href: "/about", label: "Hakkımızda" },
  { href: "/contact", label: "İletişim" },
  { href: "/privacy", label: "Gizlilik Politikası" },
  { href: "/terms", label: "Kullanım Koşulları" },
  { href: "/cookies", label: "Çerez Politikası" },
];

const LINK_CLS = "transition-colors hover:text-surface-subtle hover:underline underline-offset-2";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-24 bg-ink text-surface-subtle/75">
      <div className="mx-auto grid max-w-7xl gap-10 px-6 py-14 sm:grid-cols-2 lg:grid-cols-[1.3fr_1fr_1fr_1.4fr] lg:px-12">
        <div className="space-y-3">
          <Link href="/" className="inline-flex items-center gap-2.5">
            <span
              aria-hidden
              className="grid h-6 w-6 place-items-center rounded-[4px] bg-crate-500"
            >
              <span className="block h-1.5 w-1.5 rounded-full bg-ink" />
            </span>
            <span className="font-display text-lg font-semibold text-surface-subtle">
              Semt Pazarı
            </span>
          </Link>
          <p className="max-w-xs text-sm leading-relaxed">
            Türkiye&apos;deki semt ve üretici pazarlarını haritada bulun, hal fiyatlarını her gün
            takip edin.
          </p>
        </div>

        <FooterColumn title="Popüler şehirler">
          {CITY_LINKS.map((l) => (
            <li key={l.href}>
              <Link href={l.href} className={LINK_CLS}>
                {l.label}
              </Link>
            </li>
          ))}
        </FooterColumn>

        <FooterColumn title="Bilgi">
          {INFO_LINKS.map((l) => (
            <li key={l.href}>
              <Link href={l.href} className={LINK_CLS}>
                {l.label}
              </Link>
            </li>
          ))}
          {CMP_ACTIVE && (
            <li>
              <CookieSettingsButton className={LINK_CLS} />
            </li>
          )}
        </FooterColumn>

        <div className="space-y-3">
          <h2 className="font-sans text-sm font-semibold text-surface-subtle">Bülten</h2>
          <p className="text-sm">Yeni özellikler ve güncellemelerden e-postayla haberdar olun.</p>
          <NewsletterForm />
        </div>
      </div>

      <div className="border-t border-white/10">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-5 text-xs text-surface-subtle/55 sm:flex-row sm:justify-between lg:px-12">
          <p>© {year} Semt Pazarı. Tüm hakları saklıdır.</p>
          <p>Fiyat ve pazar verileri hal.gov.tr ile belediye hal bültenlerinden derlenir.</p>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="font-sans text-sm font-semibold text-surface-subtle">{title}</h2>
      <ul className="space-y-2 text-sm">{children}</ul>
    </div>
  );
}
