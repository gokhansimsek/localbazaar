import type { Route } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { MarketsMockup } from "@/components/home/MarketsMockup";
import { PricesMockup } from "@/components/home/PricesMockup";
import { TrendsMockup } from "@/components/home/TrendsMockup";
import { cn } from "@/lib/cn";

export default function HomePage() {
  return (
    <div className="space-y-28 lg:space-y-36">
      <section className="pt-12 lg:pt-24">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="font-display text-[44px] font-semibold leading-[1.02] tracking-[-0.045em] text-ink sm:text-6xl lg:text-[80px]">
            Türkiye&apos;nin{" "}
            <span className="font-normal italic text-ink-soft">semt pazarları</span> ve hal
            fiyatları, tek adreste.
          </h1>
          <p className="mx-auto mt-7 max-w-xl text-[15px] leading-[1.65] text-ink-soft">
            81 il, binlerce mahalle pazarı ve ürünlerin günlük fiyatları. Haritada keşfedin,
            fiyatları izleyin, trendleri okuyun.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href="/markets" className="btn-primary">
              Pazarları keşfet
              <ArrowUpRight size={14} strokeWidth={2.25} />
            </Link>
            <Link href="/prices" className="btn-ghost">
              Bugünün bülteni
            </Link>
          </div>
        </div>
      </section>

      <FeatureSection
        eyebrow="Pazarlar"
        title="Her semt pazarı, haritada"
        copy="81 ilin 970 ilçesindeki tüm semt ve üretici pazarları coğrafyaya yerleştirildi. Konumunuzu paylaşın, yakındaki pazarları gün ve türe göre filtreleyin."
        href="/markets"
        cta="Pazarları aç"
        mockup={<MarketsMockup />}
      />

      <FeatureSection
        eyebrow="Hal Fiyatları"
        title="Günlük bültenler"
        copy="Ulusal ve büyük şehirlerin hal bültenlerinden günlük ortalama fiyatlar."
        href="/prices"
        cta="Bülteni gör"
        mockup={<PricesMockup />}
        reverse
      />

      <FeatureSection
        eyebrow="Fiyat Geçmişi"
        title="Tarihsel seri"
        copy="Günlük, haftalık veya aylık birikim. Ürün bazlı çizgi grafikleri, yüzde değişim okumaları ve mevsimsellik kalıpları."
        href="/trends"
        cta="Fiyat Geçmişini incele"
        mockup={<TrendsMockup />}
      />
    </div>
  );
}

function FeatureSection({
  eyebrow,
  title,
  copy,
  href,
  cta,
  mockup,
  reverse = false,
}: {
  eyebrow: string;
  title: React.ReactNode;
  copy: string;
  href: string;
  cta: string;
  mockup: React.ReactNode;
  reverse?: boolean;
}) {
  return (
    <section className="grid items-center gap-10 lg:grid-cols-2 lg:gap-20">
      <div className={cn("space-y-6", reverse && "lg:order-2")}>
        <div className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-ink-muted">
          {eyebrow}
        </div>
        <h2 className="font-display text-[34px] font-semibold leading-[1.08] tracking-[-0.035em] text-ink lg:text-[52px]">
          {title}
        </h2>
        <p className="max-w-md text-[15px] leading-[1.65] text-ink-soft">{copy}</p>
        <Link
          href={href as Route}
          className="group inline-flex items-center gap-1.5 border-b border-ink/15 pb-0.5 text-[14px] font-medium text-ink transition-colors hover:border-ink/60"
        >
          {cta}
          <ArrowUpRight
            size={14}
            strokeWidth={2.25}
            className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
          />
        </Link>
      </div>
      <div className={cn(reverse && "lg:order-1")}>{mockup}</div>
    </section>
  );
}
