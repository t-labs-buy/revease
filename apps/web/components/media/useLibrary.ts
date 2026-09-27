"use client";

/**
 * The user's media library for the editor's Media tab: list, upload with
 * per-file progress, and a 2 s poll while anything is still being processed
 * (normalizing, removing a background, importing a recording) — the worker
 * flips those rows to ready/error on its own schedule.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteLibraryAsset,
  importRecording,
  listLibrary,
  removeBackground,
  uploadToLibrary,
  type LibraryAsset,
} from "@/lib/api";

export interface PendingUpload {
  key: string;
  name: string;
  loaded: number;
  total: number;
  error?: string;
}

const busy = (a: LibraryAsset) => a.status === "processing" || a.bg_status === "running";

/** The storage key the renderer should use for an asset (cut-out when asked). */
export function assetKey(a: LibraryAsset, nobg = false): string | null {
  if (a.kind === "image" && nobg && a.nobg_key) return a.nobg_key;
  return a.normalized_key || (a.status === "ready" ? a.storage_key : null);
}

/** A thumbnail key for the grid (cut-out preferred once it exists). */
export function assetThumb(a: LibraryAsset): string | null {
  if (a.kind === "image") return a.nobg_key || a.normalized_key || null;
  return a.poster_key;
}

export function useLibrary() {
  const [assets, setAssets] = useState<LibraryAsset[] | null>(null);
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const list = await listLibrary();
      if (alive.current) {
        setAssets(list);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  const polling = !!assets?.some(busy);
  useEffect(() => {
    if (!polling) return;
    const t = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(t);
  }, [polling, refresh]);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      await Promise.all(
        list.map(async (file) => {
          const key = `${file.name}:${file.size}:${file.lastModified}:${Math.random()}`;
          setUploads((u) => [...u, { key, name: file.name, loaded: 0, total: file.size }]);
          try {
            const asset = await uploadToLibrary(file, {
              onProgress: (p) =>
                setUploads((u) => u.map((x) => (x.key === key ? { ...x, loaded: p.loaded, total: p.total } : x))),
            });
            setUploads((u) => u.filter((x) => x.key !== key));
            setAssets((a) => [asset, ...(a ?? []).filter((x) => x.id !== asset.id)]);
          } catch (e) {
            setUploads((u) => u.map((x) => (x.key === key ? { ...x, error: (e as Error).message } : x)));
          }
        }),
      );
    },
    [],
  );

  const dismissUpload = (key: string) => setUploads((u) => u.filter((x) => x.key !== key));

  const cutout = useCallback(async (id: string) => {
    const a = await removeBackground(id);
    setAssets((list) => (list ?? []).map((x) => (x.id === id ? a : x)));
  }, []);

  const reuse = useCallback(async (sessionId: string) => {
    const a = await importRecording(sessionId);
    setAssets((list) => [a, ...(list ?? [])]);
    return a;
  }, []);

  const remove = useCallback(async (id: string) => {
    await deleteLibraryAsset(id);
    setAssets((list) => (list ?? []).filter((x) => x.id !== id));
  }, []);

  return { assets, uploads, error, refresh, upload, dismissUpload, cutout, reuse, remove };
}
