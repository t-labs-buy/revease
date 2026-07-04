import type { Skill } from "@/lib/api";

type Sec = { title: string; description?: string; include_screenshots?: boolean };

/** Render a skill as a Claude-style SKILL.md: YAML frontmatter + a readable body,
 *  with a lossless payload comment so it round-trips on import. */
export function skillToMarkdown(s: Skill): string {
  const st = (s.settings || {}) as Record<string, unknown>;
  const fm: string[] = [`name: ${s.name}`, `description: ${s.description || ""}`, `target: ${s.target}`];
  const tags = Array.isArray(st.tags) ? (st.tags as string[]) : [];
  if (tags.length) fm.push(`tags: [${tags.join(", ")}]`);
  if (typeof st.package === "string" && st.package) fm.push(`package: ${st.package}`);

  let body = "";
  if (typeof st.overall_instructions === "string" && st.overall_instructions)
    body += `## Overall Instructions\n\n${st.overall_instructions}\n\n`;
  if (typeof st.instruction === "string" && st.instruction)
    body += `## AI Instruction\n\n${st.instruction}\n\n`;

  const secs = Array.isArray(st.sections) ? (st.sections as Sec[]) : [];
  if (secs.length) {
    body += `## Sections\n\n`;
    for (const sec of secs)
      body += `### ${sec.title}\n\n${sec.description || ""}\n\n${sec.include_screenshots ? "_Includes screenshots._\n\n" : ""}`;
  }
  if (s.target === "video") {
    body +=
      `## Video\n\n` +
      `- Voice: ${st.voice_id ?? "af_sarah"}\n` +
      `- Speed: ${st.speed ?? 1}\n` +
      `- Captions: ${st.captions !== false}\n` +
      `- Auto-zoom on clicks: ${st.motion_zoom === true}\n\n`;
  }

  const payload = JSON.stringify({
    name: s.name,
    description: s.description,
    target: s.target,
    settings: s.settings,
  });
  return `---\n${fm.join("\n")}\n---\n\n${body}<!-- revease:skill ${payload} -->\n`;
}

/** Parse a SKILL.md back into a skill. Prefers the lossless payload comment; else
 *  reads the frontmatter + treats the body as overall instructions. */
export function markdownToSkill(md: string): {
  name: string;
  description: string;
  target: string;
  settings: Record<string, unknown>;
} {
  const payload = md.match(/<!--\s*revease:skill\s*([\s\S]*?)-->/);
  if (payload) {
    try {
      const o = JSON.parse(payload[1].trim());
      return {
        name: o.name || "Imported skill",
        description: o.description || "",
        target: o.target === "video" ? "video" : "doc",
        settings: o.settings || {},
      };
    } catch {
      /* fall through to frontmatter parse */
    }
  }

  let name = "Imported skill";
  let description = "";
  let target = "doc";
  let body = md;
  const fmMatch = md.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (fmMatch) {
    const fm = fmMatch[1];
    body = fmMatch[2];
    const g = (k: string) => (fm.match(new RegExp(`^${k}:\\s*(.*)$`, "m"))?.[1] || "").trim();
    name = g("name") || name;
    description = g("description");
    target = g("target") === "video" ? "video" : "doc";
  }
  return { name, description, target, settings: { overall_instructions: body.trim() } };
}
