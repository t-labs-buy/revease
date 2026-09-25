/**
 * Resumable multipart upload for large capture files (recordings, uploads).
 *
 * Why parts: a 2 GB recording sent as one PUT restarts from zero on any network
 * blip and, on the old path, tied up an API worker for the whole transfer. Parts
 * upload in parallel, each retries on its own, and on object storage they go
 * straight to the store via presigned URLs — the API only signs and completes.
 *
 * Resume: the upload id is remembered per (session, file) in localStorage. A
 * retry — or a reload and re-picking the same file — asks the server which parts
 * already arrived and sends only the rest.
 *
 * Presigned part URLs must be sent WITHOUT our Authorization header (it would
 * break the S3 signature); API part URLs (local backend) need it.
 */

import { API_BASE, apiFetch, getToken } from "@/lib/http";

export interface UploadProgress {
  loaded: number;
  total: number;
}

interface UploadInfo {
  upload_id: string;
  storage_key: string;
  size: number;
  part_size: number;
  part_count: number;
  status: string;
  parts: { number: number; etag: string; size: number }[];
}

const RESUME_KEY = "revease.uploads";
const CONCURRENCY = 4;
const MAX_ATTEMPTS = 6;
const SIGN_BATCH = 50;

function resumeMap(): Record<string, string> {
  try {
    return JSON.parse(window.localStorage.getItem(RESUME_KEY) || "{}");
  } catch {
    return {};
  }
}
function remember(key: string, uploadId: string | null) {
  try {
    const m = resumeMap();
    if (uploadId) m[key] = uploadId;
    else delete m[key];
    window.localStorage.setItem(RESUME_KEY, JSON.stringify(m));
  } catch {
    /* storage unavailable: resume just won't survive a reload */
  }
}

async function json<T>(r: Response, what: string): Promise<T> {
  if (!r.ok) {
    let detail = `${what} failed: ${r.status}`;
    try {
      const j = await r.json();
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

/** PUT one part with upload progress (fetch has no upload progress events). */
function putPart(url: string, body: Blob, onLoaded: (n: number) => void, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const viaApi = url.startsWith("/uploads/");
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", viaApi ? `${API_BASE}${url}` : url);
    if (viaApi) {
      const t = getToken();
      if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    }
    xhr.upload.onprogress = (e) => onLoaded(e.loaded);
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) return reject(new Error(`part upload failed: ${xhr.status}`));
      let etag = xhr.getResponseHeader("ETag") || "";
      if (viaApi) {
        try {
          etag = JSON.parse(xhr.responseText).etag;
        } catch {
          /* fall through */
        }
      }
      // Not fatal when a CORS policy hides ETag: the server re-reads part ETags
      // from the store on complete.
      resolve(etag.replace(/"/g, "") || "unknown");
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function uploadLarge(
  sessionId: string,
  kind: "raw_video" | "audio",
  ext: string,
  blob: Blob,
  opts: { onProgress?: (p: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<string> {
  const fileTag = blob instanceof File ? `${blob.name}:${blob.lastModified}` : "blob";
  const resumeKey = `${sessionId}:${kind}:${blob.size}:${fileTag}`;
  let info: UploadInfo | null = null;

  const previous = resumeMap()[resumeKey];
  if (previous) {
    const r = await apiFetch(`/uploads/${previous}`, { cache: "no-store" });
    if (r.ok) {
      const j = (await r.json()) as UploadInfo;
      if (j.status === "uploading") info = j;
    }
  }
  if (!info) {
    info = await json<UploadInfo>(
      await apiFetch(`/sessions/${sessionId}/uploads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, ext, size: blob.size }),
      }),
      "createUpload",
    );
    remember(resumeKey, info.upload_id);
  }
  const up = info;

  const etags = new Map<number, string>(up.parts.map((p) => [p.number, p.etag]));
  const doneBytes = new Map<number, number>(up.parts.map((p) => [p.number, p.size]));
  const inflight = new Map<number, number>();
  const report = () => {
    let loaded = 0;
    doneBytes.forEach((v) => (loaded += v));
    inflight.forEach((v) => (loaded += v));
    opts.onProgress?.({ loaded: Math.min(loaded, blob.size), total: blob.size });
  };
  report();

  const pending = Array.from({ length: up.part_count }, (_, i) => i + 1).filter((n) => !etags.has(n));
  const urls = new Map<number, string>();
  // One signing request in flight at a time: the parallel part workers all
  // start with no URLs and would otherwise each sign the same batch.
  let signing: Promise<void> | null = null;
  const signUpTo = async (n: number): Promise<void> => {
    while (signing) await signing;
    if (urls.has(n)) return;
    const batch = pending.filter((x) => x >= n && !urls.has(x)).slice(0, SIGN_BATCH);
    if (!batch.includes(n)) batch.unshift(n);
    signing = (async () => {
      const r = await json<{ parts: { number: number; url: string }[] }>(
        await apiFetch(`/uploads/${up.upload_id}/parts/sign`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ numbers: batch.slice(0, SIGN_BATCH) }),
        }),
        "signParts",
      );
      r.parts.forEach((p) => urls.set(p.number, p.url));
    })();
    try {
      await signing;
    } finally {
      signing = null;
    }
  };

  let next = 0;
  const worker = async () => {
    while (next < pending.length) {
      const n = pending[next++];
      const start = (n - 1) * up.part_size;
      const body = blob.slice(start, Math.min(start + up.part_size, blob.size));
      for (let attempt = 1; ; attempt++) {
        if (opts.signal?.aborted) throw new DOMException("aborted", "AbortError");
        try {
          if (!urls.has(n)) await signUpTo(n);
          const etag = await putPart(urls.get(n)!, body, (l) => {
            inflight.set(n, l);
            report();
          }, opts.signal);
          inflight.delete(n);
          etags.set(n, etag);
          doneBytes.set(n, body.size);
          report();
          break;
        } catch (e) {
          inflight.delete(n);
          if ((e as Error).name === "AbortError" || attempt >= MAX_ATTEMPTS) throw e;
          urls.delete(n); // presigned URLs can expire; re-sign on retry
          await sleep(Math.min(16000, 1000 * 2 ** (attempt - 1)));
        }
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, pending.length || 1) }, worker));

  const done = await json<{ storage_key: string }>(
    await apiFetch(`/uploads/${up.upload_id}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parts: Array.from({ length: up.part_count }, (_, i) => ({ number: i + 1, etag: etags.get(i + 1) || "unknown" })),
      }),
    }),
    "completeUpload",
  );
  remember(resumeKey, null);
  return done.storage_key;
}

export function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
