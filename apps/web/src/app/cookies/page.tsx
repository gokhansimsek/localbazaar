// DRAFT: written without legal review. Have it reviewed before relying on it.
import type { Metadata } from "next";
import { DocPage, DocSection } from "@/components/DocPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Çerez Politikası — Semt Pazarı",
  description: "Semt Pazarı'nda hangi çerezlerin kullanıldığı ve bunları nasıl yönetebileceğiniz.",
};

const LAST_UPDATED = "15 Eylül 2026";

export default function CookiesPage() {
  return (
    <DocPage
      title="Çerez Politikası"
      updated={LAST_UPDATED}
      intro={
        <p>
          Bu sayfa, Semt Pazarı&apos;nda hangi çerezlerin kullanıldığını ve bunları nasıl
          yönetebileceğinizi açıklar.
        </p>
      }
    >
      <DocSection title="1. Çerez nedir?">
        <p>
          Çerezler, ziyaret ettiğiniz sitelerin tarayıcınıza kaydettiği küçük metin dosyalarıdır.
        </p>
      </DocSection>

      <DocSection title="2. Kendi çerezlerimiz">
        <p>
          Semt Pazarı&apos;nın kendisi izleme ya da reklam amaçlı çerez kullanmaz. Sayfa
          ziyaretlerini yalnızca sayfa başına toplam sayı olarak sayarız; bu sayım çerez kullanmaz
          ve sizi tanımlamaz.
        </p>
      </DocSection>

      <DocSection title="3. Üçüncü taraf çerezleri">
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>Google AdSense</strong>: Reklam gösterildiğinde, reklam ölçümü ve
            kişiselleştirme için çerez kullanabilir.
          </li>
          <li>
            <strong>Google Funding Choices</strong>: AB ve Birleşik Krallık ziyaretçilerinin çerez
            tercihini saklar.
          </li>
          <li>
            <strong>Google Haritalar</strong>: Pazar yerleri sayfasındaki harita, çalışması için
            Google çerezleri kullanabilir.
          </li>
        </ul>
        <p>
          Google&apos;ın çerez kullanımı için{" "}
          <a href="https://policies.google.com/technologies/cookies" rel="noopener noreferrer">
            policies.google.com/technologies/cookies
          </a>{" "}
          adresine bakabilirsiniz.
        </p>
      </DocSection>

      <DocSection title="4. Tercihlerinizi yönetme">
        <p>
          AB ya da Birleşik Krallık&apos;tan bağlanıyorsanız sayfanın altındaki{" "}
          <strong>Çerez ayarları</strong> bağlantısıyla tercihinizi istediğiniz zaman
          değiştirebilirsiniz. Tüm ziyaretçiler tarayıcı ayarlarından çerezleri silebilir ya da
          engelleyebilir; bu durumda harita gibi bazı özellikler düzgün çalışmayabilir.
        </p>
      </DocSection>

      <DocSection title="5. İletişim">
        <p>
          Sorularınız için: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </DocSection>
    </DocPage>
  );
}
