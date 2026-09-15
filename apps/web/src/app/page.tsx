import type { Route } from "next";
import Link from "next/link";
import { MarketsMockup } from "@/components/home/MarketsMockup";
import { PricesMockup } from "@/components/home/PricesMockup";
import { TrendsMockup } from "@/components/home/TrendsMockup";
import { cn } from "@/lib/cn";

export default function HomePage() {
  return (
    <div className="space-y-24 pb-24 lg:space-y-32">
      <section className="border-b border-surface-border pb-14 pt-8 lg:pb-20 lg:pt-14">
        <h1 className="max-w-4xl text-[44px] font-semibold leading-[1.02] sm:text-6xl lg:text-[84px]">
          Semt pazarları ve hal fiyatları, tek adreste.
        </h1>
        <div className="mt-10 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <p className="max-w-xl text-base leading-relaxed text-ink-soft">
            81 ildeki semt ve üretici pazarlarını haritada bulun, halin günlük bültenini okuyun, bir
            ürünün fiyatının aylar içinde nasıl değiştiğini görün.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/markets" className="btn-primary">
              Pazarları keşfet
            </Link>
            <Link href="/prices" className="btn-ghost">
              Bugünün bülteni
            </Link>
          </div>
        </div>
      </section>

      <FeatureSection
        title="Her semt pazarı, haritada"
        copy="81 ilin 970 ilçesindeki semt ve üretici pazarları haritada. Konumunuzu paylaşın, yakınınızdaki pazarları güne ve türe göre süzün."
        href="/markets"
        cta="Pazarları aç"
        mockup={<MarketsMockup />}
      />

      <FeatureSection
        title="Günlük hal bülteni"
        copy="Ulusal bültenle birlikte dokuz büyük şehrin halinden günlük ortalama fiyatlar."
        href="/prices"
        cta="Bülteni gör"
        mockup={<PricesMockup />}
        reverse
      />

      <FeatureSection
        title="Fiyat geçmişi"
        copy="Bir ürünün fiyatını günlük, haftalık ya da aylık izleyin; halleri karşılaştırın, mevsimin fiyatlara etkisini görün."
        href="/trends"
        cta="Fiyat geçmişini incele"
        mockup={<TrendsMockup />}
      />
    </div>
  );
}

function FeatureSection({
  title,
  copy,
  href,
  cta,
  mockup,
  reverse = false,
}: {
  title: string;
  copy: string;
  href: Route;
  cta: string;
  mockup: React.ReactNode;
  reverse?: boolean;
}) {
  return (
    <section className="grid items-center gap-10 lg:grid-cols-2 lg:gap-20">
      <div className={cn("space-y-5", reverse && "lg:order-2")}>
        <h2 className="text-[34px] font-semibold leading-[1.08] lg:text-[48px]">{title}</h2>
        <p className="max-w-md text-[15px] leading-[1.7] text-ink-soft">{copy}</p>
        <Link
          href={href}
          className="inline-block text-[15px] font-semibold text-crate-700 underline decoration-crate-500/40 decoration-2 underline-offset-4 transition-colors hover:decoration-crate-500"
        >
          {cta}
        </Link>
      </div>
      <div className={cn(reverse && "lg:order-1")}>{mockup}</div>
    </section>
  );
}
