const PINS: { left: string; top: string; delay: string }[] = [
  { left: "16%", top: "58%", delay: "0s" },
  { left: "26%", top: "38%", delay: "0.6s" },
  { left: "38%", top: "52%", delay: "1.2s" },
  { left: "48%", top: "34%", delay: "0.3s" },
  { left: "58%", top: "60%", delay: "1.8s" },
  { left: "68%", top: "44%", delay: "0.9s" },
  { left: "78%", top: "58%", delay: "2.1s" },
  { left: "84%", top: "30%", delay: "1.5s" },
];

const TOOLTIP_X = "48%";
const TOOLTIP_Y = "34%";

export function MarketsMockup() {
  return (
    <div className="relative aspect-[5/4] w-full overflow-hidden rounded-2xl border border-surface-border bg-white shadow-soft">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_60%_38%,#EEF0FF_0%,#F6F9FC_55%,#FFFFFF_100%)]" />

      <svg
        viewBox="0 0 500 400"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full text-surface-border"
        aria-hidden
      >
        <g stroke="currentColor" strokeWidth="0.6" opacity="0.7">
          {Array.from({ length: 14 }).map((_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 30} x2="500" y2={i * 30} />
          ))}
          {Array.from({ length: 18 }).map((_, i) => (
            <line key={`v${i}`} x1={i * 30} y1="0" x2={i * 30} y2="400" />
          ))}
        </g>
        <g fill="none" stroke="#BAB4FF" strokeWidth="1.4" opacity="0.55">
          <path d="M30 200 Q 90 160 160 180 T 290 170 T 410 200 T 490 220" />
          <path d="M70 270 Q 160 240 230 255 T 380 280 T 480 300" />
          <path d="M40 110 Q 130 90 220 120 T 380 100" />
        </g>
      </svg>

      <div className="pointer-events-none absolute inset-y-0 -left-1/3 w-1/3 bg-[linear-gradient(90deg,transparent_0%,rgba(99,91,255,0.08)_50%,transparent_100%)] motion-safe:animate-[mapScan_6s_ease-in-out_infinite]" />

      {PINS.map((p, i) => (
        <span
          key={i}
          className="absolute"
          style={{ left: p.left, top: p.top, transform: "translate(-50%,-100%)" }}
        >
          <span className="relative block">
            <span
              className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-500/40 motion-safe:animate-[mapPulse_2.6s_ease-out_infinite]"
              style={{ animationDelay: p.delay }}
            />
            <span className="relative block h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_0_2px_white]" />
          </span>
        </span>
      ))}

      <div
        className="absolute z-10 motion-safe:animate-[tooltipFloat_4.5s_ease-in-out_infinite]"
        style={{ left: TOOLTIP_X, top: TOOLTIP_Y, transform: "translate(-50%, -140%)" }}
      >
        <div className="rounded-lg border border-surface-border bg-white px-3 py-2 text-left shadow-soft">
          <div className="text-[11px] font-semibold text-ink">Kadıköy Salı Pazarı</div>
          <div className="mt-0.5 text-[10px] text-ink-muted">Salı · Semt Pazarı</div>
          <div className="mt-1 inline-flex items-center gap-1 text-[10px] text-success">
            <span className="h-1 w-1 rounded-full bg-success" />
            12 esnaf · 1.2 km
          </div>
        </div>
        <div className="mx-auto h-2 w-2 -translate-y-1 rotate-45 border-b border-r border-surface-border bg-white" />
      </div>

      <div className="absolute bottom-3 left-3 flex items-center gap-2 rounded-full border border-surface-border bg-white/85 px-2.5 py-1 text-[10px] font-medium text-ink-muted backdrop-blur">
        <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
        {PINS.length * 1180} pazar · 81 il
      </div>
    </div>
  );
}
