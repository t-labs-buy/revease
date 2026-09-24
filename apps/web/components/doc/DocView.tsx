"use client";

/** Read-only rendering of a DocV2 — used by the public share page and as the
 *  fallback view of the document page. Body text carries only `**bold**` and
 *  `` `code` `` inline markup; `Inline` maps exactly those two. */

import type { ReactNode } from "react";
import { mediaUrl, type DocV2 } from "@/lib/api";
import { IconLightbulb } from "@/components/icons";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/g;

export function Inline({ text }: { text: string }) {
  const parts = (text || "").split(INLINE).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`"))
          return (
            <code key={i} className="rounded bg-[var(--hover)] px-1 py-0.5 text-[0.92em] text-[var(--text)]">
              {p.slice(1, -1)}
            </code>
          );
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

export const mmss = (s: number | null | undefined) => {
  const v = Math.max(0, Number(s) || 0);
  const m = Math.floor(v / 60);
  const sec = v - m * 60;
  return `${String(m).padStart(2, "0")}:${sec.toFixed(1).padStart(4, "0")}`;
};

export function TipCallout({ children }: { children: ReactNode }) {
  return (
    <div className="mt-3 flex items-start gap-2.5 rounded-lg border border-[#D99A2B]/30 bg-[#D99A2B]/10 px-3 py-2.5 text-[13.5px] leading-relaxed text-[var(--text)]">
      <IconLightbulb width={16} height={16} className="mt-0.5 flex-none text-[#B07A15]" />
      <div>{children}</div>
    </div>
  );
}

export function DocView({ doc }: { doc: DocV2 }) {
  return (
    <article>
      <h1 className="text-[28px] font-bold leading-tight tracking-tight text-[var(--text)]">{doc.title}</h1>
      {doc.overview && (
        <p className="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed text-[var(--text-2)]">
          <Inline text={doc.overview} />
        </p>
      )}

      {doc.prerequisites.length > 0 && (
        <section className="mt-6">
          <h2 className="eyebrow">Prerequisites</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] text-[var(--text)]">
            {doc.prerequisites.map((p, i) => (
              <li key={i}>
                <Inline text={p} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <ol className="mt-8 space-y-8">
        {doc.steps.map((s, i) => (
          <li key={s.id} className="border-l-2 border-[var(--border)] pl-5">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full bg-[var(--brand)] text-xs font-semibold text-white">
                {i + 1}
              </span>
              <h2 className="text-[17px] font-semibold leading-snug text-[var(--text)]">{s.title}</h2>
            </div>
            {s.body && (
              <p className="mt-2 whitespace-pre-wrap text-[14.5px] leading-relaxed text-[var(--text)]">
                <Inline text={s.body} />
              </p>
            )}
            {s.tip && (
              <TipCallout>
                <strong>Tip:</strong> <Inline text={s.tip} />
              </TipCallout>
            )}
            {s.snapshot?.key && (
              <figure className="mt-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaUrl(s.snapshot.key)}
                  alt={`Step ${i + 1}: ${s.title}`}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--navy)]"
                />
              </figure>
            )}
          </li>
        ))}
      </ol>

      {doc.tips.length > 0 && (
        <section className="mt-10">
          <h2 className="eyebrow">Tips &amp; troubleshooting</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] text-[var(--text)]">
            {doc.tips.map((t, i) => (
              <li key={i}>
                <Inline text={t} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
