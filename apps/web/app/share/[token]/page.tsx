"use client";

import { use, useEffect, useState } from "react";
import { downloadUrl, getSharePublic, mediaUrl, type SharePublic } from "@/lib/api";

function safeFilename(title: string): string {
  const base = title.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-");
  return `${base || "video"}.mp4`;
}

export default function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [data, setData] = useState<SharePublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    getSharePublic(token)
      .then(setData)
      .catch(() => setError("This link isn’t available — it may have been revoked."));
  }, [token]);

  async function download() {
    if (!data?.video_url) return;
    setDownloading(true);
    try {
      // Cross-origin <a download> is ignored by browsers (it just plays the file),
      // so fetch the bytes and save them through a same-origin blob URL instead.
      await downloadUrl(data.video_url, safeFilename(data.title));
    } catch {
      setError("Download failed — please try again.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <main className="min-h-screen">
      {/* minimal public header */}
      <header className="border-b border-zinc-800/60 px-6 py-3">
        <div className="mx-auto flex max-w-4xl items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-600 text-sm font-bold text-[var(--text)]">
            R
          </span>
          <span className="font-semibold tracking-tight">RevEase</span>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-10">
        {error && <p className="text-sm text-red-300">{error}</p>}
        {!data && !error && <p className="text-sm text-zinc-500">Loading…</p>}

        {data && (
          <>
            <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>

            {data.kind === "video" && data.video_url && (
              <div className="mt-5">
                <div className="rounded-2xl bg-gradient-to-br from-violet-500/25 via-blue-500/20 to-emerald-500/20 p-4 sm:p-6">
                  <video
                    src={data.video_url}
                    controls
                    // Hide the browser's own download control when the owner turned downloads off.
                    controlsList={data.allow_download ? undefined : "nodownload"}
                    onContextMenu={data.allow_download ? undefined : (e) => e.preventDefault()}
                    className="w-full rounded-xl bg-black"
                  />
                </div>
                {data.allow_download && (
                  <button onClick={download} disabled={downloading} className="btn btn-primary mt-4">
                    {downloading ? "Downloading…" : "↓ Download video"}
                  </button>
                )}
              </div>
            )}

            {data.kind === "doc" && data.doc && (
              <article className="mt-6">
                <p className="text-zinc-500">{data.doc.summary}</p>
                <ol className="mt-6 space-y-6">
                  {data.doc.steps.map((s) => (
                    <li key={s.n} className="border-l-2 border-zinc-800 pl-5">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-600 text-xs font-semibold text-[var(--text)]">
                          {s.n}
                        </span>
                        <h2 className="text-lg font-medium text-zinc-100">{s.title}</h2>
                      </div>
                      {s.body && <p className="mt-2 text-zinc-300">{s.body}</p>}
                      {s.screenshot && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={mediaUrl(s.screenshot)}
                          alt={`Step ${s.n}`}
                          className="mt-3 w-full rounded-lg border border-zinc-800"
                        />
                      )}
                    </li>
                  ))}
                </ol>
              </article>
            )}

            <p className="mt-10 text-xs text-zinc-600">Made with RevEase.</p>
          </>
        )}
      </div>
    </main>
  );
}
