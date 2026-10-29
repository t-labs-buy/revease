"use client";

/** Admin → Feedback: every response from the popup shown while a video or document
 *  generates (see components/FeedbackGate.tsx), newest first, with the average
 *  rating. The API 403s non-admins; this page also redirects them home. */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { listFeedback, type FeedbackItem } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { fmtDateIST } from "@/lib/time";
import { IconChevronDown, IconChevronRight } from "@/components/icons";

const stars = (n: number) => "★".repeat(n) + "☆".repeat(5 - n);

/** One response on a single line; the expand arrow appears only when an answer is
 *  actually cut off. That depends on the rendered width, so it is measured (and
 *  re-measured on resize) rather than guessed from the text length. */
function FeedbackRow({ f }: { f: FeedbackItem }) {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const challengesRef = useRef<HTMLTableCellElement>(null);
  const improvementsRef = useRef<HTMLTableCellElement>(null);

  useLayoutEffect(() => {
    if (open) return; // measured while collapsed; keep the arrow to close it again
    const measure = () =>
      setOverflows(
        [challengesRef.current, improvementsRef.current].some((el) => el && el.scrollWidth > el.clientWidth),
      );
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [open, f.challenges, f.improvements]);

  // collapsed: one line, cut with "…"; open: the full text with its line breaks
  const answer = open ? "max-w-sm whitespace-pre-wrap" : "max-w-xs truncate";
  return (
    <tr className="border-b border-[var(--border)] align-top last:border-0">
      <td className="w-10 py-2.5 pl-3">
        {overflows && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? "Collapse review" : "Expand review"}
            title={open ? "Collapse" : "Show full review"}
            className="btn btn-ghost btn-sm h-7 w-7 p-0 text-[var(--text-3)] hover:text-[var(--text)]"
          >
            {open ? <IconChevronDown width={15} height={15} /> : <IconChevronRight width={15} height={15} />}
          </button>
        )}
      </td>
      <td className="whitespace-nowrap px-5 py-3 text-[var(--text)]">{f.email}</td>
      <td className="whitespace-nowrap px-5 py-3 text-amber-400" title={`${f.rating} / 5`}>
        {stars(f.rating)}
      </td>
      <td ref={challengesRef} className={`${answer} px-5 py-3 text-[var(--text-2)]`}>
        {f.challenges || "—"}
      </td>
      <td ref={improvementsRef} className={`${answer} px-5 py-3 text-[var(--text-2)]`}>
        {f.improvements || "—"}
      </td>
      <td className="whitespace-nowrap px-5 py-3 text-[var(--text-2)]">
        {f.kind === "video" ? "Video" : "Document"}
        {f.project_name && <span className="text-[var(--text-3)]"> · {f.project_name}</span>}
      </td>
      <td className="whitespace-nowrap px-5 py-3 text-[var(--text-2)]">{fmtDateIST(f.created_at)}</td>
    </tr>
  );
}

export default function AdminFeedbackPage() {
  const { isAdmin, loading } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [average, setAverage] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAdmin) router.replace("/");
  }, [loading, isAdmin, router]);

  useEffect(() => {
    if (!isAdmin) return;
    listFeedback()
      .then((r) => {
        setItems(r.items);
        setAverage(r.average);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [isAdmin]);

  if (loading || !isAdmin) return null;

  return (
    <main className="mx-auto max-w-[1600px] px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Feedback</h1>
      <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
        Asked once per video and once per document, while it is being generated.
      </p>

      <div className="mt-6 flex gap-4">
        <div className="card px-5 py-4">
          <div className="text-[13px] text-[var(--text-3)]">Responses</div>
          <div className="mt-1 text-2xl font-semibold text-[var(--text)]">{items.length}</div>
        </div>
        <div className="card px-5 py-4">
          <div className="text-[13px] text-[var(--text-3)]">Average rating</div>
          <div className="mt-1 text-2xl font-semibold text-[var(--text)]">
            {average == null ? "—" : `${average.toFixed(1)} / 5`}
          </div>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      <div className="card mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-[var(--text-3)]">
              <th className="w-10" />
              <th className="px-5 py-3 font-medium">User</th>
              <th className="px-5 py-3 font-medium">Rating</th>
              <th className="px-5 py-3 font-medium">Challenges</th>
              <th className="px-5 py-3 font-medium">Improvements</th>
              <th className="px-5 py-3 font-medium">For</th>
              <th className="px-5 py-3 font-medium">Date</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-8 text-center text-[var(--text-3)]">
                  No feedback yet.
                </td>
              </tr>
            )}
            {items.map((f) => (
              <FeedbackRow key={f.id} f={f} />
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
