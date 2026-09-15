// DRAFT (updated 15 Sep 2026 to match what the site actually stores): needs
// legal review, including naming the data controller (veri sorumlusu).
import type { Metadata } from "next";
import Link from "next/link";
import { DocPage, DocSection } from "@/components/DocPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Gizlilik Politikası — Semt Pazarı",
  description:
    "Semt Pazarı'nın gizlilik politikası: hangi verileri topluyoruz, neden topluyoruz, üçüncü taraf hizmetler ve kullanıcı hakları.",
};

const LAST_UPDATED = "15 Eylül 2026";

export default function PrivacyPage() {
  return (
    <DocPage title="Gizlilik Politikası" updated={LAST_UPDATED}>
      <DocSection title="1. Topladığımız veriler">
        <p>
          Siteyi kullanmak için hesap açmanız gerekmez. Yalnızca gezinirken sizi tanımlayan bir veri
          saklamayız.
        </p>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>Sayfa sayaçları</strong>: Hangi sayfanın kaç kez ziyaret edildiğini sayfa başına
            toplam sayı olarak tutarız. Bu sayı sizi tanımlamaz.
          </li>
          <li>
            <strong>Teknik veriler</strong>: IP adresiniz aşırı istekleri sınırlamak için işlenir;
            IP adresi ve tarayıcınızın gönderdiği standart bilgiler (User-Agent, dil) teknik sunucu
            kayıtlarında yer alabilir.
          </li>
          <li>
            <strong>Yer öner formu</strong>: Bir pazar önerdiğinizde adınız, soyadınız, e-posta
            adresiniz, isteğe bağlı olarak il ve ilçe bilginiz ile önerinizin ayrıntıları (pazar
            adı, konum, açıklama) kaydedilir.
          </li>
          <li>
            <strong>Bülten</strong>: Bültene abone olduğunuzda e-posta adresiniz ve abonelik
            tarihiniz kaydedilir.
          </li>
          <li>
            <strong>Konum</strong>: &quot;Konumumu Kullan&quot; düğmesine bastığınızda tarayıcınız
            konumunuzu yalnızca izninizle paylaşır. Konum, Google Haritalar ile il ve ilçeye
            çevrilir ve sunucularımıza kaydedilmez.
          </li>
        </ul>
      </DocSection>

      <DocSection title="2. Verileri ne için kullanıyoruz">
        <ul className="list-disc space-y-1 pl-6">
          <li>
            Öneri bilgilerini, öneriyi incelemek, pazar bilgisini güncellemek ve gerekirse sizinle
            iletişime geçmek için.
          </li>
          <li>Bülten e-posta adresini, yalnızca site güncellemelerini göndermek için.</li>
          <li>Teknik verileri, sitenin güvenliği ve düzgün çalışması için.</li>
        </ul>
        <p>Kişisel verilerinizi satmayız.</p>
      </DocSection>

      <DocSection title="3. Üçüncü taraf hizmetler">
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>Google AdSense</strong>: Reklamların gösterilmesi için Google tarafından
            sağlanan reklam ağı. AdSense, kişiselleştirilmiş reklamlar için tarayıcınızda çerez
            kullanabilir. Ayrıntılar için{" "}
            <a href="https://policies.google.com/technologies/ads" rel="noopener noreferrer">
              policies.google.com/technologies/ads
            </a>
            .
          </li>
          <li>
            <strong>Google Funding Choices</strong>: AB ve Birleşik Krallık ziyaretçileri için IAB
            TCF v2.2 uyumlu rıza yönetim aracı. Reklamlar yüklenmeden önce çerez tercihinizi sorar.
          </li>
          <li>
            <strong>Google Haritalar</strong>: Pazar yerleri sayfasındaki harita ve konum çevirisi
            Google Maps JavaScript API ile çalışır. Ayrıntılar için{" "}
            <a href="https://policies.google.com/privacy" rel="noopener noreferrer">
              policies.google.com/privacy
            </a>
            .
          </li>
          <li>
            <strong>Hal.gov.tr ve belediyeler</strong>: Fiyat ve pazar verileri kamuya açık
            kaynaklardan alınır. Bu sitelerin gizlilik politikaları bizim kontrolümüz dışındadır.
          </li>
        </ul>
      </DocSection>

      <DocSection title="4. Çerezler">
        <p>
          Hangi çerezlerin kullanıldığını ve tercihinizi nasıl değiştirebileceğinizi{" "}
          <Link href="/cookies">Çerez Politikası</Link> sayfasında açıklıyoruz.
        </p>
      </DocSection>

      <DocSection title="5. Veri saklama">
        <p>
          Öneri kayıtları, incelendikten sonra da pazar bilgisindeki değişikliklerin kaynağını
          gösterebilmek için saklanır. Bülten aboneliğiniz, aboneliğinizi sonlandırmanızı
          istediğiniz ana kadar saklanır. Silinmesini istediğiniz veriler için bize yazabilirsiniz.
        </p>
      </DocSection>

      <DocSection title="6. Haklarınız (KVKK / GDPR)">
        <p>
          6698 sayılı KVKK ve AB vatandaşları için GDPR kapsamında verilerinize erişme, düzeltme,
          silme ve işlenmesine itiraz etme haklarına sahipsiniz. Bülten aboneliğinden çıkmak da
          dahil bu talepleriniz için aşağıdaki adrese yazabilirsiniz.
        </p>
      </DocSection>

      <DocSection title="7. İletişim">
        <p>
          Bu politikayla ilgili sorularınız için:{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </DocSection>
    </DocPage>
  );
}
