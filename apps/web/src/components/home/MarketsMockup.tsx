import { cn } from "@/lib/cn";

const PINS: { left: string; top: string; producer?: boolean }[] = [
  { left: "14%", top: "62%" },
  { left: "23%", top: "36%", producer: true },
  { left: "34%", top: "54%" },
  { left: "44%", top: "40%" },
  { left: "56%", top: "62%", producer: true },
  { left: "66%", top: "44%" },
  { left: "76%", top: "58%" },
  { left: "86%", top: "32%", producer: true },
];

// Tooltip anchor sits between pin 4 and pin 5 so it never overlaps a pin's
// solid dot. The triangle pointer below the card points down at this y.
const TOOLTIP_X = "50%";
const TOOLTIP_Y = "20%";

export function MarketsMockup() {
  return (
    <div className="relative aspect-[5/4] w-full overflow-hidden rounded-2xl border border-surface-border bg-surface-subtle">
      <svg
        viewBox="0 0 500 400"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full text-surface-border"
        aria-hidden
      >
        <g stroke="currentColor" strokeWidth="0.6" opacity="0.8">
          {Array.from({ length: 14 }).map((_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 30} x2="500" y2={i * 30} />
          ))}
          {Array.from({ length: 18 }).map((_, i) => (
            <line key={`v${i}`} x1={i * 30} y1="0" x2={i * 30} y2="400" />
          ))}
        </g>
        <g fill="none" stroke="#C4CF9E" strokeWidth="1.6" opacity="0.8">
          <path d="M30 200 Q 90 160 160 180 T 290 170 T 410 200 T 490 220" />
          <path d="M70 270 Q 160 240 230 255 T 380 280 T 480 300" />
          <path d="M40 110 Q 130 90 220 120 T 380 100" />
        </g>
      </svg>

      {PINS.map((p, i) => {
        // Staggered delays so the pulses ripple across the grid instead of
        // firing in unison.
        const pulseDelay = `${(i * 0.35).toFixed(2)}s`;
        const color = p.producer ? "bg-leaf-500" : "bg-crate-500";
        return (
          <span
            key={i}
            className="absolute"
            style={{ left: p.left, top: p.top, transform: "translate(-50%,-100%)" }}
          >
            <span className="relative block">
              <span
                className={cn(
                  "absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-40 motion-safe:animate-[mapPulse_2.8s_ease-out_infinite]",
                  color,
                )}
                style={{ animationDelay: pulseDelay }}
              />
              <span
                className={cn(
                  "relative block h-2 w-2 rounded-full shadow-[0_0_0_2px_white]",
                  color,
                )}
              />
            </span>
          </span>
        );
      })}

      <div
        className="absolute z-10"
        style={{ left: TOOLTIP_X, top: TOOLTIP_Y, transform: "translate(-50%, 0)" }}
      >
        <div className="rounded-md border border-surface-border bg-white px-3 py-2 text-left">
          <div className="font-display text-[12px] font-semibold text-ink">Kadıköy Salı Pazarı</div>
          <div className="mt-0.5 text-[10px] text-ink-muted">Her salı kurulan semt pazarı</div>
          <div className="mt-1 text-[10px] font-medium text-leaf-700">1,2 km uzağınızda</div>
        </div>
        <div className="mx-auto h-2 w-2 -translate-y-1 rotate-45 border-b border-r border-surface-border bg-white" />
      </div>

      <div className="absolute bottom-3 left-3 flex items-center gap-3 rounded-md border border-surface-border bg-white/90 px-2.5 py-1 text-[10px] font-medium text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-crate-500" />
          Semt
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-leaf-500" />
          Üretici
        </span>
      </div>
    </div>
  );
}
