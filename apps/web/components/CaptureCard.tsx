import Link from "next/link";
import { mediaUrl, type Session } from "@/lib/api";
import { Badge } from "@/components/ui";

const SOURCE_ICON: Record<string, string> = { recorder: "●", upload: "↑", extension: "◆" };

function statusBadge(status: string) {
  if (status === "ready") return <Badge tone="green">ready</Badge>;
  if (status === "processing") return <Badge tone="amber">processing</Badge>;
  return <Badge tone="zinc">queued</Badge>;
}

export function CaptureCard({
  session: s,
  href,
  projectName,
}: {
  session: Session;
  href: string;
  projectName?: string;
}) {
  return (
    <Link href={href} className="card card-hover group overflow-hidden">
      <div className="relative aspect-video w-full overflow-hidden bg-zinc-950">
        {s.poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(s.poster)}
            alt={s.source_type}
            className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-2xl text-zinc-700">
            {SOURCE_ICON[s.source_type] ?? "●"}
          </div>
        )}
        <div className="absolute right-2 top-2">{statusBadge(s.status)}</div>
        {s.duration_ms ? (
          <div className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[11px] text-zinc-200">
            {(s.duration_ms / 1000).toFixed(0)}s
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-2 px-3.5 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium capitalize text-zinc-100">
            {projectName ?? s.source_type}
          </div>
          <div className="mt-0.5 truncate text-xs text-zinc-500">
            {projectName ? `${s.source_type} · ` : ""}
            {new Date(s.created_at).toLocaleDateString()}
          </div>
        </div>
        <Badge tone={s.telemetry === "present" ? "violet" : "zinc"}>
          {s.telemetry === "present" ? "clicks" : "video"}
        </Badge>
      </div>
    </Link>
  );
}
