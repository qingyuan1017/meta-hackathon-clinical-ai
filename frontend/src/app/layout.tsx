import type { Metadata } from "next";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "Clinical AI Artifact Workbench",
  description: "Draft clinical artifacts from synthetic and de-identified study inputs.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
              <Link href="/" className="focus-ring flex items-center gap-3 rounded-lg" aria-label="Clinical AI Workbench home">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-ink text-white shadow-sm">
                  <FlaskConical size={20} aria-hidden="true" />
                </span>
                <span>
                  <span className="block text-sm font-extrabold tracking-tight text-ink">Clinical AI</span>
                  <span className="block text-xs font-medium tracking-[0.18em] text-slate-500">ARTIFACT WORKBENCH</span>
                </span>
              </Link>
              <div className="hidden items-center gap-2 text-xs font-semibold text-slate-500 sm:flex">
                <span className="h-2 w-2 rounded-full bg-amber-400" />
                Hackathon demonstration · synthetic data only
              </div>
            </div>
          </header>
          <main>{children}</main>
          <footer className="border-t border-slate-200 bg-white/70">
            <div className="mx-auto max-w-7xl px-5 py-8 text-xs leading-5 text-slate-500 lg:px-8">
              Draft outputs are not validated for clinical or regulatory use. Qualified experts must review all content.
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
