"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ChevronDown, Menu, PanelLeftClose, PanelLeftOpen, ShieldCheck, X } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { ExperimentalBadge } from "@/components/experimental-badge";
import { workflowById, workspaceGroups } from "@/lib/workflows";
import { cn } from "@/lib/utils";

function WorkspaceNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const selectedDiscipline = search.get("discipline") ?? "biostats";

  return (
    <nav aria-label="Clinical workspaces" className="space-y-7">
      {workspaceGroups.map((group) => (
        <div key={group.id}>
          <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.17em] text-[#8fa9a3]">{group.title}</p>
          <div className="space-y-1">
            {group.items.map((item) => {
              const active = pathname === item.pathname
                && (item.pathname !== "/workflows/clinical-document" || selectedDiscipline === item.discipline);
              const experimental = workflowById[item.workflow].experimental;
              const Icon = item.icon;
              return (
                <Link
                  key={`${group.id}-${item.label}`}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  aria-label={experimental ? `${item.label} (Experimental)` : item.label}
                  className={cn(
                    "focus-ring group flex items-center gap-3 rounded-md border px-3 py-2.5 text-sm font-medium transition",
                    active
                      ? "border-[#d8e6df] bg-[#f7f3ea] text-[#173f3b] shadow-sm"
                      : "border-transparent text-[#c6d3cf] hover:border-white/10 hover:bg-white/[0.06] hover:text-white",
                  )}
                >
                  <Icon size={16} strokeWidth={1.8} className={active ? "text-[#b6533c]" : "text-[#7fa099] group-hover:text-[#c6d3cf]"} />
                  <span className="min-w-0 flex-1">{item.label}</span>
                  {experimental && <ExperimentalBadge compact />}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Brand({ dark = false }: { dark?: boolean }) {
  return (
    <Link href="/" className="focus-ring flex items-center gap-3 rounded-md" aria-label="Clinical Workbench home">
      <span className={cn("grid h-9 w-9 place-items-center rounded-sm border text-[11px] font-black tracking-[-0.04em]", dark ? "border-[#315a55] bg-[#204a45] text-[#f7f3ea]" : "border-[#cfd8d4] bg-[#173f3b] text-white")}>
        CW
      </span>
      <span>
        <span className={cn("block text-sm font-semibold tracking-tight", dark ? "text-white" : "text-slate-900")}>Clinical Workbench</span>
        <span className={cn("block text-[9px] font-semibold uppercase tracking-[0.17em]", dark ? "text-[#8fa9a3]" : "text-slate-500")}>Artifact operations</span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  return (
    <div className={cn("min-h-screen lg:grid", sidebarOpen ? "lg:grid-cols-[264px_minmax(0,1fr)]" : "lg:grid-cols-[minmax(0,1fr)]")}>
      <aside className={cn("h-screen flex-col border-r border-[#244b47] bg-[#173f3b] px-4 py-5 lg:sticky lg:top-0", sidebarOpen ? "hidden lg:flex" : "hidden")}>
        <div className="px-2"><Brand dark /></div>
        <div className="mt-8 border-y border-white/10 px-2 py-4">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#8fa9a3]">Active workspace</p>
          <p className="mt-1.5 text-sm font-semibold text-white">Clinical development</p>
          <p className="mt-1 text-xs text-[#9db2ad]">De-identified sandbox</p>
        </div>
        <div className="mt-7 min-h-0 flex-1 overflow-y-auto"><WorkspaceNavigation /></div>
        <div className="mt-5 space-y-3 border-t border-white/10 pt-4">
          <ConfigStatus compact tone="dark" />
          <p className="flex items-start gap-2 px-1 text-[10px] leading-4 text-[#8fa9a3]"><ShieldCheck size={12} className="mt-0.5 shrink-0" />Synthetic or de-identified data only. Expert review required.</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-[#d9ddd9] bg-[#fffefa]/95 px-4 backdrop-blur-md lg:px-8">
          <div className="lg:hidden"><Brand /></div>
          <button
            type="button"
            aria-label={sidebarOpen ? "Collapse navigation sidebar" : "Expand navigation sidebar"}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((value) => !value)}
            className="focus-ring hidden items-center gap-2 rounded-md px-2 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 lg:flex"
          >
            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
            <span>{sidebarOpen ? "Hide navigation" : "Show navigation"}</span>
          </button>
          <div className="hidden items-center gap-3 text-xs font-medium text-slate-600 sm:flex">
            <span className="text-slate-400">Clinical Development</span>
            <span aria-hidden="true" className="h-3 w-px bg-slate-300" />
            <span className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />Local environment</span>
          </div>
          <button
            type="button"
            aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((value) => !value)}
            className="focus-ring grid h-9 w-9 place-items-center rounded-md border border-slate-300 text-slate-700 lg:hidden"
          >
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </header>

        {mobileOpen && (
          <div className="fixed inset-x-0 top-16 z-30 max-h-[calc(100vh-4rem)] overflow-y-auto border-b border-[#244b47] bg-[#173f3b] p-5 shadow-2xl lg:hidden">
            <div className="mb-5 flex items-center justify-between rounded-md border border-white/10 bg-white/[0.05] px-3 py-3 text-sm font-semibold text-white">
              Clinical development <ChevronDown size={15} className="text-[#8fa9a3]" />
            </div>
            <WorkspaceNavigation onNavigate={() => setMobileOpen(false)} />
            <div className="mt-6 border-t border-white/10 pt-4"><ConfigStatus compact tone="dark" /></div>
          </div>
        )}

        <main className="min-h-[calc(100vh-7.5rem)]">{children}</main>
        <footer className="border-t border-[#d9ddd9] bg-[#ebe8e1] px-5 py-5 text-[11px] leading-5 text-slate-500 lg:px-8">
          Draft outputs require review by qualified clinical and regulatory professionals before use.
        </footer>
      </div>
    </div>
  );
}
