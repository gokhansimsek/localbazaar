import type { Metadata } from "next";
import Link from "next/link";
import { DocPage, DocSection } from "@/components/DocPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "İletişim — Semt Pazarı",
  description: "Soru, öneri ve düzeltme talepleriniz için Semt Pazarı ile iletişime geçin.",
};

export default function ContactPage() {
  return (
    <DocPage
      title="İletişim"
      intro={<p>Soru, öneri ve düzeltme talepleriniz için bize e-posta gönderebilirsiniz.</p>}
    >
      <DocSection title="E-posta">
        <p>
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </DocSection>

      <DocSection title="Pazar bilgisi düzeltme">
        <p>
          Bir pazarın adı, konumu ya da kurulduğu gün yanlışsa en hızlı yol{" "}
          <Link href="/markets">Pazar yerleri</Link> sayfasındaki <strong>Yer öner</strong>{" "}
          formudur. Önerinizle birlikte haritada doğru konumu işaretleyebilirsiniz.
        </p>
      </DocSection>

      <DocSection title="Kişisel verileriniz">
        <p>
          Verilerinize erişme, düzeltme, silme ya da bülten aboneliğinden çıkma talepleriniz için de
          aynı adresi kullanabilirsiniz. Ayrıntılar için{" "}
          <Link href="/privacy">Gizlilik Politikası</Link>&apos;na bakın.
        </p>
      </DocSection>
    </DocPage>
  );
}
