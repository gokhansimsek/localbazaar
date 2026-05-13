const BARS = [38, 52, 44, 66, 58, 80, 70, 84, 92, 78];

export function TrendsMockup() {
  const sparkline = "0,82 30,74 60,60 90,64 120,42 150,50 180,30 210,38 240,20 270,28 300,10";

  return (
    <div className="relative aspect-[5/4] w-full overflow-hidden rounded-2xl border border-surface-border bg-white shadow-soft">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-2.5">
        <div className="text-[10.5px] font-medium uppercase tracking-[0.16em] text-ink-muted">
          Trend
        </div>
        <div className="flex gap-1 font-mono text-[10px]">
          {["1H", "1A", "3A", "6A", "1Y"].map((label, i) => (
            <span
              key={label}
              className={
                i === 2
                  ? "rounded-md bg-ink px-1.5 py-0.5 text-white"
                  : "rounded-md px-1.5 py-0.5 text-ink-faint"
              }
            >
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="px-5 pt-4">
        <div className="flex items-baseline justify-between">
          <div>
            <div className="text-[10.5px] font-medium uppercase tracking-[0.14em] text-ink-muted">
              Domates · Yuvarlak
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-display text-[26px] font-semibold tracking-[-0.02em] text-ink tabular-nums">
                32,40 ₺
              </span>
              <span className="rounded-md bg-success/10 px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-success">
                +12,4%
              </span>
            </div>
          </div>
          <div className="text-right text-[10px] text-ink-faint">
            <div>Ort. Hal Fiyatı</div>
            <div className="mt-0.5 font-mono">Son 90 gün</div>
          </div>
        </div>

        <svg
          className="mt-3 h-[78px] w-full"
          viewBox="0 0 300 100"
          preserveAspectRatio="none"
          aria-hidden
        >
          <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#635BFF" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#635BFF" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,100 ${sparkline} 300,100`} fill="url(#sparkFill)" />
          <polyline
            points={sparkline}
            fill="none"
            stroke="#635BFF"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            strokeDasharray="600"
            strokeDashoffset="0"
            className="motion-safe:animate-[sparkDraw_5s_ease-in-out_infinite]"
          />
          <circle
            cx="300"
            cy="10"
            r="3"
            fill="#635BFF"
            className="motion-safe:animate-[sparkDot_5s_ease-in-out_infinite]"
          />
        </svg>
      </div>

      <div className="absolute bottom-4 left-5 right-5">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[10.5px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Haftalık ortalama
          </span>
          <span className="font-mono text-[10px] text-ink-faint">10 hafta</span>
        </div>
        <div className="flex h-[52px] items-end gap-1.5">
          {BARS.map((h, i) => (
            <div key={i} className="flex flex-1 items-end">
              <div
                className="w-full origin-bottom rounded-[2px] bg-gradient-to-t from-indigo-500 to-indigo-300 motion-safe:animate-[barRise_5s_ease-in-out_infinite]"
                style={{ height: `${h}%`, animationDelay: `${i * 120}ms` }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
