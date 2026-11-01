"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ChevronDown, FlaskConical, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { workspaceGroups } from "@/lib/workflows";
import { cn } from "@/lib/utils";

function WorkspaceNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const selectedDiscipline = search.get("discipline") ?? "biostats";

  return (
    <nav aria-label="Clinical workspaces" className="space-y-7">
      {workspaceGroups.map((group) => (
        <div key={group.id}>
          <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-500">{group.title}</p>
          <div className="space-y-1">
            {group.items.map((item) => {
              const active = pathname === item.pathname
                && (item.pathname !== "/workflows/clinical-document" || selectedDiscipline === item.discipline);
              const Icon = item.icon;
              return (
                <Link
                  key={`${group.id}-${item.label}`}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "focus-ring group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
                    active ? "bg-white text-zinc-950 shadow-sm" : "text-zinc-400 hover:bg-white/5 hover:text-white",
                  )}
                >
                  <Icon size={17} className={active ? "text-clinical-600" : "text-zinc-500 group-hover:text-zinc-300"} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/" className="focus-ring flex items-center gap-3 rounded-lg" aria-label="Clinical AI Workbench home">
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-clinical-500 to-violet-400 text-white shadow-lg shadow-violet-950/30">
        <FlaskConical size={18} aria-hidden="true" />
      </span>
      <span>
        <span className="block text-sm font-semibold tracking-tight text-white">Clinical AI</span>
        <span className="block text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-500">Artifact workbench</span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  return (
    <div className={cn("min-h-screen lg:grid", sidebarOpen ? "lg:grid-cols-[272px_minmax(0,1fr)]" : "lg:grid-cols-[minmax(0,1fr)]")}>
      <aside className={cn("h-screen flex-col border-r border-white/10 bg-[#0d0d0f] px-4 py-5 lg:sticky lg:top-0", sidebarOpen ? "hidden lg:flex" : "hidden")}>
        <div className="px-2"><Brand /></div>
        <div className="mt-7 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3">
          <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">Workspace</p>
          <p className="mt-1 text-sm font-semibold text-zinc-100">Clinical development</p>
          <p className="mt-0.5 text-xs text-zinc-500">Synthetic sandbox</p>
        </div>
        <div className="mt-7 min-h-0 flex-1 overflow-y-auto"><WorkspaceNavigation /></div>
        <div className="mt-5 space-y-3 border-t border-white/10 pt-4">
          <ConfigStatus compact tone="dark" />
          <p className="px-1 text-[10px] leading-4 text-zinc-600">Demo only · No PHI · Expert review required</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-white/10 bg-[#111113]/90 px-4 backdrop-blur-xl lg:px-8">
          <div className="lg:hidden"><Brand /></div>
          <button
            type="button"
            aria-label={sidebarOpen ? "Collapse navigation sidebar" : "Expand navigation sidebar"}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((value) => !value)}
            className="focus-ring hidden items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-400 transition hover:bg-white/[0.05] hover:text-white lg:flex"
          >
            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
            <span>{sidebarOpen ? "Collapse workspace navigation" : "Expand workspace navigation"}</span>
          </button>
          <div className="hidden items-center gap-2 text-xs font-medium text-zinc-400 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Local artifact environment
          </div>
          <button
            type="button"
            aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((value) => !value)}
            className="focus-ring grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-zinc-200 lg:hidden"
          >
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </header>

        {mobileOpen && (
          <div className="fixed inset-x-0 top-16 z-30 max-h-[calc(100vh-4rem)] overflow-y-auto border-b border-white/10 bg-[#0d0d0f] p-5 shadow-2xl lg:hidden">
            <div className="mb-5 flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3 text-sm font-semibold text-zinc-100">
              Clinical development <ChevronDown size={15} className="text-zinc-500" />
            </div>
            <WorkspaceNavigation onNavigate={() => setMobileOpen(false)} />
            <div className="mt-6 border-t border-white/10 pt-4"><ConfigStatus compact tone="dark" /></div>
          </div>
        )}

        <main>{children}</main>
        <footer className="border-t border-white/10 bg-[#111113] px-5 py-6 text-xs leading-5 text-zinc-500 lg:px-8">
          Draft outputs are not validated for clinical or regulatory use. Qualified experts must review all content.
        </footer>
      </div>
    </div>
  );
}
