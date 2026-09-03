import Link from "next/link";
import { mediaUrl, type Session } from "@/lib/api";
import { Badge } from "@/components/ui";
import { IconPlay } from "@/components/icons";
import { fmtDateIST } from "@/lib/time";

const SOURCE_ICON: Record<string, string> = { recorder: "●", upload: "↑", extension: "◆" };

const mmss = (ms: number) => {
  const s = Math.round(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

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
    <Link href={href} className="card card-hover group flex flex-col overflow-hidden">
      {/* thumbnail */}
      <div className="relative aspect-video overflow-hidden bg-gradient-to-br from-[#1c1c2e] to-[#2b2b45]">
        {s.poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(s.poster)}
            alt={s.source_type}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-2xl text-white/40">
            {SOURCE_ICON[s.source_type] ?? "●"}
          </div>
        )}
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white/90 pl-0.5 text-[#7C3AED] shadow-lg">
            <IconPlay width={16} height={16} />
          </span>
        </span>
        <span className="absolute left-2 top-2">{statusBadge(s.status)}</span>
        {s.duration_ms ? (
          <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {mmss(s.duration_ms)}
          </span>
        ) : null}
      </div>

      {/* body */}
      <div className="flex flex-1 flex-col p-5">
        <h3 className="truncate text-[17px] font-semibold capitalize text-[var(--text)]">
          {projectName ?? s.source_type}
        </h3>
        <div className="mt-1 truncate text-sm text-[var(--text-2)]">
          {projectName ? `${s.source_type} · ` : ""}
          {fmtDateIST(s.created_at)}
        </div>
        <div className="mt-3.5 flex items-center justify-between border-t border-[var(--border)] pt-3">
          <span
            className={`badge px-2.5 py-1 ${
              s.telemetry === "present"
                ? "bg-[#7C3AED]/10 text-[#7C3AED]"
                : "bg-[var(--text-3)]/10 text-[var(--text-2)]"
            }`}
          >
            {s.telemetry === "present" ? "clicks" : "video"}
          </span>
        </div>
      </div>
    </Link>
  );
}
