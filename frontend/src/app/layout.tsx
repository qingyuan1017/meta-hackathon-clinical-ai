import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "Clinical Workbench",
  description: "Prepare and review clinical development artifacts from de-identified study inputs.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>
        <Providers>
          <Suspense fallback={<main>{children}</main>}><AppShell>{children}</AppShell></Suspense>
        </Providers>
      </body>
    </html>
  );
}
