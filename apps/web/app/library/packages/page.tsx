"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createPackage, deletePackage, listPackages, mediaUrl, type BrandPackage } from "@/lib/api";

export default function PackagesPage() {
  const router = useRouter();
  const [pkgs, setPkgs] = useState<BrandPackage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = () => listPackages().then(setPkgs).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  async function create() {
    setCreating(true);
    try {
      const p = await createPackage("Untitled brand", {
        outro: "Thanks for watching!",
        primary_color: "#6d5dfb",
        accent_color: "#a855f7",
        font: "Geist",
      });
      router.push(`/library/packages/${p.id}`);
    } catch (e) {
      setError(String(e));
      setCreating(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="mb-1 text-sm text-[var(--text-3)]">
            <Link href="/library" className="hover:text-[var(--text)]">
              Library
            </Link>{" "}
            / Brand Packages
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Brand Packages</h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
            Intro/outro, logo, colours and a brand voice — reference a package by name in a skill to
            brand generated output.
          </p>
        </div>
        <button onClick={create} disabled={creating} className="btn btn-primary">
          {creating ? "Creating…" : "+ New package"}
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {pkgs.map((p) => {
          const s = (p.settings || {}) as Record<string, string>;
          const logo = s.logo_key ? mediaUrl(s.logo_key) : s.logo_url;
          return (
            <div key={p.id} className="card card-hover group overflow-hidden">
              <div
                className="relative flex h-24 items-center justify-center"
                style={{ background: `linear-gradient(135deg, ${s.primary_color || "#6d5dfb"}, ${s.accent_color || "#a855f7"})` }}
              >
                {logo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={logo} alt="" className="h-9 object-contain" />
                ) : (
                  <span className="text-white/80">◆</span>
                )}
              </div>
              <div className="p-4">
                <div className="flex items-center gap-2">
                  <h3 className="truncate font-semibold text-[var(--text)]">{p.name}</h3>
                  <button
                    onClick={() => deletePackage(p.id).then(load)}
                    className="ml-auto text-[var(--text-3)] opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                  >
                    ✕
                  </button>
                </div>
                <p className="mt-1 line-clamp-1 text-sm text-[var(--text-2)]">{s.intro || "—"}</p>
                <Link href={`/library/packages/${p.id}`} className="btn btn-secondary btn-sm mt-3 w-full">
                  Edit
                </Link>
              </div>
            </div>
          );
        })}
        {pkgs.length === 0 && !error && (
          <p className="text-sm text-[var(--text-2)]">No packages yet — create one to brand your videos.</p>
        )}
      </div>
    </main>
  );
}
