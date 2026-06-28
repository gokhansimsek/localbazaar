import { ArrowDownRight, ArrowUpRight } from "lucide-react";

type Row = {
  name: string;
  variety: string;
  price: string;
  unit: string;
  change: string;
  dir: "up" | "down";
};

const ROWS: Row[] = [
  { name: "Domates", variety: "Yuvarlak", price: "32,40", unit: "Kg", change: "+2,1%", dir: "up" },
  { name: "Salatalık", variety: "Sera", price: "18,90", unit: "Kg", change: "-0,8%", dir: "down" },
  { name: "Patates", variety: "Sarı", price: "12,15", unit: "Kg", change: "+0,3%", dir: "up" },
  { name: "Soğan", variety: "Kuru", price: "9,80", unit: "Kg", change: "-1,4%", dir: "down" },
  { name: "Biber", variety: "Charliston", price: "44,20", unit: "Kg", change: "+3,7%", dir: "up" },
  { name: "Patlıcan", variety: "Kemer", price: "27,55", unit: "Kg", change: "+0,9%", dir: "up" },
  { name: "Marul", variety: "Kıvırcık", price: "8,60", unit: "Adet", change: "-2,2%", dir: "down" },
  { name: "Limon", variety: "Mayer", price: "21,30", unit: "Kg", change: "+1,5%", dir: "up" },
];

export function PricesMockup() {
  const loop = [...ROWS, ...ROWS];
  return (
    <div className="relative aspect-[5/4] w-full overflow-hidden rounded-2xl border border-surface-border bg-white shadow-soft">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-2.5">
        <div className="flex items-center gap-2 text-[10.5px] font-medium uppercase tracking-[0.16em] text-ink-muted">
          <span className="relative inline-flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-success/70 opacity-75 motion-safe:animate-ping" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
          </span>
          Canlı Bülten
        </div>
        <div className="font-mono text-[10px] text-ink-faint">10 HAZ · TRY</div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-9 z-10 h-10 bg-gradient-to-b from-white to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-14 bg-gradient-to-t from-white to-transparent" />

      <div className="relative h-[calc(100%-2.55rem)]">
        <div className="motion-safe:animate-[priceScroll_22s_linear_infinite]">
          {loop.map((row, i) => (
            <div
              key={i}
              className="flex items-center justify-between border-b border-surface-border/60 px-4 py-[9px]"
            >
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-ink">{row.name}</div>
                <div className="text-[10px] text-ink-faint">
                  {row.variety} · {row.unit}
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <span className="font-mono text-[13px] font-semibold tabular-nums text-ink">
                  {row.price} ₺
                </span>
                <span
                  className={
                    row.dir === "up"
                      ? "inline-flex items-center gap-0.5 rounded-md bg-success/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-success"
                      : "inline-flex items-center gap-0.5 rounded-md bg-danger/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-danger"
                  }
                >
                  {row.dir === "up" ? (
                    <ArrowUpRight size={10} strokeWidth={2.5} />
                  ) : (
                    <ArrowDownRight size={10} strokeWidth={2.5} />
                  )}
                  {row.change}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
