"use client";

/**
 * State machine for the document page: load → (none | queued/running → poll) →
 * ready (editor with autosave) | error.
 *
 * Why the working copy is never replaced wholesale once ready: a poll answer
 * (snapshot re-grab) arriving mid-edit would clobber the user's typing, so only
 * the targeted step's `snapshot` is merged — into both `doc` and `savedDoc`, so
 * the swap never counts as an unsaved edit either.
 *
 * Why sequence counters: a slow PATCH or GET must not overwrite state produced
 * by a later one. Every save and every generate bumps a counter and results
 * carrying an old value are dropped.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  generateDocument,
  getDocument,
  saveDocument,
  setStepSnapshot,
  type DocSnapshot,
  type DocStatus,
  type DocumentState,
  type DocV2,
} from "@/lib/api";

export type Phase = "loading" | "none" | "queued" | "running" | "error" | "ready";
export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";
export interface GenerateOpts {
  instruction?: string;
  skill_id?: string;
}

const AUTOSAVE_MS = 800;
const POLL_MS = 2000;
const SNAPSHOT_POLL_MS = 1500;
const SNAPSHOT_POLL_MAX = 40; // ~60s

const phaseOf = (status: DocStatus, hasDoc: boolean): Phase => {
  if (status === "queued" || status === "running" || status === "error") return status;
  if (status === "ready" && hasDoc) return "ready";
  return "none";
};

const withSnapshot = (doc: DocV2 | null, stepId: string, snapshot: DocSnapshot | null): DocV2 | null =>
  doc ? { ...doc, steps: doc.steps.map((s) => (s.id === stepId ? { ...s, snapshot } : s)) } : doc;

export function useDocumentState(projectId: string) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [serverError, setServerError] = useState<string | null>(null);
  const [state, setState] = useState<DocumentState | null>(null);
  const [doc, setDocState] = useState<DocV2 | null>(null);
  const [savedDoc, setSavedDoc] = useState<DocV2 | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [snapshotBusy, setSnapshotBusy] = useState<Record<string, true>>({});
  const [lastOpts, setLastOpts] = useState<GenerateOpts>({});

  const docRef = useRef<DocV2 | null>(null);
  const saveStateRef = useRef<SaveState>("idle");
  const genSeq = useRef(0);
  const saveSeq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setDoc = useCallback((next: DocV2 | null) => {
    docRef.current = next;
    setDocState(next);
  }, []);
  const setSave = useCallback((s: SaveState) => {
    saveStateRef.current = s;
    setSaveState(s);
  }, []);

  /** Apply a server answer that describes the whole document (load, poll). */
  const applyState = useCallback(
    (s: DocumentState) => {
      setState(s);
      const next = phaseOf(s.status, !!s.doc);
      if (next === "ready") {
        setDoc(s.doc);
        setSavedDoc(s.doc);
        setSave("idle");
      }
      if (next === "error") setServerError(s.error?.error ?? "Generation failed");
      setPhase(next);
    },
    [setDoc, setSave],
  );

  const reload = useCallback(async () => {
    const seq = genSeq.current;
    try {
      const s = await getDocument(projectId);
      if (seq === genSeq.current) applyState(s);
    } catch (e) {
      setServerError(String(e instanceof Error ? e.message : e));
      setPhase("error");
    }
  }, [projectId, applyState]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // poll while the worker is on it
  useEffect(() => {
    if (phase !== "queued" && phase !== "running") return;
    const seq = genSeq.current;
    const id = setInterval(async () => {
      try {
        const s = await getDocument(projectId);
        if (seq === genSeq.current) applyState(s);
      } catch {
        /* transient; keep polling */
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [phase, projectId, applyState]);

  // ---- autosave ----

  const save = useCallback(async () => {
    const snapshot = docRef.current;
    if (!snapshot) return;
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const seq = ++saveSeq.current;
    setSave("saving");
    setSaveError(null);
    try {
      const r = await saveDocument(projectId, snapshot);
      if (seq !== saveSeq.current) return; // a newer save is in flight
      setSavedDoc(r.doc ?? snapshot);
      setState(r);
      setSave(docRef.current === snapshot ? "saved" : "dirty");
      if (docRef.current !== snapshot) scheduleSave();
    } catch (e) {
      if (seq !== saveSeq.current) return;
      setSave("error");
      setSaveError(String(e instanceof Error ? e.message : e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, setSave]);

  const scheduleSave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(), AUTOSAVE_MS);
  }, [save]);

  const edit = useCallback(
    (next: DocV2) => {
      setDoc(next);
      setSave("dirty");
      scheduleSave();
    },
    [setDoc, setSave, scheduleSave],
  );

  /** Save now if anything is pending. Awaits the PATCH. */
  const flush = useCallback(async () => {
    if (saveStateRef.current === "dirty" || saveStateRef.current === "error") await save();
  }, [save]);

  const dirty = saveState === "dirty" || saveState === "saving" || saveState === "error";

  // leaving the page with unsaved edits: warn, and fire a keepalive save
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (saveStateRef.current === "dirty" || saveStateRef.current === "saving") {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    const onPageHide = () => {
      // fetch keepalive bodies are capped (~64KB in Chromium); fine at our sizes
      if (saveStateRef.current === "dirty" && docRef.current) {
        void saveDocument(projectId, docRef.current, { keepalive: true }).catch(() => {});
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, [projectId]);

  // ---- generate ----

  const generate = useCallback(
    async (opts: GenerateOpts = {}) => {
      await flush();
      setLastOpts(opts);
      genSeq.current += 1;
      setServerError(null);
      setPhase("queued");
      try {
        const s = await generateDocument(projectId, opts);
        setState(s);
        setPhase(phaseOf(s.status, false) === "ready" ? "queued" : phaseOf(s.status, false));
      } catch (e) {
        setServerError(String(e instanceof Error ? e.message : e));
        setPhase("error");
      }
    },
    [projectId, flush],
  );

  // ---- snapshots ----

  const changeSnapshot = useCallback(
    async (stepId: string, tSeconds: number) => {
      await flush();
      setSnapshotBusy((b) => ({ ...b, [stepId]: true }));
      try {
        // The API marks the step `pending` before it answers, so the first poll
        // that comes back not-pending means the worker has written the frame —
        // even when the chosen moment (and therefore the key) is unchanged.
        await setStepSnapshot(projectId, stepId, tSeconds);
        for (let i = 0; i < SNAPSHOT_POLL_MAX; i++) {
          await new Promise((r) => setTimeout(r, SNAPSHOT_POLL_MS));
          const s = await getDocument(projectId);
          const step = s.doc?.steps.find((x) => x.id === stepId);
          if (!step) break; // deleted meanwhile
          const snap = step.snapshot ?? null;
          if (!snap?.pending) {
            setDoc(withSnapshot(docRef.current, stepId, snap));
            setSavedDoc((d) => withSnapshot(d, stepId, snap));
            setState((st) => (st ? { ...st, stale: s.stale, latest_graph_version: s.latest_graph_version } : st));
            return;
          }
        }
        throw new Error("The frame is taking too long — is the worker running?");
      } finally {
        setSnapshotBusy((b) => {
          const { [stepId]: _gone, ...rest } = b;
          return rest;
        });
      }
    },
    [projectId, flush, setDoc],
  );

  const removeSnapshot = useCallback(
    (stepId: string) => {
      const cur = docRef.current;
      if (cur) edit(withSnapshot(cur, stepId, null)!);
    },
    [edit],
  );

  /** Show the last ready document again after a failed regenerate. */
  const openLastVersion = useCallback(() => {
    if (state?.doc) {
      setDoc(state.doc);
      setSavedDoc(state.doc);
      setSave("idle");
      setPhase("ready");
    }
  }, [state, setDoc, setSave]);

  return {
    phase,
    serverError,
    state,
    doc,
    savedDoc,
    saveState,
    saveError,
    dirty,
    snapshotBusy,
    lastOpts,
    generate,
    edit,
    save,
    flush,
    reload,
    changeSnapshot,
    removeSnapshot,
    openLastVersion,
  };
}
