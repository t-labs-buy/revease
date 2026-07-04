export type GalleryItem = {
  slug: string;
  name: string;
  target: "video" | "doc";
  category: string;
  icon: string;
  grad: string;
  description: string;
  settings: Record<string, unknown>;
};

/** Curated, ready-to-install skills (a small marketplace). */
export const SKILL_GALLERY: GalleryItem[] = [
  {
    slug: "product-demo",
    name: "Product Demo",
    target: "video",
    category: "Video",
    icon: "🎬",
    grad: "from-[#6d5dfb] to-[#a855f7]",
    description: "Screen walkthrough with auto-zoom on clicks and a clear AI voiceover.",
    settings: {
      voice_id: "af_sarah", speed: 1, captions: true, motion_zoom: true,
      tags: ["demo", "product"],
      instruction:
        "Rewrite as a clear, confident product demo narration: explain what each screen and action does and why it matters, in a friendly professional tone.",
    },
  },
  {
    slug: "marketing-explainer",
    name: "Marketing Explainer",
    target: "video",
    category: "Video",
    icon: "✨",
    grad: "from-[#f97316] to-[#ec4899]",
    description: "Punchy, benefit-led promo that hooks the viewer and ends with a call to action.",
    settings: {
      voice_id: "af_bella", speed: 1.05, captions: true, motion_zoom: true,
      tags: ["marketing", "promo"],
      instruction:
        "Rewrite as a punchy marketing explainer: benefit-led, exciting, hook early and end with a call to action.",
    },
  },
  {
    slug: "sales-demo",
    name: "Sales Demo",
    target: "video",
    category: "Video",
    icon: "📈",
    grad: "from-[#8b5cf6] to-[#0ea5e9]",
    description: "Confident, value-focused pitch that emphasizes business outcomes.",
    settings: {
      voice_id: "am_michael", speed: 1, captions: true, motion_zoom: true,
      tags: ["sales", "b2b"],
      instruction:
        "Rewrite as a persuasive sales demo narration: confident, value-focused, emphasize business outcomes and impact.",
    },
  },
  {
    slug: "social-reel",
    name: "Social Reel",
    target: "video",
    category: "Video",
    icon: "📱",
    grad: "from-[#ec4899] to-[#f59e0b]",
    description: "Vertical, high-energy clip for social — bold captions, tight pacing.",
    settings: {
      voice_id: "af_bella", speed: 1.1, aspect: "9:16", captions: true, motion_zoom: true,
      tags: ["social", "reel"],
      instruction: "Rewrite as a high-energy social reel: short, snappy lines with a strong hook.",
    },
  },
  {
    slug: "tutorial",
    name: "Tutorial / How-to",
    target: "video",
    category: "Video",
    icon: "🎓",
    grad: "from-[#22c55e] to-[#0ea5e9]",
    description: "Friendly step-by-step walkthrough for first-time users.",
    settings: {
      voice_id: "am_adam", speed: 1, captions: true, motion_zoom: true,
      tags: ["tutorial", "how-to"],
      instruction:
        "Rewrite as a friendly how-to tutorial: welcoming, clear, guiding a first-time user step by step.",
    },
  },
  {
    slug: "sop",
    name: "SOP Document",
    target: "doc",
    category: "Docs",
    icon: "📋",
    grad: "from-[#6366f1] to-[#06b6d4]",
    description: "Formal Standard Operating Procedure with numbered, imperative steps.",
    settings: {
      tags: ["sop", "handbook"],
      instruction:
        "Rewrite as a formal Standard Operating Procedure: precise, imperative step titles and clear professional instructions.",
      sections: [
        { title: "Overview", description: "Summarize the purpose of this procedure.", include_screenshots: false },
        { title: "Prerequisites", description: "List what's needed before starting.", include_screenshots: false },
        { title: "Steps", description: "List each step precisely, in order.", include_screenshots: true },
      ],
    },
  },
  {
    slug: "faq-guide",
    name: "FAQ Guide",
    target: "doc",
    category: "Docs",
    icon: "❓",
    grad: "from-[#8b5cf6] to-[#ec4899]",
    description: "Question-and-answer format generated from the transcript.",
    settings: {
      tags: ["faq", "support"],
      instruction:
        "Rewrite each step as a FAQ entry: phrase the title as a natural question and the body as a clear direct answer.",
    },
  },
  {
    slug: "release-notes",
    name: "Release Notes",
    target: "doc",
    category: "Docs",
    icon: "🚀",
    grad: "from-[#f43f5e] to-[#f97316]",
    description: "Changelog-style summary of what changed and why it matters.",
    settings: {
      tags: ["changelog", "release"],
      instruction:
        "Rewrite as concise release notes: group changes under What's New / Improvements / Fixes, one crisp line each.",
      sections: [
        { title: "What's New", description: "New capabilities shown.", include_screenshots: true },
        { title: "Improvements", description: "Enhancements to existing features.", include_screenshots: false },
      ],
    },
  },
  {
    slug: "onboarding-checklist",
    name: "Onboarding Checklist",
    target: "doc",
    category: "Docs",
    icon: "✅",
    grad: "from-[#10b981] to-[#6366f1]",
    description: "Welcome + setup steps + next steps for a new user.",
    settings: {
      tags: ["onboarding"],
      instruction: "Rewrite as a warm onboarding checklist: welcoming tone, clear checkable steps.",
      sections: [
        { title: "Welcome", description: "Greet the user and set expectations.", include_screenshots: false },
        { title: "Set up", description: "The steps to get set up.", include_screenshots: true },
        { title: "Next steps", description: "What to explore next.", include_screenshots: false },
      ],
    },
  },
];
