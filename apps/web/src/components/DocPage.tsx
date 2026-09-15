/** Shared shell for text pages: about, contact, and the legal pages. */
export function DocPage({
  title,
  updated,
  intro,
  children,
}: {
  title: string;
  updated?: string;
  intro?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <article className="mx-auto max-w-3xl space-y-8 pb-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold lg:text-5xl">{title}</h1>
        {updated && <p className="text-sm text-ink-muted">Son güncelleme: {updated}</p>}
        {intro && <div className="text-lg leading-relaxed text-ink-soft">{intro}</div>}
      </header>
      {children}
    </article>
  );
}

export function DocSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="space-y-2 text-[15px] leading-relaxed text-ink-soft [&_a]:text-crate-700 [&_a]:underline [&_a]:underline-offset-2">
        {children}
      </div>
    </section>
  );
}
