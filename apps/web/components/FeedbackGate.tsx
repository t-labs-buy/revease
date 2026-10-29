"use client";

/** The feedback popup. Mounted once in the root layout; asks the API whether a
 *  video or document the user can see is generating (see app/routers/feedback.py).
 *
 *  - First generation of a video/document (`due`): the popup cannot be closed until
 *    answered — no backdrop click, no Escape, no close button. The server decides,
 *    so a reload can't skip it.
 *  - Regenerations (`optional`): the same popup with a Skip button. Skipping (or
 *    answering) is remembered here only while that generation runs, so the next
 *    regeneration asks again.
 *
 *  Either way it stays up even if the generation finishes first. Only the star
 *  rating is required. Checked only when this tab starts work (ACTIVITY_EVENT) —
 *  no polling, so a reload, another tab or a collaborator's generation is not
 *  asked about. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVITY_EVENT, getFeedbackStatus, submitFeedback, type FeedbackDue } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const LABELS = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];

type Ask = { item: FeedbackDue; skippable: boolean };
const keyOf = (d: FeedbackDue) => `${d.kind}:${d.target_id}`;

export function FeedbackGate() {
  const { user } = useAuth();
  const [due, setDue] = useState<Ask | null>(null);
  // the generation already asked about (skipped or answered) while it still runs
  const settled = useRef<string | null>(null);

  const check = useCallback(() => {
    getFeedbackStatus()
      .then(({ due: required, optional }) => {
        // that generation ended: its regeneration may ask again
        if (settled.current && (!optional || keyOf(optional) !== settled.current)) settled.current = null;
        const next: Ask | null = required
          ? { item: required, skippable: false }
          : optional && keyOf(optional) !== settled.current
            ? { item: optional, skippable: true }
            : null;
        // Once shown, the popup stays until answered/skipped: a quick re-render
        // (every scene reused) can finish within one poll, and the next check would
        // otherwise read "nothing running" and close it under the user.
        setDue((cur) => cur ?? next);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!user) return setDue(null);
    // Only on a click that starts work. The event fires once the start request has
    // returned, so the job row already exists — and checking at once matters: a
    // regeneration that reuses every scene can finish in about a second.
    window.addEventListener(ACTIVITY_EVENT, check);
    return () => window.removeEventListener(ACTIVITY_EVENT, check);
  }, [user, check]);

  if (!user || !due) return null;
  const close = () => {
    // after the first answer the server reports this same run as `optional` —
    // don't ask twice for one generation
    settled.current = keyOf(due.item);
    setDue(null);
    check();
  };
  return (
    <FeedbackDialog
      key={keyOf(due.item)}
      due={due.item}
      onDone={close}
      onSkip={due.skippable ? close : undefined}
    />
  );
}

function FeedbackDialog({
  due,
  onDone,
  onSkip,
}: {
  due: FeedbackDue;
  onDone: () => void;
  onSkip?: () => void;
}) {
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [challenges, setChallenges] = useState("");
  const [improvements, setImprovements] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const what = due.kind === "video" ? "video" : "document";

  async function send() {
    if (!rating) return;
    setBusy(true);
    setError(null);
    try {
      await submitFeedback({ kind: due.kind, target_id: due.target_id, rating, challenges, improvements });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const shown = hover || rating;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-title"
        className="w-full max-w-lg rounded-2xl bg-[var(--card)] p-6 shadow-2xl ring-1 ring-[var(--border)]"
      >
        <h3 id="feedback-title" className="text-[17px] font-semibold text-[var(--text)]">
          While your {what} is being generated…
        </h3>
        <p className="mt-1 text-sm text-[var(--text-2)]">
          How was your experience with RevEase{due.project_name ? ` on “${due.project_name}”` : ""}?
          <span className="ml-0.5 text-red-500" aria-label="required">*</span>
        </p>

        <div className="mt-4 flex items-center gap-1" onMouseLeave={() => setHover(0)}>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              aria-label={`${n} star${n > 1 ? "s" : ""}`}
              aria-pressed={rating === n}
              onMouseEnter={() => setHover(n)}
              onClick={() => setRating(n)}
              className={`text-3xl leading-none transition-colors ${
                n <= shown ? "text-amber-400" : "text-[var(--border-strong)]"
              }`}
            >
              ★
            </button>
          ))}
          {shown > 0 && <span className="ml-2 text-sm text-[var(--text-2)]">{LABELS[shown]}</span>}
        </div>

        <label className="mt-5 block text-sm font-medium text-[var(--text)]">
          What challenges or difficulties did you face while using the tool?
          <textarea
            value={challenges}
            onChange={(e) => setChallenges(e.target.value)}
            rows={3}
            maxLength={4000}
            className="input mt-1.5 w-full resize-none"
          />
        </label>

        <label className="mt-4 block text-sm font-medium text-[var(--text)]">
          What improvements or new features would you recommend?
          <textarea
            value={improvements}
            onChange={(e) => setImprovements(e.target.value)}
            rows={3}
            maxLength={4000}
            className="input mt-1.5 w-full resize-none"
          />
        </label>

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex items-center justify-end gap-3">
          {!rating && <span className="text-xs text-[var(--text-3)]">Pick a star rating to continue</span>}
          {onSkip && (
            <button onClick={onSkip} disabled={busy} className="btn btn-secondary btn-sm font-semibold">
              Skip
            </button>
          )}
          <button onClick={send} disabled={!rating || busy} className="btn btn-primary btn-sm disabled:opacity-50">
            {busy ? "Sending…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
