import type { Metadata } from "next";
import Link from "next/link";
import { DocPage, DocSection } from "@/components/DocPage";

export const metadata: Metadata = {
  title: "Hakkımızda — Semt Pazarı",
  description: "Semt Pazarı nedir, verilerini nereden alır ve nasıl güncellenir.",
};

const CITY_SOURCES = [
  "Adana",
  "Ankara",
  "Antalya",
  "Bursa",
  "İstanbul",
  "İzmir",
  "Kocaeli",
  "Konya",
  "Şanlıurfa",
];

export default function AboutPage() {
  return (
    <DocPage
      title="Hakkımızda"
      intro={
        <p>
          Semt Pazarı, Türkiye&apos;deki semt ve üretici pazarlarını bir haritada toplayan ve hal
          fiyatlarını her gün yayımlayan bağımsız bir bilgi sitesidir.
        </p>
      }
    >
      <DocSection title="Ne sunuyoruz">
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <Link href="/markets">Pazar yerleri</Link>: 81 ildeki semt ve üretici pazarlarının
            konumu, kurulduğu günler ve adresi.
          </li>
          <li>
            <Link href="/prices">Hal fiyatları</Link>: ulusal bültenle birlikte dokuz şehrin
            halinden günlük ortalama fiyatlar.
          </li>
          <li>
            <Link href="/trends">Fiyat geçmişi</Link>: bir ürünün fiyatının günler, haftalar ve
            aylar içindeki değişimi.
          </li>
        </ul>
      </DocSection>

      <DocSection title="Veriler nereden geliyor">
        <p>
          Pazar yerleri listesi ve ulusal hal bülteni, T.C. Ticaret Bakanlığı&apos;nın{" "}
          <a href="https://www.hal.gov.tr" rel="noopener noreferrer">
            hal.gov.tr
          </a>{" "}
          sitesinden alınır. Şehir bazlı fiyatlar {CITY_SOURCES.join(", ")} belediyelerinin
          yayımladığı hal bültenlerinden derlenir. Pazarların harita konumları Google Haritalar ile
          belirlenir.
        </p>
        <p>Veriler her gece otomatik olarak güncellenir.</p>
      </DocSection>

      <DocSection title="Fiyatları okurken">
        <p>
          Gösterilen fiyatlar halde oluşan toptan fiyatlardır; pazarda ya da markette ödeyeceğiniz
          perakende fiyattan farklıdır. Kaynak en düşük ve en yüksek fiyatı yayımlıyorsa ikisinin
          ortalamasını gösteririz; İzmir gibi ortalamayı doğrudan yayımlayan kaynaklarda o değeri
          kullanırız.
        </p>
      </DocSection>

      <DocSection title="Katkıda bulunun">
        <p>
          Eksik ya da hatalı bir pazar mı gördünüz? <Link href="/markets">Pazar yerleri</Link>{" "}
          sayfasındaki <strong>Yer öner</strong> düğmesiyle bize bildirin; önerileri inceledikten
          sonra haritaya işliyoruz.
        </p>
      </DocSection>

      <DocSection title="Bağımsızlık">
        <p>
          Semt Pazarı herhangi bir kamu kurumuyla bağlantılı değildir. Kamuya açık verileri derler
          ve kolay okunur hâle getirir.
        </p>
      </DocSection>
    </DocPage>
  );
}
