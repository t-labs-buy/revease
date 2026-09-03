"use client";

/** Admin → Usage: totals of videos generated and screens recorded for a date
 *  range (defaults to the current month). The API 403s non-admins; this page
 *  also redirects them home. */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getUsageSummary, listUsageEvents, type UsageEventRow, type UsageSummary } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { EmptyState } from "@/components/ui";

const iso = (d: Date) => d.toISOString().slice(0, 10);

const KINDS: Record<UsageEventRow["kind"], { label: string; badge: string }> = {
  video: {
    label: "Video generated",
    badge: "bg-[#6d5dfb]/10 text-[var(--brand-2)] ring-[#6d5dfb]/25",
  },
  recording: {
    label: "Screen recorded",
    badge: "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20",
  },
  upload: {
    label: "Video uploaded",
    badge: "bg-amber-500/10 text-amber-500 ring-amber-500/20",
  },
};

/** Initials for the little avatar — from the name, else the email local part. */
const initials = (name: string | null, email: string): string => {
  const source = (name || "").trim() || email.split("@")[0] || "?";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase();
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 754000 -> "12:34"; hour-long content gets "1:02:34". */
const fmtDuration = (ms: number | null | undefined) => {
  if (ms == null || ms <= 0) return "—";
  const s = Math.round(ms / 1000);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${mm}:${pad(ss)}`;
};

/** API timestamps are IST wall-clock time with no zone marker — render them
 *  verbatim rather than letting the browser reinterpret them as local time. */
const fmtWhen = (ist: string) => {
  const m = ist.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return ist;
  const [, y, mo, d, h, min] = m;
  return `${+d} ${MONTHS[+mo - 1]} ${y}, ${h}:${min}`;
};

const PAGE_SIZE = 10;

// The API's date filters mean IST calendar days, so the defaults must too.
const IST_OFFSET_MS = 5.5 * 3600 * 1000;
const istToday = () => iso(new Date(Date.now() + IST_OFFSET_MS));

function monthStart(): string {
  const now = new Date(Date.now() + IST_OFFSET_MS);
  return iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)));
}

export default function AdminUsagePage() {
  const { isAdmin, loading } = useAuth();
  const router = useRouter();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(istToday());
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [events, setEvents] = useState<UsageEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0); // zero-based
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAdmin) router.replace("/");
  }, [loading, isAdmin, router]);

  // a new date range starts back at the first page
  useEffect(() => setPage(0), [from, to]);

  useEffect(() => {
    if (!isAdmin) return;
    Promise.all([
      getUsageSummary(from || undefined, to || undefined),
      listUsageEvents(from || undefined, to || undefined, PAGE_SIZE, page * PAGE_SIZE),
    ])
      .then(([s, ev]) => {
        setSummary(s);
        setEvents(ev.events);
        setTotal(ev.total);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [isAdmin, from, to, page]);

  if (loading || !isAdmin) return null;

  const allTime = !from && !to;
  const tiles = [
    {
      label: "Videos generated",
      value: summary?.videos_generated,
      icon: "🎬",
      grad: "from-[#6d5dfb] to-[#a855f7]",
    },
    {
      label: "Screens recorded",
      value: summary?.screens_recorded,
      icon: "🖥",
      grad: "from-[#6366f1] to-[#06b6d4]",
    },
    {
      label: "Videos uploaded",
      value: summary?.videos_uploaded,
      icon: "⬆️",
      grad: "from-[#f97316] to-[#ec4899]",
    },
  ];

  return (
    <main className="mx-auto max-w-[1600px] px-8 py-10">
      {/* header: title left, period picker right */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Usage</h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
            {allTime ? "Totals across all users, all time." : "Totals across all users for the selected period."}
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-1.5">
          <input
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => setFrom(e.target.value)}
            aria-label="From date"
            className="rounded-xl border-0 bg-transparent px-2.5 py-1.5 text-sm text-[var(--text)] outline-none"
          />
          <span className="text-[var(--text-3)]">–</span>
          <input
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => setTo(e.target.value)}
            aria-label="To date"
            className="rounded-xl border-0 bg-transparent px-2.5 py-1.5 text-sm text-[var(--text)] outline-none"
          />
          <button
            onClick={() => {
              setFrom("");
              setTo("");
            }}
            title="Show totals across all time"
            className={`rounded-xl px-3 py-1.5 text-sm font-medium transition-colors ${
              allTime
                ? "bg-[#6d5dfb] text-white"
                : "text-[var(--text-2)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
            }`}
          >
            All time
          </button>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {/* totals */}
      <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:max-w-4xl lg:grid-cols-3">
        {tiles.map((t) => (
          <div key={t.label} className="card flex items-center gap-4 p-6">
            <span
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${t.grad} text-xl shadow-lg shadow-black/10`}
            >
              {t.icon}
            </span>
            <span>
              <span className="block text-3xl font-semibold leading-tight tracking-tight text-[var(--text)]">
                {t.value ?? "—"}
              </span>
              <span className="mt-0.5 block text-sm text-[var(--text-2)]">{t.label}</span>
            </span>
          </div>
        ))}
      </div>

      {/* per-event detail */}
      <h2 className="mt-10 text-xl font-semibold tracking-tight text-[var(--text)]">Activity</h2>
      {events.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            title="No activity in this period"
            hint="Recordings and generated videos will show up here as they happen."
          />
        </div>
      ) : (
        <div className="card mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-[var(--text-3)]">
                <th className="px-5 py-3.5 font-medium">When</th>
                <th className="px-5 py-3.5 font-medium">User</th>
                <th className="px-5 py-3.5 font-medium">Email</th>
                <th className="px-5 py-3.5 font-medium">Activity</th>
                <th className="px-5 py-3.5 text-right font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => (
                <tr
                  key={i}
                  className="border-b border-[var(--border)] transition-colors last:border-0 hover:bg-[var(--hover)]"
                >
                  <td className="whitespace-nowrap px-5 py-3.5 text-[var(--text-2)]">
                    {fmtWhen(e.created_at)}
                  </td>
                  <td className="px-5 py-3.5">
                    {e.user_email ? (
                      <span className="flex items-center gap-2.5">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-[10px] font-semibold text-white">
                          {initials(e.user_name, e.user_email)}
                        </span>
                        <span className="text-[var(--text)]">
                          {e.user_name || e.user_email.split("@")[0]}
                        </span>
                      </span>
                    ) : (
                      <span className="text-[var(--text-3)]">—</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-[var(--text-2)]">{e.user_email ?? "—"}</td>
                  <td className="whitespace-nowrap px-5 py-3.5">
                    <span
                      className={`badge px-2.5 py-0.5 ring-1 ring-inset ${KINDS[e.kind]?.badge ?? ""}`}
                    >
                      {KINDS[e.kind]?.label ?? e.kind}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-5 py-3.5 text-right tabular-nums text-[var(--text-2)]">
                    {fmtDuration(e.duration_ms)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* pagination */}
          <div className="flex items-center justify-between border-t border-[var(--border)] px-5 py-3 text-sm text-[var(--text-2)]">
            <span>
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
            </span>
            <span className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="btn btn-secondary btn-sm disabled:opacity-40"
              >
                ← Previous
              </button>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={(page + 1) * PAGE_SIZE >= total}
                className="btn btn-secondary btn-sm disabled:opacity-40"
              >
                Next →
              </button>
            </span>
          </div>
        </div>
      )}
    </main>
  );
}
