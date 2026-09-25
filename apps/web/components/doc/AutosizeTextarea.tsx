"use client";

import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

/** A textarea that grows with its content (no scrollbars in the editor). */
export function AutosizeTextarea({
  value,
  minRows = 2,
  className = "",
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string; minRows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  return <textarea ref={ref} value={value} rows={minRows} className={`input resize-none ${className}`} {...rest} />;
}
