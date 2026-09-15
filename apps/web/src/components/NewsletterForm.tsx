"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { subscribeNewsletter } from "@/lib/api";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Footer newsletter signup: email + explicit consent, stored via POST /api/newsletter. */
export function NewsletterForm() {
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState(""); // honeypot
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailId = useId();
  const consentId = useId();

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!EMAIL_RE.test(email.trim())) {
      setError("Geçerli bir e-posta adresi girin.");
      return;
    }
    if (!consent) {
      setError("Abone olmak için onay kutusunu işaretleyin.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await subscribeNewsletter({ email: email.trim(), consent: true, website });
      setDone(true);
    } catch {
      setError("Abonelik şu anda kaydedilemedi. Birkaç dakika sonra tekrar deneyin.");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <p role="status" className="text-sm text-leaf-200">
        Abone oldunuz. Güncellemeleri e-posta adresinize göndereceğiz.
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-3">
      <div className="flex gap-2">
        <label htmlFor={emailId} className="sr-only">
          E-posta adresi
        </label>
        <input
          id={emailId}
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="E-posta adresiniz"
          className="min-w-0 flex-1 rounded-md border border-white/15 bg-white/5 px-3 py-2 text-sm text-surface-subtle placeholder:text-surface-subtle/40 focus:border-crate-400 focus:outline-none"
        />
        <button type="submit" disabled={submitting} className="btn-primary shrink-0 py-2">
          {submitting ? "Kaydediliyor…" : "Abone ol"}
        </button>
      </div>
      <div className="flex items-start gap-2 text-xs leading-relaxed">
        <input
          id={consentId}
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 accent-crate-500"
        />
        <label htmlFor={consentId}>
          Bülten için e-posta adresimin kullanılmasını kabul ediyorum.{" "}
          <Link href="/privacy" className="underline underline-offset-2 hover:text-surface-subtle">
            Gizlilik Politikası
          </Link>
        </label>
      </div>
      <input
        type="text"
        name="website"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden
        className="hidden"
      />
      {error && (
        <p role="alert" className="text-xs text-crate-300">
          {error}
        </p>
      )}
    </form>
  );
}
