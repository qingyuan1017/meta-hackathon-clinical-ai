import Link from "next/link";
import { ArrowRight, BookOpenCheck, Clock3, Download, FolderKanban, ShieldCheck } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { ExperimentalBadge } from "@/components/experimental-badge";
import { workflowById, workspaceGroups } from "@/lib/workflows";
import { API_URL } from "@/lib/api";

const groupCopy = {
  biostats: "Study design, protocol interpretation, and controlled document authoring.",
  "data-management": "Collection design and study documentation for data operations.",
  "stats-programming": "Standards-based tabulation, analysis displays, and programming assets.",
};

const summaryItems = [
  { icon: FolderKanban, value: "6", label: "Configured workstreams" },
  { icon: Clock3, value: "Local", label: "Run history" },
  { icon: ShieldCheck, value: "Required", label: "De-identification" },
];

const sampleFiles = [
  ["synthetic-protocol.md", "Protocol", "Markdown"],
  ["blank-crf.pdf", "Blank CRF", "PDF"],
  ["edc-specification.json", "EDC specification", "JSON"],
  ["synthetic-sap.md", "Analysis plan", "Markdown"],
  ["adam-metadata.json", "ADaM metadata", "JSON"],
  ["sdtm-demo-edc.json", "SDTM DM/AE EDC", "JSON"],
  ["sdtm-raw-dm.csv", "Raw DM", "CSV"],
  ["sdtm-raw-ae.csv", "Raw AE", "CSV"],
  ["sdtm-raw-ae-mismatch.csv", "Raw AE mismatch", "CSV"],
  ["pinnacle21-demo-report.csv", "P21 report fixture", "CSV"],
] as const;

export default function HomePage() {
  return (
    <div className="mx-auto max-w-[1440px] px-5 py-8 lg:px-10 lg:py-12">
      <section className="grid gap-8 border-b border-slate-300 pb-9 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-end">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#b6533c]">Clinical development / Overview</p>
          <h1 className="editorial-title mt-4 max-w-3xl text-4xl leading-[1.05] text-[#17201f] sm:text-5xl">Clinical artifact workspace</h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-7 text-slate-600">Prepare, review, and export study artifacts across biostatistics, data management, and statistical programming.</p>
        </div>
        <ConfigStatus />
      </section>

      <section className="grid border-b border-slate-300 sm:grid-cols-3" aria-label="Workspace summary">
        {summaryItems.map(({ icon: Icon, value, label }, index) => (
          <div key={label} className={`flex items-center gap-4 py-5 sm:px-5 ${index > 0 ? "border-t border-slate-300 sm:border-l sm:border-t-0" : ""}`}>
            <Icon size={18} strokeWidth={1.7} className="text-[#1f6b62]" />
            <div><p className="text-sm font-semibold text-slate-900">{value}</p><p className="mt-0.5 text-xs text-slate-500">{label}</p></div>
          </div>
        ))}
      </section>

      <section className="mt-11" aria-labelledby="workspaces-heading">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">Workstreams</p>
            <h2 id="workspaces-heading" className="mt-2 text-xl font-semibold tracking-tight text-slate-900">Start with a functional area</h2>
          </div>
          <p className="max-w-md text-sm leading-6 text-slate-500">Each workstream keeps its inputs, review stages, run history, and exports together.</p>
        </div>

        <div className="mt-6 overflow-hidden border-y border-slate-300 bg-[#fffefa] lg:grid lg:grid-cols-3">
          {workspaceGroups.map((group, groupIndex) => (
            <section key={group.id} className={`p-5 lg:p-6 ${groupIndex > 0 ? "border-t border-slate-300 lg:border-l lg:border-t-0" : ""}`}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <span className="font-mono text-[10px] font-bold text-[#b6533c]">0{groupIndex + 1}</span>
                  <h3 className="mt-3 text-lg font-semibold text-slate-900">{group.title}</h3>
                </div>
                <span className="mt-1 h-2 w-2 bg-[#1f6b62]" />
              </div>
              <p className="mt-2 min-h-12 text-sm leading-6 text-slate-500">{groupCopy[group.id]}</p>
              <div className="mt-5 border-t border-slate-200 pt-2">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const experimental = workflowById[item.workflow].experimental;
                  return (
                    <Link key={item.label} href={item.href} aria-label={experimental ? `${item.label} (Experimental)` : item.label} className="focus-ring group -mx-2 flex items-center justify-between rounded-md px-2 py-3 transition hover:bg-[#eef4f1]">
                      <span className="flex min-w-0 items-center gap-3 text-sm font-semibold text-slate-800"><Icon size={16} strokeWidth={1.8} className="shrink-0 text-[#1f6b62]" /><span>{item.label}</span>{experimental && <ExperimentalBadge compact />}</span>
                      <ArrowRight size={15} className="shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-[#b6533c]" />
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </section>

      <section className="mt-12 border border-slate-300 bg-[#fffefa]" aria-labelledby="samples-heading">
        <div className="grid gap-5 border-b border-slate-300 p-5 sm:grid-cols-[1fr_auto] sm:items-end lg:p-6">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-[#1f6b62]"><BookOpenCheck size={14} /> Reference library</p>
            <h2 id="samples-heading" className="mt-2 text-lg font-semibold text-slate-900">Synthetic sample inputs</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">Fictional source files for testing a workstream without sensitive data.</p>
          </div>
          <span className="text-xs font-medium text-slate-400">{sampleFiles.length} files</span>
        </div>
        <div className="grid sm:grid-cols-2 xl:grid-cols-5">
          {sampleFiles.map(([file, label, format], index) => (
            <a key={file} href={`${API_URL}/api/v1/samples/${file}`} className={`focus-ring group flex min-h-20 items-center justify-between gap-3 p-4 transition hover:bg-[#eef4f1] ${index > 0 ? "border-t border-slate-200 sm:border-t-0" : ""} ${index % 2 === 1 ? "sm:border-l" : ""} ${index >= 2 ? "sm:border-t" : ""} xl:border-l xl:border-t-0 ${index >= 5 ? "xl:border-t" : ""}`}>
              <span><span className="block text-sm font-semibold text-slate-800">{label}</span><span className="mt-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400">{format}</span></span>
              <Download size={15} className="shrink-0 text-slate-400 group-hover:text-[#1f6b62]" />
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
