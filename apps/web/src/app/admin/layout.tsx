import type { Metadata } from "next";

// Hidden surface: keep it out of search indexes. There is no nav link to it —
// it's reached by typing /admin/suggestions in the address bar.
export const metadata: Metadata = {
  title: "Yönetim — Öneriler",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
