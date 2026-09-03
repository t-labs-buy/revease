/** Date/time display helpers.
 *
 * Most API timestamps are stored in UTC but arrive with no zone marker (SQLite
 * drops it), so `new Date(iso)` would silently misread them as local time.
 * These helpers tag such strings as UTC, then always DISPLAY in IST — the
 * product's timezone — regardless of the viewer's machine settings.
 */

const IST = "Asia/Kolkata";

/** Tag a zone-less API timestamp as the UTC instant it actually is. */
const asUtc = (iso: string) => (/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);

/** "3 Sept 2026" in IST, or "—" for missing/invalid input. */
export function fmtDateIST(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(asUtc(iso));
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: IST });
}
