"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { IconPlus, IconX } from "@/components/icons";

/** Editor for a list of short strings (prerequisites, tips). Enter adds a row
 *  below, Backspace on an empty row removes it. */
export function ListEditor({
  items,
  onChange,
  placeholder,
  addLabel,
  icon,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder: string;
  addLabel: string;
  icon?: ReactNode;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const focus = (i: number) => requestAnimationFrame(() => refs.current[i]?.focus());

  const update = (i: number, v: string) => onChange(items.map((x, j) => (j === i ? v : x)));
  const insertAfter = (i: number) => {
    const next = [...items];
    next.splice(i + 1, 0, "");
    onChange(next);
    focus(i + 1);
  };
  const remove = (i: number) => {
    onChange(items.filter((_, j) => j !== i));
    focus(Math.max(0, i - 1));
  };
  const onKey = (i: number) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      insertAfter(i);
    } else if (e.key === "Backspace" && items[i] === "" && items.length > 0) {
      e.preventDefault();
      remove(i);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="flex h-5 w-5 flex-none items-center justify-center text-[var(--text-3)]">
            {icon ?? <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand)]" />}
          </span>
          <input
            ref={(el) => {
              refs.current[i] = el;
            }}
            value={item}
            onChange={(e) => update(i, e.target.value)}
            onKeyDown={onKey(i)}
            placeholder={placeholder}
            className="input h-9"
            aria-label={`${addLabel.replace(/^Add /, "")} ${i + 1}`}
          />
          <button
            type="button"
            onClick={() => remove(i)}
            aria-label={`Remove item ${i + 1}`}
            title="Remove"
            className="btn btn-ghost btn-sm h-8 w-8 flex-none p-0 text-[var(--text-3)]"
          >
            <IconX width={14} height={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => {
          onChange([...items, ""]);
          focus(items.length);
        }}
        className="btn btn-ghost btn-sm w-fit gap-1.5 text-[var(--brand)]"
      >
        <IconPlus width={14} height={14} /> {addLabel}
      </button>
    </div>
  );
}
