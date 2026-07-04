"use client";

import { useEffect, useRef, useState } from "react";
import { listVoices, previewVoice, type Voice } from "@/lib/api";
import { Spinner } from "@/components/ui";

type VoiceValue = { voice_id: string; speed: number; use_original?: boolean };

export function VoicePanel({
  value,
  onChange,
}: {
  value: VoiceValue;
  onChange: (patch: Partial<VoiceValue>) => void;
}) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [query, setQuery] = useState("");
  const [previewing, setPreviewing] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    listVoices()
      .then((r) => setVoices(r.voices))
      .catch(() => {});
    return () => audioRef.current?.pause();
  }, []);

  async function play(voiceId: string) {
    setPreviewing(voiceId);
    try {
      // poll until the sample is synthesized (first time downloads the voice model)
      for (let i = 0; i < 20; i++) {
        const { url, ready } = await previewVoice(voiceId);
        if (ready) {
          audioRef.current?.pause();
          const a = new Audio(url);
          audioRef.current = a;
          a.onended = () => setPreviewing(null);
          await a.play();
          return;
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    } catch {
      /* ignore */
    } finally {
      setPreviewing((p) => (p === voiceId ? null : p));
    }
  }

  const filtered = voices.filter(
    (v) =>
      v.name.toLowerCase().includes(query.toLowerCase()) ||
      v.style.toLowerCase().includes(query.toLowerCase()) ||
      v.gender.toLowerCase().includes(query.toLowerCase()),
  );
  const selected = voices.find((v) => v.id === value.voice_id);

  return (
    <div className="space-y-4">
      {/* Use original voice */}
      <label className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text)]">Use original voice</span>
        <input
          type="checkbox"
          checked={!!value.use_original}
          onChange={(e) => onChange({ use_original: e.target.checked })}
          className="h-5 w-9 accent-[#6d5dfb]"
        />
      </label>

      {!value.use_original && (
        <>
          <p className="rounded-lg border border-[#6d5dfb]/25 bg-[#6d5dfb]/8 px-3 py-2 text-xs text-[var(--brand-2)]">
            The chosen AI voice <strong>replaces your original narration</strong> in the generated
            video, speaking the same transcribed words. Preview a voice with ▶, click a row to
            select, then hit <strong>Generate video</strong>.
          </p>
          <div>
            <div className="mb-1.5 text-sm font-medium text-[var(--text)]">Select voiceover</div>
            <div className="card flex items-center justify-between px-3 py-2.5">
              <div>
                <div className="text-sm font-medium text-[var(--text)]">
                  {selected?.name ?? "Default"}
                </div>
                <div className="text-xs text-[var(--text-3)]">
                  {selected
                    ? `${selected.gender}, ${selected.accent ?? "English"}, ${selected.style}`
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search voice…"
            className="input"
          />

          <ul className="max-h-[46vh] space-y-1 overflow-y-auto">
            {filtered.map((v) => {
              const active = v.id === value.voice_id;
              return (
                <li key={v.id}>
                  <div
                    onClick={() => onChange({ voice_id: v.id })}
                    className={`flex cursor-pointer items-center gap-3 rounded-lg border p-2.5 transition-colors ${
                      active
                        ? "border-[#6d5dfb]/40 bg-[#6d5dfb]/5"
                        : "border-transparent hover:bg-[var(--hover)]"
                    }`}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void play(v.id);
                      }}
                      className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-[#6d5dfb] text-white hover:bg-[#5b4ce6]"
                      title="Preview"
                    >
                      {previewing === v.id ? <Spinner /> : "►"}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-[var(--text)]">{v.name}</div>
                      <div className="text-xs text-[var(--text-3)]">
                        {v.gender}, {v.accent ?? "English"}
                      </div>
                    </div>
                    {active ? (
                      <span className="rounded-full bg-[#6d5dfb] px-2 py-0.5 text-[11px] font-medium text-[var(--text)]">
                        ✓ Selected
                      </span>
                    ) : (
                      <span className="rounded-full bg-[var(--hover)] px-2 py-0.5 text-[11px] text-[#6d5dfb]">
                        {v.style}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="card p-3">
            <div className="text-xs text-[var(--text-3)]">Speed</div>
            <div className="mt-1.5 flex items-center gap-3">
              <input
                type="range"
                min={0.75}
                max={1.5}
                step={0.05}
                value={value.speed}
                onChange={(e) => onChange({ speed: Number(e.target.value) })}
                className="flex-1 accent-[#6d5dfb]"
              />
              <span className="w-10 text-right text-sm text-[var(--text-2)]">{value.speed.toFixed(2)}×</span>
            </div>
          </div>
        </>
      )}

      {value.use_original && (
        <p className="text-xs text-[var(--text-3)]">
          The generated video will keep the original recorded narration instead of an AI voice.
        </p>
      )}
    </div>
  );
}
