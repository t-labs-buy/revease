"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  deletePackage,
  getPackage,
  mediaUrl,
  previewVoice,
  updatePackage,
  uploadMedia,
  type BrandPackage,
} from "@/lib/api";
import { Spinner } from "@/components/ui";

const FONTS = ["Geist", "Inter", "Arial", "Georgia"];
const LOGO_POS = ["Top Left", "Top Center", "Top Right", "Bottom Left", "Bottom Right"];
const VOICES = [
  ["af_sarah", "Sarah (F)"],
  ["af_bella", "Bella (F)"],
  ["af_heart", "Heart (F)"],
  ["am_adam", "Adam (M)"],
  ["am_michael", "Michael (M)"],
  ["bf_emma", "Emma (F, UK)"],
  ["bm_george", "George (M, UK)"],
];
const TABS = ["Intro / Outro", "Logo", "Color theme", "AI Voice"] as const;
type Tab = (typeof TABS)[number];

type Form = {
  name: string;
  intro: string;
  intro_video_key: string;
  outro: string;
  outro_video_key: string;
  logo_key: string;
  logo_url: string;
  logo_position: string;
  primary_color: string;
  accent_color: string;
  bg_color: string;
  text_color: string;
  font: string;
  voice_id: string;
  voice_speed: number;
};

function fromPkg(p: BrandPackage): Form {
  const s = (p.settings || {}) as Record<string, unknown>;
  const str = (k: string, d = "") => (typeof s[k] === "string" ? (s[k] as string) : d);
  return {
    name: p.name,
    intro: str("intro"),
    intro_video_key: str("intro_video_key"),
    outro: str("outro", "Thanks for watching!"),
    outro_video_key: str("outro_video_key"),
    logo_key: str("logo_key"),
    logo_url: str("logo_url"),
    logo_position: str("logo_position", "Top Right"),
    primary_color: str("primary_color", "#6d5dfb"),
    accent_color: str("accent_color", "#a855f7"),
    bg_color: str("bg_color", "#0b0b12"),
    text_color: str("text_color", "#ffffff"),
    font: str("font", "Geist"),
    voice_id: str("voice_id", "af_sarah"),
    voice_speed: typeof s.voice_speed === "number" ? (s.voice_speed as number) : 1,
  };
}

export default function PackageEditor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [pkg, setPkg] = useState<BrandPackage | null>(null);
  const [f, setF] = useState<Form | null>(null);
  const [tab, setTab] = useState<Tab>("Intro / Outro");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // upload/preview in progress
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    getPackage(id)
      .then((p) => {
        setPkg(p);
        setF(fromPkg(p));
      })
      .catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <main className="p-10 text-sm text-red-400">{error}</main>;
  if (!f) return <main className="flex items-center gap-2 p-10 text-sm text-[var(--text-2)]"><Spinner /> Loading…</main>;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF({ ...f, [k]: v });

  async function upload(kind: "logo" | "intro_video" | "outro_video", file: File) {
    setBusy(kind);
    try {
      const ext = file.name.split(".").pop() || (kind === "logo" ? "png" : "mp4");
      const key = await uploadMedia(`packages/${id}/${kind}_${Date.now()}.${ext}`, file);
      set(kind === "logo" ? "logo_key" : kind === "intro_video" ? "intro_video_key" : "outro_video_key", key);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function playVoice() {
    setBusy("voice");
    try {
      for (let i = 0; i < 16; i++) {
        const { url, ready } = await previewVoice(f!.voice_id);
        if (ready) {
          audioRef.current?.pause();
          const a = new Audio(url);
          a.playbackRate = f!.voice_speed;
          audioRef.current = a;
          await a.play();
          break;
        }
        await new Promise((r) => setTimeout(r, 1200));
      }
    } catch {
      /* ignore */
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!f) return;
    setSaving(true);
    try {
      const settings = {
        intro: f.intro,
        intro_video_key: f.intro_video_key,
        outro: f.outro,
        outro_video_key: f.outro_video_key,
        logo_key: f.logo_key,
        logo_url: f.logo_url,
        logo_position: f.logo_position,
        primary_color: f.primary_color,
        accent_color: f.accent_color,
        bg_color: f.bg_color,
        text_color: f.text_color,
        font: f.font,
        voice_id: f.voice_id,
        voice_speed: f.voice_speed,
      };
      const p = await updatePackage(id, f.name, settings);
      setPkg(p);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const logoSrc = f.logo_key ? mediaUrl(f.logo_key) : f.logo_url;

  return (
    <main className="mx-auto max-w-4xl px-8 py-8">
      {/* header */}
      <div className="mb-1 text-sm text-[var(--text-3)]">
        <Link href="/library" className="hover:text-[var(--text)]">Library</Link> /{" "}
        <Link href="/library/packages" className="hover:text-[var(--text)]">Brand Packages</Link> / {f.name}
      </div>
      <div className="flex items-center gap-3">
        <input
          value={f.name}
          onChange={(e) => set("name", e.target.value)}
          className="input max-w-sm text-lg font-semibold"
        />
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => deletePackage(id).then(() => router.push("/library/packages"))}
            className="btn btn-sm border border-red-500/40 text-red-500 hover:bg-red-500/10"
          >
            🗑 Delete
          </button>
          <button onClick={save} disabled={saving} className="btn btn-primary">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* tabs */}
      <div className="mt-6 flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === t
                ? "border-b-2 border-[#6d5dfb] text-[var(--text)]"
                : "text-[var(--text-2)] hover:text-[var(--text)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* editor */}
        <div className="space-y-5">
          {tab === "Intro / Outro" &&
            (["intro", "outro"] as const).map((which) => {
              const videoKey = which === "intro" ? f.intro_video_key : f.outro_video_key;
              return (
                <div key={which} className="card p-4">
                  <div className="mb-2 text-sm font-semibold capitalize text-[var(--text)]">{which}</div>
                  <div className="label mb-1">Text</div>
                  <input
                    value={which === "intro" ? f.intro : f.outro}
                    onChange={(e) => set(which === "intro" ? "intro" : "outro", e.target.value)}
                    placeholder={which === "intro" ? "Welcome to Acme" : "Thanks for watching!"}
                    className="input"
                  />
                  <div className="mt-3 flex items-center gap-2">
                    <UploadBtn
                      label={videoKey ? "Replace clip" : "+ Add short video"}
                      accept="video/mp4,video/quicktime"
                      busy={busy === `${which}_video`}
                      onFile={(file) => upload(`${which}_video` as "intro_video" | "outro_video", file)}
                    />
                    {videoKey && (
                      <button
                        onClick={() => set(which === "intro" ? "intro_video_key" : "outro_video_key", "")}
                        className="btn btn-ghost btn-sm text-red-400"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  {videoKey && (
                    <video src={mediaUrl(videoKey)} controls className="mt-3 w-full rounded-lg bg-black" />
                  )}
                </div>
              );
            })}

          {tab === "Logo" && (
            <div className="card space-y-4 p-5">
              <div className="flex items-center gap-4">
                <div className="flex h-20 w-20 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--input-bg)]">
                  {logoSrc ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={logoSrc} alt="logo" className="max-h-full max-w-full object-contain p-1" />
                  ) : (
                    <span className="text-[var(--text-3)]">🖼</span>
                  )}
                </div>
                <div>
                  <UploadBtn
                    label={f.logo_key ? "Replace logo" : "Upload logo"}
                    accept="image/*"
                    busy={busy === "logo"}
                    onFile={(file) => upload("logo", file)}
                  />
                  <p className="mt-1 text-[11px] text-[var(--text-3)]">PNG/SVG, square (1:1) works best.</p>
                </div>
              </div>
              <div>
                <div className="label mb-1">Or logo URL</div>
                <input value={f.logo_url} onChange={(e) => set("logo_url", e.target.value)} placeholder="https://…/logo.png" className="input" />
              </div>
              <div>
                <div className="label mb-1">Position on video</div>
                <select value={f.logo_position} onChange={(e) => set("logo_position", e.target.value)} className="input">
                  {LOGO_POS.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {tab === "Color theme" && (
            <div className="card space-y-4 p-5">
              {(
                [
                  ["Primary", "primary_color"],
                  ["Accent", "accent_color"],
                  ["Background", "bg_color"],
                  ["Text", "text_color"],
                ] as const
              ).map(([label, key]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm text-[var(--text)]">{label}</span>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={f[key]}
                      onChange={(e) => set(key, e.target.value)}
                      className="h-9 w-12 rounded border border-[var(--border)] bg-transparent"
                    />
                    <span className="w-20 text-xs text-[var(--text-3)]">{f[key].toUpperCase()}</span>
                  </div>
                </div>
              ))}
              <div>
                <div className="label mb-1">Font</div>
                <select value={f.font} onChange={(e) => set("font", e.target.value)} className="input">
                  {FONTS.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {tab === "AI Voice" && (
            <div className="card space-y-4 p-5">
              <div>
                <div className="label mb-1">Brand voice</div>
                <select value={f.voice_id} onChange={(e) => set("voice_id", e.target.value)} className="input">
                  {VOICES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="label">Modulation — speed</span>
                  <span className="text-xs text-[var(--text-2)]">{f.voice_speed.toFixed(2)}×</span>
                </div>
                <input
                  type="range"
                  min={0.75}
                  max={1.5}
                  step={0.05}
                  value={f.voice_speed}
                  onChange={(e) => set("voice_speed", Number(e.target.value))}
                  className="w-full accent-[#6d5dfb]"
                />
              </div>
              <button onClick={playVoice} disabled={busy === "voice"} className="btn btn-secondary btn-sm">
                {busy === "voice" ? (
                  <>
                    <Spinner /> Loading…
                  </>
                ) : (
                  "▶ Preview voice"
                )}
              </button>
            </div>
          )}
        </div>

        {/* live brand preview */}
        <div>
          <div className="label mb-2">Preview</div>
          <div
            className="relative flex aspect-video flex-col items-center justify-center overflow-hidden rounded-2xl p-4"
            style={{ background: `linear-gradient(135deg, ${f.primary_color}, ${f.accent_color})` }}
          >
            {logoSrc && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={logoSrc}
                alt="logo"
                className="absolute h-8 object-contain"
                style={{
                  top: f.logo_position.includes("Bottom") ? "auto" : 12,
                  bottom: f.logo_position.includes("Bottom") ? 12 : "auto",
                  left: f.logo_position.includes("Left") ? 12 : f.logo_position.includes("Center") ? "50%" : "auto",
                  right: f.logo_position.includes("Right") ? 12 : "auto",
                  transform: f.logo_position.includes("Center") ? "translateX(-50%)" : "none",
                }}
              />
            )}
            <div className="text-center" style={{ fontFamily: f.font, color: f.text_color }}>
              <div className="text-lg font-semibold">{f.intro || f.name}</div>
              <div className="mt-1 text-xs opacity-80">{f.outro}</div>
            </div>
          </div>
          <p className="mt-2 text-[11px] text-[var(--text-3)]">
            Mention <b className="text-[var(--text-2)]">{f.name}</b> in a skill&apos;s Brand Package field to apply this.
          </p>
        </div>
      </div>
    </main>
  );
}

function UploadBtn({
  label,
  accept,
  busy,
  onFile,
}: {
  label: string;
  accept: string;
  busy?: boolean;
  onFile: (f: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <button onClick={() => ref.current?.click()} disabled={busy} className="btn btn-secondary btn-sm">
        {busy ? (
          <>
            <Spinner /> Uploading…
          </>
        ) : (
          label
        )}
      </button>
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </>
  );
}
