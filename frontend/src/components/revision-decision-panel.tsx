import { AlertTriangle, Info } from "lucide-react";
import { getFeedbackDecisionSequence, type RevisionFeedbackEvent } from "@/lib/revision-decision";

export function RevisionDecisionPanel({ result, warnings = [], events = [], compact = false, title = "Feedback decisions", ariaLabel = "Feedback decisions", onlyMatchedFeedback = false }: { result: unknown; warnings?: string[]; events?: RevisionFeedbackEvent[]; compact?: boolean; title?: string; ariaLabel?: string; onlyMatchedFeedback?: boolean }) {
  const sequence = getFeedbackDecisionSequence(result, warnings, events);
  const entries = onlyMatchedFeedback ? sequence.entries.filter((entry) => entry.decisions.length > 0) : sequence.entries;
  if (!entries.length && !sequence.unmatched.length && !sequence.assumptions.length) return null;

  return (
    <section aria-label={ariaLabel} className={`rounded-xl border border-amber-500/25 bg-amber-500/[0.07] ${compact ? "p-3" : "p-4"}`}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-amber-500/15 text-amber-300"><AlertTriangle size={17} /></span>
        <div className="min-w-0">
          <p className="text-xs font-black uppercase tracking-[0.12em] text-amber-300">{title}</p>
          <p className="mt-1 text-xs leading-5 text-amber-100/80">Feedback and its recorded outcome are shown together in submission order. This is an audit summary, not private model reasoning.</p>
        </div>
      </div>

      {entries.length > 0 && (
        <ol className="mt-4 space-y-3">
          {entries.map((entry, index) => (
            <li key={`${entry.eventIndex}-${entry.feedback}`} className="rounded-lg border border-white/10 bg-black/10 p-3">
              <div className="flex gap-2 text-xs leading-5"><span className="font-black text-sky-300">{index + 1}.</span><div><p className="font-bold text-sky-200">Your feedback</p><p className="text-zinc-300">{entry.feedback}</p></div></div>
              <div className="mt-2 border-l-2 border-amber-400/50 pl-3">
                <p className="text-[10px] font-black uppercase tracking-[0.1em] text-amber-300">Recorded decision</p>
                {entry.decisions.length ? <ul className="mt-1 space-y-1">{entry.decisions.map((item) => <li key={item} className="text-xs leading-5 text-amber-100">{item}</li>)}</ul> : <p className="mt-1 text-xs leading-5 text-zinc-400">No unresolved constraint was recorded for this feedback in the current draft.</p>}
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

      {!compact && sequence.assumptions.length > 0 && (
        <details className="mt-3 rounded-lg border border-white/10 bg-black/10">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-xs font-bold text-zinc-300 marker:content-none [&::-webkit-details-marker]:hidden"><Info size={14} className="text-violet-300" />Context retained ({sequence.assumptions.length})</summary>
          <ul className="space-y-2 border-t border-white/10 px-3 py-3">
            {sequence.assumptions.map((item) => <li key={item} className="text-xs leading-5 text-zinc-400">{item}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}
