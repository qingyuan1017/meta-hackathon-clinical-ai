"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertCircle, FileUp, LoaderCircle, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Job, Workflow } from "@/lib/types";
import { documentTypes, workflowById } from "@/lib/workflows";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader } from "./ui/card";

const formSchema = z.object({
  studyBrief: z.string().max(50_000),
  documentType: z.string().min(1),
  generateR: z.boolean(),
  generateSas: z.boolean(),
  acknowledged: z.boolean().refine((value) => value, { message: "Synthetic/de-identified data acknowledgement is required." }),
}).refine((value) => value.generateR || value.generateSas, { message: "Select at least one language.", path: ["generateR"] });

type FormValues = z.infer<typeof formSchema>;

export function WorkflowForm({ workflow, enabled, onCreated, discipline = "biostats" }: { workflow: Workflow; enabled: boolean; onCreated: (job: Job) => void; discipline?: string }) {
  const definition = workflowById[workflow];
  const [files, setFiles] = useState<File[]>([]);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { studyBrief: "", documentType: discipline === "data-management" ? "data-management-plan" : "protocol-synopsis", generateR: true, generateSas: true, acknowledged: false },
  });
  const values = form.watch();
  const mutation = useMutation({
    mutationFn: (submitted: FormValues) => api.createJob(workflow, {
      deidentified_acknowledged: submitted.acknowledged,
      study_brief: submitted.studyBrief,
      document_type: submitted.documentType,
      languages: [submitted.generateR && "r", submitted.generateSas && "sas"].filter(Boolean),
    }, files),
    onSuccess: onCreated,
  });

  const needsLanguages = workflow === "sdtm" || workflow === "tlf";
  const submit = form.handleSubmit((submitted) => mutation.mutate(submitted));
  const canSubmit = enabled && values.acknowledged && !mutation.isPending && (workflow === "clinical-document" ? Boolean(values.studyBrief.trim() || files.length) : Boolean(files.length));
  return (
    <Card>
      <CardHeader className="border-b border-slate-100 pb-5">
        <p className="text-xs font-black tracking-[0.16em] text-clinical-700">NEW GENERATION</p>
        <h2 className="mt-2 text-xl font-extrabold text-ink">Configure {definition.shortTitle.toLowerCase()}</h2>
      </CardHeader>
      <CardContent className="pt-6">
        <form className="space-y-6" onSubmit={submit}>
          {workflow === "clinical-document" && (
            <label className="block"><span className="mb-2 block text-sm font-extrabold text-ink">Document template</span><select {...form.register("documentType")} className="focus-ring h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-ink">{documentTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          )}
          {workflow === "clinical-document" && (
            <label className="block"><span className="mb-2 block text-sm font-extrabold text-ink">Study brief</span><textarea {...form.register("studyBrief")} rows={8} placeholder="Describe the synthetic study design, population, intervention, objectives, endpoints, and assumptions…" className="focus-ring w-full resize-y rounded-lg border border-slate-300 px-3 py-3 text-sm leading-6 text-ink placeholder:text-slate-400" /></label>
          )}
          <label className="block rounded-xl border-2 border-dashed border-slate-300 bg-slate-50/70 p-5 transition hover:border-clinical-500">
            <span className="flex items-center gap-2 text-sm font-extrabold text-ink"><FileUp size={18} className="text-clinical-700" /> Source files</span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">{definition.filePrompt} Maximum 25 MB each.</span>
            <input className="mt-4 block w-full text-xs text-slate-600" type="file" accept={definition.accepts} multiple={workflow !== "protocol-extraction"} onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
            {files.length > 0 && <span className="mt-3 block text-xs font-bold text-clinical-700">{files.length} file{files.length === 1 ? "" : "s"} selected</span>}
          </label>
          {needsLanguages && (
            <fieldset><legend className="mb-2 text-sm font-extrabold text-ink">Program languages</legend><div className="flex gap-4"><label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-bold uppercase"><input type="checkbox" {...form.register("generateR")} />R</label><label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-bold uppercase"><input type="checkbox" {...form.register("generateSas")} />SAS</label></div>{form.formState.errors.generateR && <p className="mt-2 text-xs font-semibold text-rose-700">{form.formState.errors.generateR.message}</p>}</fieldset>
          )}
          <label className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-amber-700" {...form.register("acknowledged")} />
            <span><span className="flex items-center gap-1.5 font-extrabold"><ShieldCheck size={16} /> Synthetic/de-identified data only</span>I confirm these files contain no PHI or directly identifying patient data and may be sent to the configured Meta endpoint. When public-data MCPs are enabled, the model may also send derived search terms to ClinicalTrials.gov, openFDA, NCBO BioPortal, or PubMed.</span>
          </label>
          {form.formState.errors.acknowledged && <p className="text-sm font-semibold text-rose-700">{form.formState.errors.acknowledged.message}</p>}
          {mutation.error && <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><AlertCircle size={17} className="mt-0.5 shrink-0" />{mutation.error.message}</div>}
          <Button type="submit" variant="clinical" size="lg" className="w-full" disabled={!canSubmit}>{mutation.isPending ? <><LoaderCircle className="animate-spin" size={18} /> Validating and queuing…</> : <>Generate draft artifacts</>}</Button>
        </form>
      </CardContent>
    </Card>
  );
}
