import { AlertTriangle, ChevronDown, Info } from "lucide-react";
import { getFeedbackDecisionSequence, type RevisionFeedbackEvent } from "@/lib/revision-decision";

export function RevisionDecisionPanel({ result, warnings = [], events = [], compact = false, title = "Feedback decisions", assumptionsTitle = "Assumptions", ariaLabel = "Feedback decisions", onlyMatchedFeedback = false, collapsedByDefault = false }: { result: unknown; warnings?: string[]; events?: RevisionFeedbackEvent[]; compact?: boolean; title?: string; assumptionsTitle?: string; ariaLabel?: string; onlyMatchedFeedback?: boolean; collapsedByDefault?: boolean }) {
  const sequence = getFeedbackDecisionSequence(result, warnings, events);
  const entries = onlyMatchedFeedback ? sequence.entries.filter((entry) => entry.decisions.length > 0) : sequence.entries;
  const hasDecisions = entries.length > 0 || sequence.unmatched.length > 0;
  if (!entries.length && !sequence.unmatched.length && !sequence.assumptions.length) return null;

  return (
    <div className="space-y-3">
      {hasDecisions && <section aria-label={ariaLabel}>
        <details open={collapsedByDefault ? undefined : true} aria-label={`${title} panel`} className={`group rounded-xl border border-amber-500/25 bg-amber-500/[0.07] ${compact ? "p-3" : "p-4"}`}>
        <summary className="flex cursor-pointer list-none items-start gap-3 marker:content-none [&::-webkit-details-marker]:hidden">
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-amber-500/15 text-amber-800"><AlertTriangle size={17} /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-xs font-black uppercase tracking-[0.12em] text-amber-800">{title}</span>
            <span className="mt-1 block text-xs leading-5 text-amber-100/80">Feedback and its recorded outcome are shown together in submission order. This is an audit summary, not private model reasoning.</span>
          </span>
          <ChevronDown aria-hidden size={17} className="mt-2 shrink-0 text-amber-800 transition-transform group-open:rotate-180" />
        </summary>

        {entries.length > 0 && (
          <ol className="mt-4 space-y-3">
            {entries.map((entry, index) => (
              <li key={`${entry.eventIndex}-${entry.feedback}`} className="rounded-lg border border-slate-200 bg-black/10 p-3">
                <div className="flex gap-2 text-xs leading-5"><span className="font-black text-sky-700">{index + 1}.</span><div><p className="font-bold text-sky-200">Your feedback</p><p className="text-slate-700">{entry.feedback}</p></div></div>
                <div className="mt-2 border-l-2 border-amber-400/50 pl-3">
                  <p className="text-[10px] font-black uppercase tracking-[0.1em] text-amber-800">Recorded decision</p>
                  {entry.decisions.length ? <ul className="mt-1 space-y-1">{entry.decisions.map((item) => <li key={item} className="text-xs leading-5 text-amber-100">{item}</li>)}</ul> : <p className="mt-1 text-xs leading-5 text-slate-600">No unresolved constraint was recorded for this feedback in the current draft.</p>}
                </div>
              </li>
            ))}
          </ol>
        )}

        {sequence.unmatched.length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] font-black uppercase tracking-[0.1em] text-amber-200">Other current constraints</p>
            <ul className="mt-2 space-y-2">{sequence.unmatched.map((item) => <li key={item} className="flex gap-2 text-xs leading-5 text-amber-100"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />{item}</li>)}</ul>
          </div>
        )}

        </details>
      </section>}

      {!compact && sequence.assumptions.length > 0 && (
        <section aria-label={assumptionsTitle}>
          <details aria-label={`${assumptionsTitle} panel`} className="group rounded-xl border border-emerald-500/25 bg-emerald-500/[0.07] p-4">
            <summary className="flex cursor-pointer list-none items-start gap-3 marker:content-none [&::-webkit-details-marker]:hidden">
              <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-emerald-500/15 text-emerald-700"><Info size={17} /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-black uppercase tracking-[0.12em] text-emerald-700">{assumptionsTitle}</span>
                <span className="mt-1 block text-xs leading-5 text-emerald-100/80">Assumptions retained in the current draft ({sequence.assumptions.length}).</span>
              </span>
              <ChevronDown aria-hidden size={17} className="mt-2 shrink-0 text-emerald-700 transition-transform group-open:rotate-180" />
            </summary>
            <ul className="mt-4 space-y-2 border-t border-emerald-500/20 pt-3">
              {sequence.assumptions.map((item) => <li key={item} className="flex gap-2 text-xs leading-5 text-emerald-100/80"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />{item}</li>)}
            </ul>
          </details>
        </section>
      )}
    </div>
  );
}
