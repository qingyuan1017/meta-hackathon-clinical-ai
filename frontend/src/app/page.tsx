import Link from "next/link";
import { ArrowRight, DatabaseZap, Download, ShieldCheck, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfigStatus } from "@/components/config-status";
import { RecentJobs } from "@/components/recent-jobs";
import { workflows } from "@/lib/workflows";
import { API_URL } from "@/lib/api";

export default function HomePage() {
  return (
    <>
      <section className="grid-paper border-b border-slate-200">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-16 lg:grid-cols-[1fr_360px] lg:px-8 lg:py-20">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-clinical-100 bg-clinical-50 px-3 py-1.5 text-xs font-extrabold text-clinical-700">
              <Sparkles size={14} /> META-POWERED CLINICAL OPERATIONS
            </div>
            <h1 className="max-w-4xl text-4xl font-black leading-[1.04] tracking-[-0.04em] text-ink sm:text-6xl">
              From protocol intent to <span className="text-clinical-600">reviewable artifacts.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
              Five focused workbenches help clinical teams explore how structured AI drafting can accelerate study setup, standardization, and analysis planning.
            </p>
            <div className="mt-8 flex flex-wrap gap-3 text-xs font-bold text-slate-600">
              <span className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 shadow-sm"><ShieldCheck size={15} className="text-clinical-600" /> De-identified inputs only</span>
              <span className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 shadow-sm"><DatabaseZap size={15} className="text-clinical-600" /> Local artifact history</span>
            </div>
          </div>
          <div className="self-end"><ConfigStatus /></div>
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-5 py-14 lg:px-8">
        <section aria-labelledby="workflows-heading">
          <p className="text-xs font-extrabold tracking-[0.16em] text-clinical-700">CHOOSE A WORKBENCH</p>
          <h2 id="workflows-heading" className="mt-1 text-2xl font-extrabold tracking-tight text-ink">Independent workflows, consistent controls</h2>
          <div className="mt-6 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {workflows.map((workflow, index) => {
              const Icon = workflow.icon;
              return (
                <Card key={workflow.id} className={`group relative overflow-hidden transition duration-300 hover:-translate-y-1 hover:border-clinical-500 ${index === 0 ? "xl:col-span-2" : ""}`}>
                  <div className="absolute right-0 top-0 h-24 w-24 translate-x-8 -translate-y-8 rounded-full bg-clinical-50 transition group-hover:scale-150" />
                  <CardHeader className="relative flex-row items-start justify-between">
                    <div>
                      <p className="text-[11px] font-black tracking-[0.18em] text-clinical-700">{workflow.eyebrow}</p>
                      <h3 className="mt-3 text-xl font-extrabold tracking-tight text-ink">{workflow.title}</h3>
                    </div>
                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-ink text-white"><Icon size={20} /></span>
                  </CardHeader>
                  <CardContent className="relative">
                    <p className="min-h-14 text-sm leading-6 text-slate-600">{workflow.description}</p>
                    <Link className="focus-ring mt-6 inline-flex items-center gap-2 rounded-lg text-sm font-extrabold text-clinical-700" href={`/workflows/${workflow.id}`}>
                      Open workbench <ArrowRight size={16} className="transition group-hover:translate-x-1" />
                    </Link>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>

        <section className="mt-16 rounded-2xl border border-slate-200 bg-ink px-6 py-7 text-white shadow-soft sm:px-8" aria-labelledby="samples-heading">
          <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
            <div>
              <p className="text-xs font-extrabold tracking-[0.16em] text-emerald-300">SAFE STARTING POINTS</p>
              <h2 id="samples-heading" className="mt-1 text-2xl font-extrabold">Synthetic sample inputs</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">Download these intentionally fictional files to exercise every workflow without bringing sensitive data into the demo.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {[["synthetic-protocol.md", "Protocol"], ["blank-crf.pdf", "Blank CRF"], ["edc-specification.json", "EDC spec"], ["synthetic-sap.md", "SAP"], ["adam-metadata.json", "ADaM"]].map(([file, label]) => (
                <a key={file} href={`${API_URL}/api/v1/samples/${file}`} className="focus-ring inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-bold text-white transition hover:bg-white/20"><Download size={14} />{label}</a>
              ))}
            </div>
          </div>
        </section>

        <div className="mt-16"><RecentJobs /></div>
      </div>
    </>
  );
}
