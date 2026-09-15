"use client";

type GoogleFundingChoices = {
  callbackQueue?: Array<Record<string, () => void>>;
  showRevocationMessage?: () => void;
};

declare global {
  interface Window {
    googlefc?: GoogleFundingChoices;
  }
}

/**
 * Reopens the Google Funding Choices consent dialog. Only render this when the
 * CMP loader is enabled (see app/layout.tsx); the callback queue lets a click
 * that lands before the CMP has loaded still take effect once it's ready.
 */
export function CookieSettingsButton({ className }: { className?: string }) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        window.googlefc = window.googlefc ?? {};
        window.googlefc.callbackQueue = window.googlefc.callbackQueue ?? [];
        window.googlefc.callbackQueue.push({
          CONSENT_API_READY: () => window.googlefc?.showRevocationMessage?.(),
        });
      }}
    >
      Çerez ayarları
    </button>
  );
}
