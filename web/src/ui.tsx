import { ReactNode, useState } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Button({ children, onClick, kind = "primary", disabled, busy, small, type = "button", title }: {
  children: ReactNode; onClick?: () => void; kind?: "primary" | "secondary" | "ghost" | "danger"; disabled?: boolean;
  busy?: boolean; small?: boolean; type?: "button" | "submit"; title?: string;
}) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-stone-800 border border-stone-300 hover:bg-stone-100",
    ghost: "text-stone-600 hover:bg-stone-100",
    danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50",
  }[kind];
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || busy}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer",
        small ? "px-2.5 py-1 text-sm" : "px-4 py-2", styles)}>
      {busy && <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-2xl border border-stone-200 bg-white p-5 shadow-sm", className)}>{children}</div>;
}

const BADGE = {
  LIVE: "bg-green-100 text-green-800", CACHED: "bg-sky-100 text-sky-800", DEMO: "bg-amber-100 text-amber-800",
  SAMPLE: "bg-amber-100 text-amber-800", FAILED: "bg-red-100 text-red-800", standard: "bg-stone-100 text-stone-700",
  creator: "bg-violet-100 text-violet-800", vfm: "bg-emerald-100 text-emerald-800", web: "bg-sky-100 text-sky-800",
  osm: "bg-teal-100 text-teal-800", owner: "bg-stone-100 text-stone-700", neutral: "bg-stone-100 text-stone-700",
  pinned: "bg-brand-100 text-brand-700",
} as const;
export type BadgeKind = keyof typeof BADGE;

export function Badge({ kind = "neutral", children, title }: { kind?: BadgeKind; children: ReactNode; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", BADGE[kind])}>{children}</span>;
}

export const ROUTE_LABEL = { standard: "Fix Pack", creator: "Creators", vfm: "Value-for-Money" } as const;

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "bad" | "good" }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4">
      <div className="text-sm text-stone-500">{label}</div>
      <div className={cx("mt-1 text-3xl font-bold", tone === "bad" && "text-red-700", tone === "good" && "text-green-700")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-stone-500">{hint}</div>}
    </div>
  );
}

export function More({ label, children, open: start = false }: { label: string; children: ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(start);
  return (
    <div>
      <button className="text-sm font-medium text-brand-700 hover:underline cursor-pointer" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

export function Field({ label, hint, children, required }: { label: ReactNode; hint?: ReactNode; children: ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-stone-700">{label}{required && <span className="text-brand-600"> *</span>}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-stone-900 placeholder:text-stone-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100";

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>;
}

export function Bar({ value, max = 1, highlight }: { value: number; max?: number; highlight?: boolean }) {
  return (
    <div className="h-2.5 w-full rounded-full bg-stone-100">
      <div className={cx("h-2.5 rounded-full", highlight ? "bg-brand-500" : "bg-stone-400")} style={{ width: `${Math.min(100, (value / (max || 1)) * 100)}%` }} />
    </div>
  );
}

export function SourceLinks({ sources, max = 4 }: { sources: { url: string; title?: string }[]; max?: number }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {sources.slice(0, max).map((s) => (
        <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="text-sky-700 hover:underline truncate max-w-64">
          {s.title || s.url}
        </a>
      ))}
      {sources.length > max && <span className="text-stone-500">+{sources.length - max} more</span>}
    </div>
  );
}

export function copy(text: string) {
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

export function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
