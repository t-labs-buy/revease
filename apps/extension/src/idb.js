// Minimal IndexedDB buffer. Events + screenshots survive service-worker suspension
// (MV3 workers are short-lived), so a long capture loses nothing.

const DB_NAME = "refract-capture";
const DB_VERSION = 1;

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("events")) {
        db.createObjectStore("events", { keyPath: "seq" });
      }
      if (!db.objectStoreNames.contains("screenshots")) {
        db.createObjectStore("screenshots", { keyPath: "seq" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx(db, store, mode) {
  return db.transaction(store, mode).objectStore(store);
}

export async function putEvent(evt) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const r = tx(db, "events", "readwrite").put(evt);
    r.onsuccess = () => resolve();
    r.onerror = () => reject(r.error);
  });
}

export async function putScreenshot(seq, dataUrl) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const r = tx(db, "screenshots", "readwrite").put({ seq, dataUrl });
    r.onsuccess = () => resolve();
    r.onerror = () => reject(r.error);
  });
}

export async function getAll(store) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const r = tx(db, store, "readonly").getAll();
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

export async function clearAll() {
  const db = await open();
  await Promise.all(
    ["events", "screenshots"].map(
      (s) =>
        new Promise((resolve, reject) => {
          const r = tx(db, s, "readwrite").clear();
          r.onsuccess = () => resolve();
          r.onerror = () => reject(r.error);
        }),
    ),
  );
}
