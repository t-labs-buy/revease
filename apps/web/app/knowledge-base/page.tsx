"use client";

import { useEffect, useMemo, useState } from "react";
import { createArticle, deleteArticle, listArticles, type Article, type ListScope } from "@/lib/api";
import { ScopeToggle } from "@/components/ScopeToggle";

/** Tiny markdown renderer: #/## headings, - bullets, **bold**, paragraphs. */
function Markdown({ text }: { text: string }) {
  const bold = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i} className="font-semibold text-[var(--text)]">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <span key={i}>{part}</span>
      ),
    );
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      out.push(
        <ul key={`ul${out.length}`} className="my-2 list-disc space-y-1 pl-5 text-[var(--text-2)]">
          {list.map((li, i) => (
            <li key={i}>{bold(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  lines.forEach((raw, i) => {
    const l = raw.trimEnd();
    if (l.startsWith("- ")) {
      list.push(l.slice(2));
    } else if (l.startsWith("## ")) {
      flush();
      out.push(<h3 key={i} className="mt-4 text-base font-semibold text-[var(--text)]">{bold(l.slice(3))}</h3>);
    } else if (l.startsWith("# ")) {
      flush();
      out.push(<h2 key={i} className="mt-2 text-lg font-semibold text-[var(--text)]">{bold(l.slice(2))}</h2>);
    } else if (l.trim() === "") {
      flush();
    } else {
      flush();
      out.push(<p key={i} className="my-2 text-[15px] leading-relaxed text-[var(--text-2)]">{bold(l)}</p>);
    }
  });
  flush();
  return <div>{out}</div>;
}

export default function KnowledgeBasePage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [tags, setTags] = useState("");
  const [body, setBody] = useState("");
  const [scope, setScope] = useState<ListScope>("mine");

  const load = () =>
    listArticles(scope)
      .then((a) => {
        setArticles(a);
        setSel((s) => s ?? a[0]?.id ?? null);
      })
      .catch((e) => setError(String(e)));
  useEffect(() => {
    setSel(null); // the previous selection may not exist in the new scope
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return articles;
    return articles.filter(
      (a) =>
        a.title.toLowerCase().includes(t) ||
        a.summary.toLowerCase().includes(t) ||
        a.tags.some((x) => x.toLowerCase().includes(t)),
    );
  }, [articles, q]);
  const active = articles.find((a) => a.id === sel) ?? null;

  async function submit() {
    if (!title.trim()) return;
    try {
      const a = await createArticle({
        title,
        summary,
        body_md: body,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      setTitle("");
      setSummary("");
      setTags("");
      setBody("");
      setCreating(false);
      await load();
      setSel(a.id);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Knowledge Base</h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
            Guides and docs — searchable and shareable in one place.
          </p>
        </div>
        <ScopeToggle scope={scope} onChange={setScope} mineLabel="My articles" allLabel="All articles" />
        <button onClick={() => setCreating((v) => !v)} className="btn btn-primary">
          {creating ? "Cancel" : "+ New article"}
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {creating && (
        <div className="card mt-6 space-y-3 p-5">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" className="input" />
          <input value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="One-line summary" className="input" />
          <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Tags (comma separated)" className="input" />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Body (Markdown: # heading, - bullet, **bold**)"
            className="input min-h-[140px] resize-y"
          />
          <button onClick={submit} className="btn btn-primary">
            Publish
          </button>
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(280px,340px)_1fr]">
        {/* list */}
        <div className="space-y-3">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search articles…" className="input" />
          {filtered.map((a) => (
            <button
              key={a.id}
              onClick={() => setSel(a.id)}
              className={`card card-hover w-full p-4 text-left ${
                sel === a.id ? "border-[#6d5dfb]/50 ring-1 ring-[#6d5dfb]/30" : ""
              }`}
            >
              <div className="font-medium text-[var(--text)]">{a.title}</div>
              <div className="mt-1 line-clamp-2 text-sm text-[var(--text-2)]">{a.summary}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {a.tags.map((t) => (
                  <span key={t} className="rounded-md bg-[#6d5dfb]/10 px-2 py-0.5 text-[11px] text-[var(--brand-2)]">
                    {t}
                  </span>
                ))}
              </div>
            </button>
          ))}
          {filtered.length === 0 && <p className="text-sm text-[var(--text-2)]">No articles found.</p>}
        </div>

        {/* reader */}
        <div className="card min-h-[300px] p-6">
          {active ? (
            <article>
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-2xl font-semibold tracking-tight text-[var(--text)]">{active.title}</h2>
                <button
                  onClick={() => deleteArticle(active.id).then(() => { setSel(null); load(); })}
                  className="btn btn-ghost btn-sm text-[var(--text-2)]"
                >
                  Delete
                </button>
              </div>
              <p className="mt-1 text-sm text-[var(--text-2)]">{active.summary}</p>
              <div className="mt-4 border-t border-[var(--border)] pt-4">
                <Markdown text={active.body_md} />
              </div>
            </article>
          ) : (
            <p className="text-sm text-[var(--text-2)]">Select an article to read it here.</p>
          )}
        </div>
      </div>
    </main>
  );
}
