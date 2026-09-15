"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import {
  AdminApiError,
  approveSuggestion,
  listAdminSuggestions,
  rejectSuggestion,
  type AdminSuggestion,
} from "@/lib/api";

const TOKEN_KEY = "lb_admin_token";
const STATUSES = ["pending", "approved", "rejected", "all"] as const;
type StatusFilter = (typeof STATUSES)[number];

export default function AdminSuggestionsPage() {
  const [token, setToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [authed, setAuthed] = useState(false);
  const [status, setStatus] = useState<StatusFilter>("pending");
  const [items, setItems] = useState<AdminSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (tok: string, st: StatusFilter): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listAdminSuggestions(tok, st);
      setItems(rows);
      setAuthed(true);
      sessionStorage.setItem(TOKEN_KEY, tok);
    } catch (e) {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        setAuthed(false);
        sessionStorage.removeItem(TOKEN_KEY);
        setError("Geçersiz yönetici anahtarı.");
      } else if (e instanceof AdminApiError && e.status === 503) {
        setError("Yönetim arayüzü yapılandırılmamış (ADMIN_TOKEN tanımlı değil).");
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Restore a previously entered token from the session.
  useEffect(() => {
    const saved = sessionStorage.getItem(TOKEN_KEY);
    if (saved) {
      setToken(saved);
      void load(saved, "pending");
    }
  }, [load]);

  function handleLogin(e: React.FormEvent): void {
    e.preventDefault();
    setToken(tokenInput);
    void load(tokenInput, status);
  }

  function logout(): void {
    sessionStorage.removeItem(TOKEN_KEY);
    setAuthed(false);
    setToken("");
    setTokenInput("");
    setItems([]);
  }

  async function act(kind: "approve" | "reject", id: number): Promise<void> {
    setNotice(null);
    setError(null);
    try {
      const result =
        kind === "approve"
          ? await approveSuggestion(token, id)
          : await rejectSuggestion(token, id, window.prompt("Not (isteğe bağlı):") ?? undefined);
      setNotice(`#${result.id}: ${result.detail}`);
      await load(token, status);
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : String(e));
    }
  }

  if (!authed) {
    return (
      <form onSubmit={handleLogin} className="mx-auto max-w-sm space-y-4 py-16">
        <h1 className="text-2xl font-semibold">Yönetim</h1>
        <p className="text-sm text-ink-muted">Erişim için yönetici anahtarını girin.</p>
        <input
          type="password"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="ADMIN_TOKEN"
          className="w-full rounded-xl border border-surface-border bg-white px-3 py-2 text-sm outline-none focus:border-crate-400 focus:shadow-ring"
        />
        <button type="submit" className="btn-primary w-full" disabled={loading}>
          {loading ? "Kontrol ediliyor…" : "Giriş"}
        </button>
        {error && <p className="text-sm text-danger">{error}</p>}
      </form>
    );
  }

  return (
    <div className="space-y-6 py-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Öneri yönetimi</h1>
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => {
              const next = e.target.value as StatusFilter;
              setStatus(next);
              void load(token, next);
            }}
            className="rounded-xl border border-surface-border bg-white px-3 py-2 text-sm outline-none focus:border-crate-400 focus:shadow-ring"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button type="button" onClick={logout} className="btn-ghost">
            Çıkış
          </button>
        </div>
      </header>

      {notice && <div className="card p-3 text-sm text-success">{notice}</div>}
      {error && <div className="card p-3 text-sm text-danger">{error}</div>}
      {loading && <div className="card p-3 text-center text-xs text-ink-muted">Yükleniyor…</div>}
      {!loading && items.length === 0 && (
        <div className="card p-6 text-center text-sm text-ink-muted">Öneri yok.</div>
      )}

      <ul className="space-y-3">
        {items.map((s) => (
          <li key={s.id} className="card space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="chip">
                  {s.suggestion_type === "add" ? "Yeni yer" : "Güncelleme"}
                </span>
                <span
                  className={cn(
                    "rounded-full px-2.5 py-0.5 text-xs font-medium",
                    s.status === "pending"
                      ? "bg-ochre-50 text-ochre-700"
                      : s.status === "approved"
                        ? "bg-surface-muted text-success"
                        : "bg-surface-muted text-danger",
                  )}
                >
                  {s.status}
                </span>
              </div>
              <span className="text-xs text-ink-muted">{formatDate(s.created_at)}</span>
            </div>

            <p className="text-sm text-ink">{s.explanation}</p>

            <dl className="grid gap-x-6 gap-y-1 text-xs text-ink-soft sm:grid-cols-2">
              <Detail label="Gönderen" value={`${s.first_name} ${s.last_name} · ${s.email}`} />
              {s.suggestion_type === "add" ? (
                <>
                  <Detail label="Önerilen ad" value={s.proposed_name} />
                  <Detail label="Tür" value={s.proposed_market_type} />
                </>
              ) : (
                <Detail label="Pazar" value={s.market_name} />
              )}
              {(s.province || s.district) && (
                <Detail
                  label="Konum"
                  value={[s.district, s.province].filter(Boolean).join(", ") || null}
                />
              )}
              {s.latitude != null && s.longitude != null && (
                <Detail
                  label="Koordinat"
                  value={`${s.latitude.toFixed(5)}, ${s.longitude.toFixed(5)}`}
                />
              )}
            </dl>

            {s.status === "pending" && (
              <div className="flex gap-2">
                <button type="button" onClick={() => act("approve", s.id)} className="btn-primary">
                  Onayla
                </button>
                <button type="button" onClick={() => act("reject", s.id)} className="btn-ghost">
                  Reddet
                </button>
              </div>
            )}
            {s.review_note && <p className="text-xs text-ink-muted">Not: {s.review_note}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex gap-1">
      <dt className="text-ink-muted">{label}:</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
