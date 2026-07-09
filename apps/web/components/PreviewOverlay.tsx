"use client";

import { Rnd } from "react-rnd";
import type { EditSpec, EditElement } from "@/lib/api";

type Frame = { w: number; h: number };

/** Draggable/resizable overlay over the preview video: a crop region + text/box
 *  elements. Positions are stored normalized (0..1); react-rnd works in px, so we
 *  scale by the measured frame size and convert back on drag/resize. */
/** An element shows across the whole video unless it has a time window. */
export const elActive = (el: EditElement, curMs: number) => {
  const s = el.start_ms ?? 0;
  const e = el.end_ms ?? 0;
  return e <= s ? true : curMs >= s && curMs <= e;
};

export function PreviewOverlay({
  frame,
  tab,
  cropEditing = false,
  spec,
  setSpec,
  selId,
  setSelId,
  curMs,
}: {
  frame: Frame;
  tab: string;
  cropEditing?: boolean;
  spec: EditSpec;
  setSpec: (s: EditSpec) => void;
  selId: string | null;
  setSelId: (id: string | null) => void;
  curMs: number;
}) {
  const { w, h } = frame;
  if (!w || !h) return null;

  const crop = spec.crop ?? { enabled: false, x: 0, y: 0, w: 1, h: 1 };
  const allElements = spec.elements ?? [];
  const cropEdit = cropEditing && crop.enabled;
  const elEdit = tab === "Elements";
  // While editing show every element (so any can be positioned); otherwise show
  // only those active at the current time.
  const elements = elEdit ? allElements : allElements.filter((e) => elActive(e, curMs));

  const setCrop = (c: Partial<NonNullable<EditSpec["crop"]>>) =>
    setSpec({ ...spec, crop: { ...crop, ...c } });
  const setEl = (id: string, patch: Partial<EditElement>) =>
    setSpec({ ...spec, elements: elements.map((e) => (e.id === id ? { ...e, ...patch } : e)) });

  const L = crop.x * 100,
    T = crop.y * 100,
    R = (crop.x + crop.w) * 100,
    B = (crop.y + crop.h) * 100;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* crop: darken outside + a draggable box — only while EDITING the crop.
          Otherwise the preview video itself is reframed to the crop region. */}
      {cropEdit && (
        <>
          <div className="absolute bg-black/50" style={{ left: 0, top: 0, width: "100%", height: `${T}%` }} />
          <div className="absolute bg-black/50" style={{ left: 0, top: `${B}%`, width: "100%", bottom: 0 }} />
          <div className="absolute bg-black/50" style={{ left: 0, top: `${T}%`, width: `${L}%`, height: `${B - T}%` }} />
          <div className="absolute bg-black/50" style={{ left: `${R}%`, top: `${T}%`, right: 0, height: `${B - T}%` }} />
          <Rnd
            className={`${cropEdit ? "pointer-events-auto" : "pointer-events-none"} border-2 ${
              cropEdit ? "border-violet-400" : "border-white/50"
            }`}
            bounds="parent"
            disableDragging={!cropEdit}
            enableResizing={cropEdit}
            size={{ width: crop.w * w, height: crop.h * h }}
            position={{ x: crop.x * w, y: crop.y * h }}
            onDragStop={(_e, d) => setCrop({ x: clamp01(d.x / w), y: clamp01(d.y / h) })}
            onResizeStop={(_e, _dir, ref, _delta, pos) =>
              setCrop({
                w: clamp01(ref.offsetWidth / w),
                h: clamp01(ref.offsetHeight / h),
                x: clamp01(pos.x / w),
                y: clamp01(pos.y / h),
              })
            }
          />
        </>
      )}

      {/* elements */}
      {elements.map((el) => {
        const sel = selId === el.id;
        return (
          <Rnd
            key={el.id}
            className={`${elEdit ? "pointer-events-auto cursor-move" : "pointer-events-none"} ${
              sel && elEdit ? "outline outline-2 outline-violet-400" : ""
            }`}
            bounds="parent"
            disableDragging={!elEdit}
            enableResizing={elEdit}
            size={{ width: el.w * w, height: el.h * h }}
            position={{ x: el.x * w, y: el.y * h }}
            onMouseDown={() => elEdit && setSelId(el.id)}
            onDragStop={(_e, d) => setEl(el.id, { x: clamp01(d.x / w), y: clamp01(d.y / h) })}
            onResizeStop={(_e, _dir, ref, _delta, pos) =>
              setEl(el.id, {
                w: clamp01(ref.offsetWidth / w),
                h: clamp01(ref.offsetHeight / h),
                x: clamp01(pos.x / w),
                y: clamp01(pos.y / h),
              })
            }
          >
            {el.type === "box" ? (
              <div
                className="h-full w-full rounded-sm"
                style={{ background: `${el.color ?? "#facc15"}44`, border: `2px solid ${el.color ?? "#facc15"}` }}
              />
            ) : (
              <div
                className="flex h-full w-full items-center leading-tight"
                style={{ color: el.color ?? "#ffffff", fontSize: (el.size ?? 0.06) * h, textShadow: "0 1px 3px rgba(0,0,0,.85)" }}
              >
                <span className="truncate">{el.text || "Text"}</span>
              </div>
            )}
          </Rnd>
        );
      })}
    </div>
  );
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
