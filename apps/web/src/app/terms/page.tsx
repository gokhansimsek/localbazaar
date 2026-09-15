// DRAFT: written without legal review. Have it reviewed before relying on it.
import type { Metadata } from "next";
import Link from "next/link";
import { DocPage, DocSection } from "@/components/DocPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Kullanım Koşulları — Semt Pazarı",
  description: "Semt Pazarı'nı kullanırken geçerli olan koşullar.",
};

const LAST_UPDATED = "15 Eylül 2026";

export default function TermsPage() {
  return (
    <DocPage
      title="Kullanım Koşulları"
      updated={LAST_UPDATED}
      intro={<p>Semt Pazarı&apos;nı kullanarak aşağıdaki koşulları kabul etmiş olursunuz.</p>}
    >
      <DocSection title="1. Hizmet">
        <p>
          Semt Pazarı; pazar yerleri, hal fiyatları ve fiyat geçmişi hakkında ücretsiz bilgi sunan
          bir web sitesidir. Siteyi kullanmak için hesap açmanız gerekmez.
        </p>
      </DocSection>

      <DocSection title="2. Bilgilerin doğruluğu">
        <p>
          Veriler hal.gov.tr ve belediyelerin yayımladığı bültenlerden otomatik olarak derlenir.
          Kaynaklardaki hatalar, gecikmeler ya da bizim tarafımızdaki işleme hataları nedeniyle
          bilgiler eksik veya yanlış olabilir. Gösterilen fiyatlar toptan hal fiyatlarıdır,
          perakende fiyat değildir. Pazarların yeri ve günü önceden haber verilmeden değişebilir.
          Önemli bir karar vermeden önce bilgiyi ilgili kaynaktan doğrulamanızı öneririz.
        </p>
      </DocSection>

      <DocSection title="3. Kullanıcı katkıları">
        <p>
          Yer öner formu ve bülten aboneliği aracılığıyla gönderdiğiniz bilgilerin doğru olduğunu ve
          başkasına ait kişisel veri içermediğini kabul edersiniz. Önerileri inceleme, düzenleme,
          yayımlama ya da reddetme hakkımız saklıdır.
        </p>
      </DocSection>

      <DocSection title="4. Kabul edilemez kullanım">
        <p>
          Siteyi hukuka aykırı amaçlarla kullanmak, hizmetin işleyişini bozmaya çalışmak ya da
          siteye aşırı sayıda otomatik istek göndermek yasaktır. Aşırı istekler otomatik olarak
          sınırlandırılır.
        </p>
      </DocSection>

      <DocSection title="5. Fikri mülkiyet">
        <p>
          Sitenin tasarımı ve yazılımı Semt Pazarı&apos;na aittir. Kaynak verilerin hakları, onları
          yayımlayan kurumlara aittir.
        </p>
      </DocSection>

      <DocSection title="6. Üçüncü taraf hizmetler ve bağlantılar">
        <p>
          Site, Google Haritalar ve Google AdSense gibi üçüncü taraf hizmetler içerir ve başka
          sitelere bağlantı verir. Bu hizmetlerin içeriğinden ve uygulamalarından sorumlu değiliz.
          Çerez kullanımı için <Link href="/cookies">Çerez Politikası</Link>&apos;na bakın.
        </p>
      </DocSection>

      <DocSection title="7. Sorumluluğun sınırlandırılması">
        <p>
          Site &quot;olduğu gibi&quot; sunulur. Yürürlükteki mevzuatın izin verdiği ölçüde, sitedeki
          bilgilerin kullanımından doğabilecek doğrudan ya da dolaylı zararlardan sorumlu
          tutulamayız.
        </p>
      </DocSection>

      <DocSection title="8. Değişiklikler">
        <p>
          Bu koşulları zaman zaman güncelleyebiliriz. Güncel metin her zaman bu sayfadadır; son
          değişiklik tarihi sayfanın başında yer alır.
        </p>
      </DocSection>

      <DocSection title="9. Uygulanacak hukuk">
        <p>Bu koşullar Türkiye Cumhuriyeti hukukuna tabidir.</p>
      </DocSection>

      <DocSection title="10. İletişim">
        <p>
          Sorularınız için: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </DocSection>
    </DocPage>
  );
}
