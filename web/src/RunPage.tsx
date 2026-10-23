import { useEffect, useRef, useState } from "react";
import { api, Job, Profile, Status } from "./api";
import { Badge, Button, Card, ErrorNote, cx } from "./ui";
import { go } from "./App";

type Estimate = { questions: number; max_calls: number; cached: Record<string, number>; model: string; rough_max_cost_usd: number };

export default function RunPage({ slug, status, fresh }: { slug: string; status: Status | null; fresh?: boolean }) {
  const isSample = slug === "example";
  const [profile, setProfile] = useState<Profile | null>(null);
  const [runs, setRuns] = useState(1);
  const [webSearch, setWebSearch] = useState(true);
  const [reuse, setReuse] = useState(!fresh);  // #/r/<slug>/run/fresh = re-check with fresh answers
  const [est, setEst] = useState<Estimate | null>(null);
  const [useClaude, setUseClaude] = useState(true);
  const [useSaved, setUseSaved] = useState<Record<string, boolean>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const poll = useRef<number>(undefined);

  useEffect(() => {
    api.get<{ profile: Profile }>(`/api/restaurants/${slug}`).then((d) => setProfile(d.profile)).catch((e) => setError(e.message));
    return () => window.clearInterval(poll.current);
  }, [slug]);
  useEffect(() => {
    if (isSample) return;
    api.get<Estimate>(`/api/restaurants/${slug}/estimate?runs=${runs}`).then(setEst).catch(() => undefined);
  }, [slug, runs, isSample]);

  const claudeOn = !!status?.claude_key && useClaude;
  const savedPlatforms = Object.entries(est?.cached || {}).filter(([p]) => p !== "claude");
  const platforms = [...(claudeOn ? ["claude"] : []), ...savedPlatforms.filter(([p]) => useSaved[p]).map(([p]) => p)];

  async function start() {
    setError(null);
    try {
      const j = await api.post<Job>(`/api/restaurants/${slug}/run`, { runs, reuse, web_search: webSearch, platforms: isSample ? null : platforms });
      setJob(j);
      poll.current = window.setInterval(async () => {
        try {
          const s = await api.get<Job>(`/api/jobs/${j.id}`);
          setJob(s);
          if (s.state !== "running") {
            window.clearInterval(poll.current);
            if (s.state === "done") go(`/r/${slug}/results`);
          }
        } catch (e) { setError((e as Error).message); window.clearInterval(poll.current); }
      }, 700);
    } catch (e) { setError((e as Error).message); }
  }

  if (!profile) return <ErrorNote error={error} />;
  const running = job?.state === "running";
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {!isSample && (
        <ol className="flex flex-wrap gap-2 text-sm">
          {["Your restaurant", "Competitors nearby", "Run the check"].map((n, i) => (
            <li key={n} className={cx("rounded-full px-3 py-1", i === 2 ? "bg-brand-600 text-white" : "bg-brand-100 text-brand-700")}>{i + 1}. {n}</li>
          ))}
        </ol>
      )}
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Check how AI recommends {profile.name}</h1>
            <p className="mt-1 text-stone-600">
              We ask {isSample ? 30 : est?.questions ?? 30} questions real customers ask — like “best {profile.cuisine} near {profile.area}” — and count
              how often {profile.name} is named, against {(profile.competitors || []).length} competitors.
            </p>
          </div>
          {isSample && <Badge kind="SAMPLE">SAMPLE</Badge>}
        </div>

        {isSample ? (
          <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This uses saved SAMPLE answers — free, no AI calls.</p>
        ) : (
          <div className="mt-5 space-y-4">
            <div>
              <div className="text-sm font-semibold">Ask which AI</div>
              <label className="mt-2 flex items-center gap-3">
                <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={claudeOn} disabled={!status?.claude_key} onChange={(e) => setUseClaude(e.target.checked)} />
                <span>Claude <span className="text-sm text-stone-500">({est?.model || status?.discovery_model}) — live</span></span>
                {!status?.claude_key && <Badge kind="FAILED">no key in .env</Badge>}
              </label>
              {savedPlatforms.map(([p, n]) => (
                <label key={p} className="mt-2 flex items-center gap-3">
                  <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={!!useSaved[p]} onChange={(e) => setUseSaved({ ...useSaved, [p]: e.target.checked })} />
                  <span className="capitalize">{p}</span> <span className="text-sm text-stone-500">— {n} saved real answers (free to re-show)</span>
                </label>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="text-sm font-semibold">How many times to ask each question</div>
                <div className="mt-2 flex gap-2">
                  {[1, 2, 3].map((n) => (
                    <button key={n} onClick={() => setRuns(n)} className={cx("cursor-pointer rounded-lg border px-4 py-1.5", runs === n ? "border-brand-600 bg-brand-50 font-semibold text-brand-700" : "border-stone-300")}>{n}×</button>
                  ))}
                </div>
                <p className="mt-1 text-xs text-stone-500">AI answers vary, so 3× is more reliable. 1× is fine for a first look.</p>
              </div>
              <div className="space-y-2">
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={webSearch} onChange={(e) => setWebSearch(e.target.checked)} />
                  <span><span className="font-medium">Let Claude search the web</span><br /><span className="text-xs text-stone-500">How Claude answers real users — and we see which sites it trusts.</span></span>
                </label>
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={reuse} onChange={(e) => setReuse(e.target.checked)} />
                  <span><span className="font-medium">Reuse saved answers</span><br /><span className="text-xs text-stone-500">Untick for a fresh measurement after you've made changes.</span></span>
                </label>
              </div>
            </div>
            <div className="rounded-lg bg-stone-50 p-3 text-sm text-stone-700">
              Up to <b>{(est?.questions ?? 30) * runs * (claudeOn ? 1 : 0)}</b> new Claude questions
              {claudeOn && <> (fewer when saved answers are reused)</>}.
              {!claudeOn && platforms.length > 0 && <> Showing saved answers only.</>}
            </div>
          </div>
        )}

        <ErrorNote error={error} />
        {job?.state === "failed" && <ErrorNote error={job.error} />}
        <div className="mt-5">
          {running ? (
            <div>
              <div className="flex justify-between text-sm"><span>Asking… {job.done}/{job.total || "?"}</span>
                <button className="cursor-pointer text-stone-500 hover:text-red-600" onClick={() => api.post(`/api/jobs/${job.id}/stop`)}>Stop (keeps what arrived)</button></div>
              <div className="mt-2 h-3 w-full rounded-full bg-stone-100"><div className="h-3 rounded-full bg-brand-500 transition-all" style={{ width: `${job.total ? (job.done / job.total) * 100 : 3}%` }} /></div>
              <p className="mt-2 truncate text-xs text-stone-500">{job.note}</p>
            </div>
          ) : (
            <div className="flex gap-3">
              <Button onClick={start} disabled={!isSample && platforms.length === 0}>▶ Run the check</Button>
              {!isSample && <Button kind="ghost" onClick={() => go(`/r/${slug}/setup/2`)}>← Competitors</Button>}
              <Button kind="ghost" onClick={() => go(`/r/${slug}/results`)}>See last results</Button>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
