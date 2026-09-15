const BARS = [38, 52, 44, 66, 58, 80, 70, 84, 92, 78];

export function TrendsMockup() {
  const sparkline = "0,82 30,74 60,60 90,64 120,42 150,50 180,30 210,38 240,20 270,28 300,10";

  return (
    <div className="relative aspect-[5/4] w-full overflow-hidden rounded-2xl border border-surface-border bg-white">
      <div className="flex items-center justify-between border-b border-surface-border bg-surface-subtle px-4 py-2.5">
        <div className="font-display text-[13px] font-semibold text-ink">Fiyat geçmişi</div>
        <div className="flex gap-1 text-[10px] font-medium tabular-nums">
          {["1H", "1A", "3A", "6A", "1Y"].map((label, i) => (
            <span
              key={label}
              className={
                i === 2
                  ? "rounded-sm bg-ink px-1.5 py-0.5 text-surface-subtle"
                  : "rounded-sm px-1.5 py-0.5 text-ink-faint"
              }
            >
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="px-5 pt-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[12px] font-medium text-ink-muted">Domates (yuvarlak)</div>
            <div className="mt-2 flex items-center gap-2">
              <span className="price-tag text-[22px]">32,40 ₺</span>
              <span className="rounded-sm bg-surface-subtle px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums text-success">
                +12,4%
              </span>
            </div>
          </div>
          <div className="text-right text-[10px] text-ink-faint">
            <div>Ortalama hal fiyatı</div>
            <div className="mt-0.5">son 90 gün</div>
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
              <stop offset="0%" stopColor="#C4432B" stopOpacity="0.14" />
              <stop offset="100%" stopColor="#C4432B" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,100 ${sparkline} 300,100`} fill="url(#sparkFill)" />
          <polyline
            points={sparkline}
            fill="none"
            stroke="#C4432B"
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
            fill="#C4432B"
            className="motion-safe:animate-[sparkDot_5s_ease-in-out_infinite]"
          />
        </svg>
      </div>

      <div className="absolute bottom-4 left-5 right-5">
        <div className="mb-1.5 flex items-center justify-between text-[10.5px]">
          <span className="font-medium text-ink-muted">Haftalık ortalama</span>
          <span className="tabular-nums text-ink-faint">10 hafta</span>
        </div>
        <div className="flex h-[52px] items-end gap-1.5">
          {BARS.map((h, i) => (
            <div key={i} className="flex h-full flex-1 items-end">
              <div
                className={i === BARS.length - 1 ? "w-full bg-crate-500" : "w-full bg-leaf-300"}
                style={{ height: `${h}%` }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
