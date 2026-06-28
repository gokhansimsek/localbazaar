"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  listDistricts,
  submitSuggestion,
  type District,
  type MarketOut,
  type MarketTypeSlug,
  type Province,
  type SuggestionType,
} from "@/lib/api";

type Props = {
  provinces: Province[];
  mode: SuggestionType;
  onModeChange: (mode: SuggestionType) => void;
  /** Coordinates the user dropped on the map for an "add" suggestion. */
  draftPin: { lat: number; lng: number } | null;
  /** Existing market the user picked (by clicking a pin) for an "update". */
  selectedMarket: MarketOut | null;
  onClose: () => void;
};

const PLACE_TYPES: { value: MarketTypeSlug; label: string }[] = [
  { value: "semt_pazari", label: "Semt Pazarı" },
  { value: "uretici_pazari", label: "Üretici Pazarı" },
];

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Panel for submitting a place suggestion (add a new market by dropping a pin,
 * or update an existing one). Rendered alongside the still-interactive map.
 */
export function SuggestionForm({
  provinces,
  mode,
  onModeChange,
  draftPin,
  selectedMarket,
  onClose,
}: Props) {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [userProvince, setUserProvince] = useState("");
  const [userDistrict, setUserDistrict] = useState("");
  const [userDistricts, setUserDistricts] = useState<District[]>([]);
  const [placeName, setPlaceName] = useState("");
  const [placeType, setPlaceType] = useState<MarketTypeSlug>("semt_pazari");
  const [explanation, setExplanation] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!userProvince) {
      setUserDistricts([]);
      setUserDistrict("");
      return;
    }
    listDistricts(userProvince)
      .then(setUserDistricts)
      .catch(() => setUserDistricts([]));
  }, [userProvince]);

  function validate(): string | null {
    if (!firstName.trim() || !lastName.trim()) return "Ad ve soyad gerekli.";
    if (!EMAIL_RE.test(email.trim())) return "Geçerli bir e-posta girin.";
    if (!explanation.trim()) return "Lütfen kısa bir açıklama yazın.";
    if (mode === "add") {
      if (!placeName.trim()) return "Yeni yer için bir ad girin.";
      if (!draftPin) return "Haritaya tıklayarak yerin konumunu işaretleyin.";
    } else if (!selectedMarket) {
      return "Güncellenecek pazarı haritadan seçin.";
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitSuggestion({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim(),
        user_province: userProvince || undefined,
        user_district: userDistrict || undefined,
        suggestion_type: mode,
        explanation: explanation.trim(),
        website,
        ...(mode === "add"
          ? {
              name: placeName.trim(),
              market_type: placeType,
              latitude: draftPin?.lat,
              longitude: draftPin?.lng,
            }
          : { market_id: selectedMarket?.id }),
      });
      setDone(true);
    } catch {
      setError("Öneri gönderilemedi. Lütfen daha sonra tekrar deneyin.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Yer öner</h2>
          <p className="text-xs text-ink-muted">
            Eksik bir pazarı ekleyin veya mevcut bir pazarın bilgisini düzeltin.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Kapat"
          className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-surface-muted hover:text-ink"
        >
          <X size={16} />
        </button>
      </div>

      {done ? (
        <div className="space-y-3">
          <p className="text-sm text-success">
            Teşekkürler! Öneriniz alındı ve incelenmek üzere kaydedildi.
          </p>
          <button type="button" onClick={onClose} className="btn-ghost">
            Kapat
          </button>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="inline-flex rounded-xl border border-surface-border bg-white p-1">
            {(["add", "update"] as SuggestionType[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => onModeChange(m)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                  mode === m
                    ? "bg-indigo-500 text-white shadow-soft"
                    : "text-ink-soft hover:bg-surface-muted",
                )}
              >
                {m === "add" ? "Yeni yer ekle" : "Mevcut yeri güncelle"}
              </button>
            ))}
          </div>

          {mode === "add" ? (
            <div className="space-y-3">
              <p className="text-xs text-ink-muted">
                Haritaya tıklayarak yerin konumunu işaretleyin.{" "}
                {draftPin ? (
                  <span className="text-success">
                    Konum seçildi: {draftPin.lat.toFixed(5)}, {draftPin.lng.toFixed(5)}
                  </span>
                ) : (
                  <span className="text-danger">Henüz konum seçilmedi.</span>
                )}
              </p>
              <Field label="Yer adı">
                <input
                  type="text"
                  value={placeName}
                  onChange={(e) => setPlaceName(e.target.value)}
                  placeholder="Örn. Cumartesi Semt Pazarı"
                  className={inputCls}
                />
              </Field>
              <Field label="Tür">
                <select
                  value={placeType}
                  onChange={(e) => setPlaceType(e.target.value as MarketTypeSlug)}
                  className={inputCls}
                >
                  {PLACE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          ) : (
            <p className="text-xs text-ink-muted">
              Haritadan güncellemek istediğiniz pazarı seçin.{" "}
              {selectedMarket ? (
                <span className="text-success">Seçilen: {selectedMarket.name}</span>
              ) : (
                <span className="text-danger">Henüz pazar seçilmedi.</span>
              )}
            </p>
          )}

          <Field label="Açıklama">
            <textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="Önerinizi kısaca açıklayın."
              className={cn(inputCls, "resize-y")}
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Ad">
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Soyad">
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className={inputCls}
              />
            </Field>
          </div>
          <Field label="E-posta">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputCls}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="İl">
              <select
                value={userProvince}
                onChange={(e) => setUserProvince(e.target.value)}
                className={inputCls}
              >
                <option value="">Seçin</option>
                {provinces.map((p) => (
                  <option key={p.slug} value={p.slug}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="İlçe">
              <select
                value={userDistrict}
                onChange={(e) => setUserDistrict(e.target.value)}
                disabled={!userProvince}
                className={cn(inputCls, "disabled:opacity-50")}
              >
                <option value="">Seçin</option>
                {userDistricts.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {/* Honeypot — hidden from real users; bots tend to fill it. */}
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            aria-hidden="true"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            className="hidden"
          />

          {error && <p className="text-xs text-danger">{error}</p>}

          <div className="flex items-center gap-2">
            <button type="submit" disabled={submitting} className="btn-primary disabled:opacity-60">
              {submitting ? "Gönderiliyor…" : "Öneriyi gönder"}
            </button>
            <button type="button" onClick={onClose} className="btn-ghost">
              Vazgeç
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-xl border border-surface-border bg-white px-3 py-2 text-sm text-ink outline-none transition-all focus:border-indigo-400 focus:shadow-ring";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-ink-muted">{label}</span>
      {children}
    </label>
  );
}
