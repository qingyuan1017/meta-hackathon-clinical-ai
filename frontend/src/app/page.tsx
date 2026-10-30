import Link from "next/link";
import { ArrowUpRight, Bot, Download, FolderClock, ShieldCheck, Sparkles } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { workspaceGroups } from "@/lib/workflows";
import { API_URL } from "@/lib/api";

const groupCopy = {
  biostats: "Interpret study intent and create controlled clinical drafts.",
  "data-management": "Translate protocol requirements into collection-ready designs.",
  "stats-programming": "Plan standards-based datasets and analysis displays.",
};

const summaryCards = [
  { icon: Bot, value: "5", label: "Specialist agents" },
  { icon: FolderClock, value: "Local", label: "Persistent job history" },
  { icon: ShieldCheck, value: "Required", label: "De-identified data" },
];

export default function HomePage() {
  return (
    <div className="mx-auto max-w-[1440px] px-5 py-8 lg:px-10 lg:py-10">
      <section className="flex flex-col justify-between gap-6 border-b border-white/10 pb-8 xl:flex-row xl:items-end">
        <div>
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-clinical-700"><Sparkles size={14} /> Clinical AI workspace</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-white sm:text-4xl">Build reviewable clinical artifacts.</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">Choose a functional area to run a specialist agent, review its structured result, and export deterministic draft artifacts.</p>
        </div>
        <div className="w-full xl:w-[340px]"><ConfigStatus /></div>
      </section>

      <section className="mt-8 grid gap-3 sm:grid-cols-3" aria-label="Workspace summary">
        {summaryCards.map(({ icon: Icon, value, label }) => (
          <div key={label} className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.035] px-5 py-4 shadow-sm">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-clinical-500/15 text-violet-300"><Icon size={17} /></span>
            <div><p className="text-sm font-semibold text-zinc-100">{value}</p><p className="text-xs text-zinc-500">{label}</p></div>
          </div>
        ))}
      </section>

      <section className="mt-10" aria-labelledby="workspaces-heading">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Functional areas</p>
          <h2 id="workspaces-heading" className="mt-1 text-xl font-semibold tracking-tight text-zinc-100">Clinical development modules</h2>
          <p className="mt-2 text-sm text-zinc-500">Each module keeps its own generation history, review queue, and artifacts together.</p>
        </div>
        <div className="mt-5 grid gap-4 xl:grid-cols-3">
          {workspaceGroups.map((group, groupIndex) => (
            <div key={group.id} className="overflow-hidden rounded-xl border border-white/10 bg-[#18181b] shadow-sm">
              <div className="border-b border-white/[0.08] px-5 py-5">
                <div className="flex items-center justify-between"><span className="text-xs font-semibold text-clinical-700">0{groupIndex + 1}</span><span className="h-2 w-2 rounded-full bg-clinical-500" /></div>
                <h3 className="mt-5 text-lg font-semibold text-zinc-100">{group.title}</h3>
                <p className="mt-2 min-h-10 text-sm leading-5 text-zinc-400">{groupCopy[group.id]}</p>
              </div>
              <div className="p-2">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link key={item.label} href={item.href} className="focus-ring group flex items-center justify-between rounded-lg px-3 py-3 transition hover:bg-white/[0.05]">
                      <span className="flex items-center gap-3 text-sm font-medium text-zinc-200"><span className="grid h-8 w-8 place-items-center rounded-md border border-white/10 bg-white/[0.03] text-zinc-400"><Icon size={15} /></span>{item.label}</span>
                      <ArrowUpRight size={15} className="text-zinc-400 transition group-hover:text-clinical-600" />
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="mt-10">
        <section className="rounded-xl border border-white/10 bg-[#18181b] p-5 text-white shadow-sm" aria-labelledby="samples-heading">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-300">Safe starting points</p>
          <h2 id="samples-heading" className="mt-2 text-lg font-semibold">Synthetic sample inputs</h2>
          <p className="mt-2 text-sm leading-5 text-zinc-400">Fictional files for exercising every workflow without sensitive data.</p>
          <div className="mt-5 grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {[["synthetic-protocol.md", "Protocol"], ["blank-crf.pdf", "Blank CRF"], ["edc-specification.json", "EDC spec"], ["synthetic-sap.md", "SAP"], ["adam-metadata.json", "ADaM"]].map(([file, label]) => (
              <a key={file} href={`${API_URL}/api/v1/samples/${file}`} className="focus-ring inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.06] px-3 py-2.5 text-xs font-medium text-zinc-200 transition hover:bg-white/10"><Download size={13} />{label}</a>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
