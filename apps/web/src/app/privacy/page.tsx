import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Gizlilik Politikası — Semt Pazarı",
  description:
    "Semt Pazarı'nın gizlilik politikası: hangi verileri topluyoruz, neden topluyoruz, üçüncü taraf hizmetler ve kullanıcı hakları.",
};

const LAST_UPDATED = "13 Mayıs 2026";

export default function PrivacyPage() {
  return (
    <article className="prose prose-slate mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <span className="chip">Yasal</span>
        <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl">Gizlilik Politikası</h1>
        <p className="text-sm text-ink-muted">Son güncelleme: {LAST_UPDATED}</p>
      </header>

      <Section title="1. Topladığımız veriler">
        <p>
          Semt Pazarı, kullanıcılar için zorunlu hesap kaydı tutmaz. Site, anonim olarak aşağıdaki
          verileri toplayabilir:
        </p>
        <ul className="list-disc pl-6">
          <li>Ziyaretiniz sırasında ulaştığınız sayfalar ve ziyaret süresi (anonim analitik).</li>
          <li>
            IP adresinizden çıkarılan ülke / şehir bilgisi (kötü niyetli trafik tespitinde ve oran
            sınırlamada kullanılır).
          </li>
          <li>
            Tarayıcınızın gönderdiği User-Agent, dil tercihi ve referans bilgisi (standart HTTP
            başlıkları).
          </li>
        </ul>
      </Section>

      <Section title="2. Üçüncü taraf hizmetler">
        <ul className="list-disc pl-6">
          <li>
            <strong>Google AdSense</strong>: Reklamların gösterilmesi için Google tarafından
            sağlanan reklam ağı. AdSense, kişiselleştirilmiş reklamlar için tarayıcınızda çerez
            kullanabilir. Google&apos;ın çerez politikası için{" "}
            <a href="https://policies.google.com/technologies/ads" rel="noopener noreferrer">
              policies.google.com/technologies/ads
            </a>{" "}
            adresini inceleyebilirsiniz.
          </li>
          <li>
            <strong>Google Funding Choices</strong>: AB / Birleşik Krallık ziyaretçileri için IAB
            TCF v2.2 uyumlu rıza yönetim aracı. Reklamlar yüklenmeden önce çerez tercihinizi sorar.
          </li>
          <li>
            <strong>Google Haritalar</strong>: Pazar yerleri sayfasındaki harita Google Maps
            JavaScript API ile yüklenir. Kullanım kuralları için{" "}
            <a href="https://policies.google.com/privacy" rel="noopener noreferrer">
              policies.google.com/privacy
            </a>
            .
          </li>
          <li>
            <strong>Hal.gov.tr</strong>: Fiyat ve pazar verileri, T.C. Ticaret Bakanlığı&apos;nın
            açık veri kaynaklarından sayılan{" "}
            <a href="https://www.hal.gov.tr" rel="noopener noreferrer">
              hal.gov.tr
            </a>{" "}
            üzerinden alınır. Hal.gov.tr&apos;nin gizlilik politikası bizim kontrolümüz dışındadır.
          </li>
        </ul>
      </Section>

      <Section title="3. Çerezler ve rıza yönetimi">
        <p>
          AB / Birleşik Krallık ziyaretçileri için reklam çerezleri yüklenmeden önce bir rıza mesajı
          gösterilir. Tercihinizi istediğiniz zaman, sayfanın sağ üst köşesindeki tarayıcı
          ayarlarından veya bu sayfadaki rıza penceresini yeniden açarak değiştirebilirsiniz.
        </p>
        <p>
          Diğer bölgelerdeki ziyaretçiler için reklamlar varsayılan olarak kişiselleştirilebilir;
          tarayıcı ayarlarınızdan çerezleri devre dışı bırakmak her zaman mümkündür.
        </p>
      </Section>

      <Section title="4. Veri saklama">
        <p>
          Anonim analitik veriler kümülatif istatistik amacıyla saklanır. Kişisel veri (ad, e-posta,
          adres) toplanmadığı için kişisel veri saklama süresi söz konusu değildir.
        </p>
      </Section>

      <Section title="5. Haklarınız (KVKK / GDPR)">
        <p>
          Türkiye Cumhuriyeti vatandaşları için 6698 sayılı KVKK, AB vatandaşları için GDPR
          kapsamında verilerinize erişme, düzeltme, silme ve işlenmesine itiraz etme haklarına
          sahipsiniz. İletişim için aşağıdaki e-posta adresini kullanabilirsiniz.
        </p>
      </Section>

      <Section title="6. İletişim">
        <p>
          Bu politikayla ilgili sorularınız için:{" "}
          <a href="mailto:gokhan.simsek@osf.digital">gokhan.simsek@osf.digital</a>.
        </p>
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold text-ink">{title}</h2>
      <div className="space-y-2 text-sm text-ink-soft">{children}</div>
    </section>
  );
}
