import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AgentReview, AiQuote, Aiso, api, ApiError, CreatorsView, Evidence, Farm, Housekeeping, PeopleSay, pct, PackPiece, Results as R } from "./api";
import { Badge, BadgeKind, Bar, Button, Card, ErrorNote, EvidenceBadge, Field, inputCls, More, ROUTE_LABEL, SlowBar, SourceLinks, Stat, copy, cx, download } from "./ui";
import { go } from "./App";

const TABS = [
  ["rank", "1", "Where you rank"],
  ["housekeeping", "2", "Housekeeping"],
  ["social", "3", "Social media"],
  ["business", "4", "Business value"],
  ["farm", "5", "Data farming"],
  ["todo", "6", "Your to-do list"],
  ["improve", "7", "Did it improve?"],
] as const;
// old links keep working
const TAB_ALIAS: Record<string, string> = { why: "rank", change: "todo", make: "housekeeping" };

export default function Results({ slug, tab: rawTab }: { slug: string; tab: string }) {
  const tab = TAB_ALIAS[rawTab] || rawTab;
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.get<R>(`/api/restaurants/${slug}/results`).then(setR).catch((e) => setError(e.message)), [slug]);
  useEffect(() => { load(); }, [load]);

  if (error) return (
    <Card><ErrorNote error={error} /><div className="mt-3"><Button onClick={() => go(`/r/${slug}/run`)}>Run a check</Button></div></Card>
  );
  if (!r) return <p className="text-stone-500">Loading results…</p>;
  if (r.no_run) return <BeforeFirstCheck r={r} tab={tab} reload={load} />;
  const c = r.meta.counts;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{r.restaurant}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-stone-500">
            {r.is_sample && <Badge kind="SAMPLE">SAMPLE data</Badge>}
            {c.LIVE > 0 && <Badge kind="LIVE">{c.LIVE} live</Badge>}
            {c.CACHED > 0 && <Badge kind="CACHED">{c.CACHED} saved</Badge>}
            {c.DEMO > 0 && <Badge kind="DEMO">{c.DEMO} sample answers</Badge>}
            {c.FAILED > 0 && <Badge kind="FAILED" title="Left out of every number">{c.FAILED} no answer</Badge>}
            <span>· checked {r.meta.when} · {r.meta.platforms.join(" + ")}{r.meta.web_search ? " with web search" : ""}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button kind="secondary" onClick={() => go(`/r/${slug}/run`)}>Check again</Button>
          {!r.is_sample && <Button kind="ghost" onClick={() => go(`/r/${slug}/setup/1`)}>Edit setup</Button>}
        </div>
      </div>

      <TabNav slug={slug} tab={tab} reminders={activeReminders(r)} />

      <Headline text={r.headlines?.[tab]} />
      {r.empty ? <Card>No answers came back in the last check, so there's nothing to score. Try again in a few minutes.</Card> :
        tab === "housekeeping" ? <Make r={r} reload={load} /> :
        tab === "social" ? <SocialTab r={r} reload={load} /> :
        tab === "business" ? <BusinessTab r={r} reload={load} /> :
        tab === "farm" ? <FarmTab r={r} reload={load} /> :
        tab === "todo" ? <TodoTab r={r} reload={load} /> :
        tab === "improve" ? <Improve r={r} /> : <RankTab r={r} reload={load} />}
    </div>
  );
}

function TabNav({ slug, tab, reminders = 0 }: { slug: string; tab: string; reminders?: number }) {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-stone-200">
      {TABS.map(([key, n, label]) => (
        <a key={key} href={`#/r/${slug}/results/${key}`}
          className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium", tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-stone-500 hover:text-stone-800")}>
          <span className="mr-1 text-xs text-stone-400">{n}</span>{label}
          {key === "housekeeping" && reminders > 0 && <span className="ml-1 rounded-full bg-amber-100 px-1.5 text-xs text-amber-800">Reminders ({reminders})</span>}
        </a>
      ))}
    </nav>
  );
}

/** No check yet: "Make the changes" (FAQ, email, content pack) already works from the saved facts. */
function BeforeFirstCheck({ r, tab, reload }: { r: R; tab: string; reload: () => void }) {
  const active = tab;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{r.restaurant}</h1>
          <p className="mt-1 text-sm text-stone-500">Not checked yet - the website drafts below only need your saved facts.</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => go(`/r/${r.slug}/run`)}>Run the first check</Button>
          {!r.is_sample && <Button kind="ghost" onClick={() => go(`/r/${r.slug}/setup/1`)}>Edit setup</Button>}
        </div>
      </div>
      <TabNav slug={r.slug} tab={active} reminders={activeReminders(r)} />
      <Headline text={r.headlines?.[active]} />
      {active === "housekeeping" ? <Make r={r} reload={reload} /> : active === "business" ? <BusinessTab r={r} reload={reload} /> :
        active === "farm" ? <FarmTab r={r} reload={reload} /> : active === "social" ? <SocialTab r={r} reload={reload} /> :
        active === "todo" ? <TodoTab r={r} reload={reload} /> : active === "rank" ? <div className="space-y-5">
          <Card><p className="text-stone-700">Run the first check to see how often AI assistants recommend you.</p>
            <div className="mt-3"><Button onClick={() => go(`/r/${r.slug}/run`)}>Run the first check</Button></div></Card>
          <PeopleSaySection slug={r.slug} part="quotes" /><SourcesPanel slug={r.slug} /></div> : (
        <Card>
          <p className="text-stone-700">Run a check first - this answer comes from asking AI assistants the questions your customers ask.</p>
          <div className="mt-3"><Button onClick={() => go(`/r/${r.slug}/run`)}>Run the first check</Button></div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 1
function Rank({ r }: { r: R }) {
  const k = r.rank;
  const max = Math.max(...k.scorecard.map((s) => s.mention_rate), 0.01);
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="AI names you in" value={pct(k.mention_rate)} hint={`${k.mentions} of ${k.answers} answers`} tone={k.mention_rate < 0.2 ? "bad" : "good"} />
        <Stat label="Your position when named" value={k.avg_rank ?? "—"} hint="1 = named first" />
        {k.top_competitor && <Stat label={`${k.top_competitor.name} is named in`} value={pct(k.top_competitor.mention_rate)} hint="the most-recommended competitor" />}
        <Stat label="Question types where you never appear" value={`${k.categories_at_zero.length}`} hint={k.categories_at_zero.slice(0, 4).map((c) => c.replace(/-/g, " ")).join(", ")} tone={k.categories_at_zero.length ? "bad" : undefined} />
      </div>
      <Card>
        <h3 className="mb-3 font-semibold">How often each restaurant is recommended</h3>
        <div className="space-y-2">
          {k.scorecard.map((s) => (
            <div key={s.restaurant} className="grid grid-cols-[minmax(0,12rem)_1fr_3rem] items-center gap-3 text-sm">
              <span className={cx("truncate", s.restaurant === r.restaurant && "font-semibold text-brand-700")}>{s.restaurant}</span>
              <Bar value={s.mention_rate} max={max} highlight={s.restaurant === r.restaurant} />
              <span className="text-right">{pct(s.mention_rate)}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">By type of question</h3>
        <div className="flex flex-wrap gap-2">
          {k.by_category.map((c) => (
            <span key={c.category} className={cx("rounded-full px-3 py-1 text-sm", c.mention_rate === 0 ? "bg-red-50 text-red-800" : c.mention_rate < 0.34 ? "bg-amber-50 text-amber-900" : "bg-green-50 text-green-800")}>
              {c.category.replace(/-/g, " ")} · {pct(c.mention_rate)}
            </span>
          ))}
        </div>
      </Card>
      <Card>
        <More label={`Show every question and answer (${k.answers_list.length})`}>
          <div className="space-y-3">
            {k.answers_list.map((a, i) => (
              <div key={i} className="border-b border-stone-100 pb-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge kind={a.status as BadgeKind}>{a.status}</Badge>
                  <span className="font-medium">{a.query}</span>
                  <span className="text-xs text-stone-400">{a.platform} · run {a.run}</span>
                </div>
                <div className="mt-1 text-stone-600">Named: {a.mentions.length ? a.mentions.join(" → ") : "none of the tracked restaurants"}</div>
                <More label="answer"><p className="whitespace-pre-wrap text-stone-600">{a.answer || "(no answer)"}</p>{a.note && <p className="text-xs text-stone-400">{a.note}</p>}</More>
                <SourceLinks sources={a.sources} />
              </div>
            ))}
          </div>
        </More>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- 2
function Why({ r, reload }: { r: R; reload: () => void }) {
  const w = r.why;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [auto, setAuto] = useState<{ restaurant: string; rating?: number; review_count?: number; price_level?: number; sources?: Record<string, string>; error?: string;
    evidence?: Record<string, Evidence>; unverified?: Record<string, unknown>; rejected?: number }[] | null>(null);

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name); setError(null);
    try { await fn(); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(null);
  }
  const addCompetitor = (name: string) => act("add" + name, async () => {
    const d = await api.get<{ profile: { competitors: { name: string }[] } }>(`/api/restaurants/${r.slug}`);
    await api.put("/api/restaurants", { profile: { ...d.profile, competitors: [...d.profile.competitors, { name, website: "" }] }, previous_slug: r.slug });
  });

  return (
    <div className="space-y-5">
      <ErrorNote error={error} />
      <Card>
        <h3 className="font-semibold">The biggest reasons</h3>
        {w.gaps.length === 0 && w.site_gaps.length === 0 && (
          <p className="mt-2 text-sm text-stone-500">Not enough evidence yet. Run the website check below and add public ratings to see the reasons.</p>
        )}
        <div className="mt-3 space-y-3">
          {w.gaps.slice(0, 5).map((g) => (
            <div key={g.gap} className="rounded-xl border border-stone-200 p-3">
              <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{g.gap}</span><Badge kind={g.action}>fix: {ROUTE_LABEL[g.action]}</Badge></div>
              <p className="mt-1 text-sm text-stone-600">{g.evidence}</p>
            </div>
          ))}
          {w.site_gaps.filter((s) => !s.startsWith("No structural")).map((s) => (
            <div key={s} className="rounded-xl border border-stone-200 p-3 text-sm"><Badge kind="standard">website</Badge> <span className="ml-1">{s}</span></div>
          ))}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <h3 className="font-semibold">Websites the AI relied on</h3>
          <p className="text-sm text-stone-500">Where Claude looked before answering. Being mentioned on these is what gets you recommended.</p>
          {w.sources_ai_used.length ? (
            <ul className="mt-3 space-y-1 text-sm">{w.sources_ai_used.map((s) => (
              <li key={s.domain} className="flex justify-between"><span>{s.domain}</span><span className="text-stone-500">{s.answers} answers</span></li>))}
            </ul>
          ) : <p className="mt-3 text-sm text-stone-400">Shown when the check runs with web search on.</p>}
        </Card>
        <Card>
          <h3 className="font-semibold">Who the AI recommends instead</h3>
          <p className="text-sm text-stone-500">Names pulled from the answers that aren't on your competitor list. Check each one.</p>
          <ul className="mt-3 space-y-1 text-sm">
            {w.ai_recommends_instead.slice(0, 10).map((x) => (
              <li key={x.restaurant} className="flex items-center justify-between gap-2">
                <span className="truncate">{x.restaurant} <span className="text-stone-400">· {x.answers_naming_it}</span></span>
                {!r.is_sample && <Button small kind="ghost" busy={busy === "add" + x.restaurant} onClick={() => addCompetitor(x.restaurant)}>+ track</Button>}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Can the AI read your website?</h3>
            <p className="text-sm text-stone-500">Compares your site with the most-recommended competitor's: structured data, menu format, FAQ, dietary info.</p>
          </div>
          <Button kind="secondary" busy={busy === "audit"} onClick={() => act("audit", () => api.post(`/api/restaurants/${r.slug}/site-audit`))}>Check both websites</Button>
        </div>
        {Object.keys(w.site_audit).length > 0 && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {Object.entries(w.site_audit).map(([name, a]) => (
              <div key={name} className="rounded-lg bg-stone-50 p-3 text-sm">
                <div className="font-medium">{name}</div>
                <div className="text-xs text-stone-500">{a.source}</div>
                {a.audit && Object.keys(a.audit).length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {[["Restaurant schema", a.audit.has_restaurant_schema], ["Menu schema", a.audit.has_menu_schema], ["FAQ", a.audit.has_faq_page],
                      ["Menu only as PDF", a.audit.menu_is_pdf]].map(([k, v]) => (
                      <li key={String(k)} className="flex justify-between"><span>{String(k)}</span><span>{v ? "yes" : "no"}</span></li>))}
                    <li className="flex justify-between"><span>Words on home page</span><span>{String(a.audit.word_count ?? "—")}</span></li>
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Ratings and reviews</h3>
            <p className="text-sm text-stone-500">{w.listings_note} AI trusts places with more reviews.</p>
          </div>
          {!r.is_sample && <Button kind="secondary" busy={busy === "auto"} onClick={async () => { setBusy("auto"); setError(null);
            try { setAuto((await api.post<{ results: typeof auto }>(`/api/restaurants/${r.slug}/listings/auto`)).results); } catch (e) { setError((e as Error).message); } setBusy(null); }}>
            Find public ratings</Button>}
        </div>
        {Object.keys(w.listings).length > 0 && (
          <table className="mt-3 w-full text-sm">
            <thead><tr className="text-left text-stone-500"><th className="py-1">Restaurant</th><th>Rating</th><th>Reviews</th><th>Price</th></tr></thead>
            <tbody>{Object.entries(w.listings).map(([n, l]) => (
              <tr key={n} className="border-t border-stone-100"><td className="py-1">{n}</td><td>{l.rating ?? "—"}</td><td>{l.review_count ?? "—"}</td><td>{l.price_level ? "$".repeat(l.price_level) : "—"}</td></tr>))}
            </tbody>
          </table>
        )}
        {auto && (
          <div className="mt-4 space-y-2">
            <p className="text-sm font-medium">Found on the web — check each, then save:</p>
            {auto.map((a) => (
              <div key={a.restaurant} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-stone-50 p-2 text-sm">
                <span className="font-medium">{a.restaurant}</span>
                {a.error ? <span className="text-red-700">{a.error}</span> : (
                  <span className="flex items-center gap-3">
                    <span>{a.rating ?? "?"}★ · {a.review_count ?? "?"} reviews · {a.price_level ? "$".repeat(a.price_level) : "?"}</span>
                    <EvidenceBadge ev={a.evidence?.google_rating || a.evidence?.google_review_count || a.evidence?.price_level} />
                    {Object.keys(a.unverified || {}).length > 0 && <span className="text-xs text-stone-400" title="Not used - couldn't be checked on the cited page">{Object.keys(a.unverified || {}).length} unchecked</span>}
                    {!!a.rejected && <span className="text-xs text-stone-400">{a.rejected} rejected</span>}
                    <Button small busy={busy === "save" + a.restaurant} disabled={!a.rating && !a.review_count && !a.price_level}
                      onClick={() => act("save" + a.restaurant, () => api.post(`/api/restaurants/${r.slug}/listings`, { restaurant: a.restaurant, rating: a.rating ?? null,
                        review_count: a.review_count ?? null, price_level: a.price_level ?? null, source: `Claude web search: ${Object.values(a.sources || {}).join(" ")}`.slice(0, 500) }))}>Save</Button>
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- 3
function Change({ r, reload }: { r: R; reload: () => void }) {
  const ch = r.change;
  const groups = (["standard", "creator", "vfm"] as const).map((k) => [k, ch.moves.filter((m) => m.route === k)] as const);
  return (
    <div className="space-y-5">
      <Card>
        <h3 className="font-semibold">Changes by tool</h3>
        <p className="text-sm text-stone-500">Each item comes from the evidence in step 2 and says which tool fixes it.</p>
        {ch.moves.length === 0 && <p className="mt-3 text-sm text-stone-500">No changes found yet — check the websites and add ratings in step 2.</p>}
        <div className="mt-3 grid gap-4 lg:grid-cols-3">
          {groups.map(([k, ms]) => (
            <div key={k}>
              <div className="mb-2"><Badge kind={k}>{ROUTE_LABEL[k]}</Badge> <span className="text-xs text-stone-500">{ms.length}</span></div>
              <div className="space-y-2">
                {ms.map((m) => (
                  <div key={m.title} className="rounded-lg border border-stone-200 p-3 text-sm">
                    <div className="font-medium">{m.title}</div>
                    <More label="why"><p className="text-stone-600">{m.evidence}</p>{m.quote && <p className="mt-1 italic text-stone-500">“{m.quote}”</p>}</More>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <h3 className="font-semibold">Value for money — what reviews say about food, price, ambience and service</h3>
        {ch.vfm ? (
          <div className="mt-3 space-y-4">
            <p className="text-sm text-stone-500">Area price benchmark: {ch.vfm.benchmark_label}{ch.vfm.area_price_level ? ` · area price level ${ch.vfm.area_price_level} (from ${ch.vfm.area_price_level_n} competitors)` : ""}</p>
            {ch.vfm.analyses.map((a) => (
              <div key={a.restaurant} className={cx("rounded-xl border p-4", a.restaurant === r.restaurant ? "border-brand-500" : "border-stone-200")}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold">{a.restaurant}</span>
                  <span className="text-sm">Value score <b>{a.vfm.vfm_index}</b>/100</span>
                </div>
                <p className="mt-1 text-sm font-medium text-brand-700">{a.vfm.verdict}</p>
                <p className="text-xs text-stone-500">{a.reviews_analysed} review texts read (of {a.review_count}) · {a.source || "source not given"}</p>
                <div className="mt-2 grid gap-1 sm:grid-cols-2">
                  {Object.entries(a.aspects).filter(([, v]) => v.mentions).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[7rem_1fr_3rem] items-center gap-2 text-xs"><span>{k.replace("_", " / ")}</span><Bar value={v.pos_ratio ?? 0} highlight /><span>{pct(v.pos_ratio)} 👍</span></div>
                  ))}
                </div>
                {a.recommendations.map((x) => (
                  <div key={x.area} className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm">
                    <div className="font-medium">{x.area}: {x.recommendation}</div>
                    <div className="text-xs text-stone-600">{x.evidence}{x.example_quote && <> · “{x.example_quote}”</>}</div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : r.is_sample ? null : <ReviewsForm r={r} reload={reload} />}
      </Card>
    </div>
  );
}

function ReviewsForm({ r, reload }: { r: R; reload: () => void }) {
  const names = [r.restaurant, ...r.rank.scorecard.map((s) => s.restaurant).filter((n) => n !== r.restaurant)];
  const [who, setWho] = useState(r.restaurant);
  const [avg, setAvg] = useState("");
  const [count, setCount] = useState("");
  const [source, setSource] = useState("Google Maps");
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lines = text.split("\n").filter((l) => l.trim()).length;
  async function save() {
    setBusy(true); setError(null);
    try {
      const d = await api.post<{ saved: number; skipped_lines: number }>(`/api/restaurants/${r.slug}/reviews`, { restaurant: who, avg_rating: Number(avg), review_count: count ? Number(count) : null, source, text });
      setMsg(`Saved ${d.saved} reviews${d.skipped_lines ? ` (${d.skipped_lines} lines skipped)` : ""}.`); setText(""); reload();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <div className="mt-3 space-y-3">
      <p className="text-sm text-stone-500">Paste real reviews (copy them from Google Maps). PlateRank never writes or invents reviews. One per line: <code>5 | Great fish, fair price.</code></p>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Reviews for"><select className={inputCls} value={who} onChange={(e) => setWho(e.target.value)}>{names.map((n) => <option key={n}>{n}</option>)}</select></Field>
        <Field label="Average rating"><input className={inputCls} type="number" step="0.1" min={1} max={5} value={avg} onChange={(e) => setAvg(e.target.value)} /></Field>
        <Field label="Total reviews"><input className={inputCls} type="number" min={0} value={count} onChange={(e) => setCount(e.target.value)} /></Field>
        <Field label="Copied from"><input className={inputCls} value={source} onChange={(e) => setSource(e.target.value)} /></Field>
      </div>
      <textarea className={cx(inputCls, "h-40 font-mono text-sm")} value={text} onChange={(e) => setText(e.target.value)} placeholder={"5 | Freshest sushi near Penn Station.\n3 | Good fish but pricey for a quick lunch."} />
      <ErrorNote error={error} />
      {msg && <p className="text-sm text-green-700">{msg}</p>}
      <Button onClick={save} busy={busy} disabled={!lines || !avg || !source.trim()}>Save {lines || ""} reviews</Button>
    </div>
  );
}

// ---------------------------------------------------------------- 4
function Draft({ r, k, title, kind, text: initial, reload, strict, note, file, open, onText }: { r: R; k: string; title: string; kind: "text" | "code" | "json";
  text: string; reload: () => void; strict?: boolean; note?: string; file?: string; open?: { href: string; copy: string; kind: string; tip: string }; onText?: (t: string) => void }) {
  const approved = r.approvals[k];
  const hk = useContext(HK);
  const [text, setText] = useState(approved?.text || initial);
  useEffect(() => { onText?.(text); }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hidden = !!hk && (hk.reminders[k] || 0) > Date.now() / 1000;
  async function remind(undo = false) {
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/remind`, { key: k, undo }); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  async function approve(undo = false) {
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/approve`, { key: k, text, undo }); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  const blocked = !text.trim() || text.includes("OWNER TO CONFIRM") || (kind === "json" && !validJson(text));
  if (hidden && !hk?.showHidden) return null;
  const now = hk?.now?.pieces?.[k];
  return (
    <Card className={hidden ? "opacity-70" : undefined}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{title}</h3>
        {approved ? <Badge kind="LIVE">approved {approved.at}</Badge> : <Badge kind="neutral">draft</Badge>}
      </div>
      {hidden && <p className="mt-1 text-xs text-amber-800">Reminder set - hidden until {new Date((hk!.reminders[k]) * 1000).toLocaleString()}.</p>}
      {hk?.now && (now || !hk.now.ok) && (
        <div className="mt-3 rounded-lg bg-stone-50 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-semibold text-stone-600">
            <span>Now on your website</span>
            {now?.evidence ? <EvidenceBadge ev={now.evidence} /> : hk.now.url && <a className="text-sky-700" href={hk.now.url} target="_blank" rel="noreferrer">{hk.now.url} ↗</a>}
          </div>
          <div className={cx("mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-xs", now?.found ? "text-stone-700" : "text-stone-500 italic")}>
            {now ? now.text : hk.now.note}</div>
        </div>
      )}
      <div className="mt-3 text-xs font-semibold text-stone-600">{hk?.now ? "Proposed" : ""}</div>
      <textarea className={cx(inputCls, "mt-1 h-48 text-sm", kind === "code" && "font-mono", !editing && !approved && "bg-stone-50")} value={text}
        readOnly={!!approved || !editing} onChange={(e) => setText(e.target.value)} />
      {note && <p className="mt-1 text-xs text-stone-500">{note}</p>}
      {text.includes("OWNER TO CONFIRM") && <p className="mt-1 text-xs text-amber-800">Fill in each [OWNER TO CONFIRM] before approving — we don't guess facts.</p>}
      {strict && kind === "json" && text.trim() && !validJson(text) && <p className="mt-1 text-xs text-red-700">This code has a typo now — undo your last edit.</p>}
      <ErrorNote error={error} />
      <div className="mt-3 flex flex-wrap gap-2">
        {approved ? <Button kind="secondary" small busy={busy} onClick={() => approve(true)}>Undo approval</Button>
          : <Button small busy={busy} onClick={() => approve()} disabled={strict && blocked}
              title={strict && blocked ? "Fill in or delete every [OWNER TO CONFIRM] part first" : ""}>✓ Approve</Button>}
        {!approved && <Button small kind="secondary" onClick={() => setEditing(!editing)}>{editing ? "Done editing" : "✎ Make changes"}</Button>}
        {!approved && hk && (hidden ? <Button small kind="ghost" busy={busy} onClick={() => remind(true)}>Bring back</Button>
          : <Button small kind="ghost" busy={busy} onClick={() => remind()}>⏰ Remind me later</Button>)}
        {approved && hk?.pdf_keys.includes(k) && <Button small kind="secondary" busy={busy} onClick={async () => {
          setBusy(true); setError(await downloadUrl(`/api/restaurants/${r.slug}/pdf/${k}`, `${r.slug}-${k}.pdf`)); setBusy(false); }}>⬇ Download PDF</Button>}
        <Button kind="ghost" small onClick={() => copy(text)}>Copy</Button>
        <Button kind="ghost" small disabled={!text.trim()} onClick={() => download(file || `${k}.txt`, text)}>Download</Button>
        {k.startsWith("reddit_") && (approved && open
          ? <Button small title={open.tip} onClick={() => { copy(open.copy); window.open(open.href, "_blank", "noopener"); }}>
              {open.kind === "post" ? "Open on Reddit (text copied)" : "Copy reply + open thread"}</Button>
          : <Button small kind="secondary" disabled title="Approve the draft first - then you post it yourself on Reddit">Open on Reddit</Button>)}
        {k.startsWith("outreach") && (r.mailto?.[k]
          ? <a href={r.mailto[k]} className="inline-flex items-center rounded-lg bg-brand-600 px-2.5 py-1 text-sm font-medium text-white hover:bg-brand-700">✉ Open in email</a>
          : <Button small kind="secondary" disabled title="Approve the draft first - then it opens in your email app for you to send">✉ Open in email</Button>)}
      </div>
      <p className="mt-2 text-xs text-stone-400">Approving only records your decision. PlateRank never publishes or sends anything{k.startsWith("outreach") ? " - “Open in email” fills a new message in your own email app; you choose who gets it and press send." : "."}</p>
    </Card>
  );
}

function Make({ r, reload }: { r: R; reload: () => void }) {
  const m = r.make;
  const hk = m.housekeeping;
  const [showHidden, setShowHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nRem = activeReminders(r);
  async function readSite() {
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/site-now`); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <HK.Provider value={hk ? { reminders: hk.reminders, showHidden, now: hk.site_now, pdf_keys: hk.pdf_keys } : null}>
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Housekeeping: your website now vs what we propose</h3>
            <p className="text-sm text-stone-500">{hk?.site_now ? (hk.site_now.ok ? `Read ${hk.site_now.url} at ${hk.site_now.at}.` : hk.site_now.note)
              : "Read your homepage once (free) to see what it says today next to each draft."}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {nRem > 0 && <span className="text-sm text-amber-800">Reminders ({nRem}) · <button className="cursor-pointer underline" onClick={() => setShowHidden(!showHidden)}>{showHidden ? "hide" : "show"}</button></span>}
            {!r.is_sample && <Button small kind="secondary" busy={busy} onClick={readSite}>{hk?.site_now ? "Read my website again" : "Read my current website"}</Button>}
          </div>
        </div>
        <ErrorNote error={error} />
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        {m.drafts.map((d) => <Draft key={d.key} r={r} k={d.key} title={d.title} kind={d.kind} text={d.text} reload={reload} />)}
      </div>
      {!r.is_sample && <AisoSection r={r} a={hk?.aiso} reload={reload} />}
      <ContentPackSection r={r} reload={reload} />
      {hk && <SocialCard s={hk.social} />}
    </div>
    </HK.Provider>
  );
}

const STRENGTH_KIND = { Strong: "LIVE", Mixed: "DEMO", Weak: "neutral" } as const;

/** AI-readability: PlateRank reads the real site (free), then code drafts each fix with what it found, why, and how strong the evidence is. */
function AisoSection({ r, a, reload }: { r: R; a?: Aiso; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function research() {
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/aiso/research`); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">AI-readability: what your website tells AI</h3>
            <p className="text-sm text-stone-500">{a?.researched ? (a.ok ? `Read ${a.url}, its robots.txt and llms.txt at ${a.at}.` : `Couldn't read ${a.url}: ${a.error}`)
              : "PlateRank reads your real homepage, robots.txt and llms.txt (free, no AI), then drafts each fix from what it finds."}</p>
          </div>
          <Button small kind="secondary" busy={busy} onClick={research}>{a?.researched ? "Research again" : "Research my website"}</Button>
        </div>
        {busy && <SlowBar label="Reading your homepage, robots.txt and llms.txt… (5–20 seconds)" />}
        <ErrorNote error={error} />
        {a?.researched && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{a.header}</p>}
        {a?.researched && (a.competitors || []).length > 0 && <More label="Competitor websites">
          <ul className="space-y-1 text-sm">{(a.competitors || []).map((c) => (
            <li key={c.name}><span className="font-medium">{c.name}</span>: {c.ok ? <>title “{c.title || "none"}” · schema: {c.schema.length ? [...new Set(c.schema)].join(", ") : "none"} · llms.txt: {c.llms_txt ? "yes" : "no"}{c.url && <> · <a className="text-sky-700" href={c.url} target="_blank" rel="noreferrer">site ↗</a></>}</>
              : <span className="text-stone-500">{c.error}</span>}</li>))}</ul>
        </More>}
      </Card>
      {a?.researched && <div className="grid gap-5 lg:grid-cols-2">{a.items.map((it) => (
        <div key={it.key} className="space-y-2">
          <div className="rounded-lg border border-stone-200 bg-white p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{it.title}</span>
              <Badge kind={STRENGTH_KIND[it.strength]}>Evidence: {it.strength}</Badge></div>
            <div className="mt-2 text-xs font-semibold text-stone-500">Now{it.before_url && <> · <a className="font-normal text-sky-700" href={it.before_url} target="_blank" rel="noreferrer">source ↗</a></>}</div>
            <div className="whitespace-pre-wrap text-stone-700">{it.before.slice(0, 600)}</div>
            <div className="mt-2 text-xs font-semibold text-stone-500">Why</div>
            <div className="text-stone-700">{it.why}</div>
            {it.research.map((n) => <div key={n.url + n.text} className="mt-1 text-xs text-stone-500">Research: {n.text} <a className="text-sky-700" href={n.url} target="_blank" rel="noreferrer">source ↗</a></div>)}
            {it.problems && it.problems.length > 0 && <div className="mt-2 text-xs text-red-700">Check failed: {it.problems.join(" ")}</div>}
          </div>
          <Draft r={r} k={it.key} title={`Proposed: ${it.file}`} kind={it.kind} text={it.text} reload={reload} file={it.file} />
        </div>))}
      </div>}
    </div>
  );
}

// ---------------------------------------------------------------- 5
function Improve({ r }: { r: R }) {
  const h = r.improve.history;
  if (r.is_sample) return <Card>The sample has no history. Run a real restaurant twice to see the trend here.</Card>;
  const W = 640, H = 200, pad = 30;
  const pts = h.map((x, i) => [pad + (h.length > 1 ? (i / (h.length - 1)) * (W - 2 * pad) : (W - 2 * pad) / 2), H - pad - x.mention_rate * (H - 2 * pad)]);
  return (
    <div className="space-y-5">
      <CompareCard r={r} />
      <PartialCard r={r} />
      <Card>
        <h3 className="font-semibold">How often AI names you, check by check</h3>
        {h.length === 0 ? <p className="mt-2 text-sm text-stone-500">No checks saved yet.</p> : (
          <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full">
            {[0, 0.5, 1].map((y) => <g key={y}><line x1={pad} x2={W - pad} y1={H - pad - y * (H - 2 * pad)} y2={H - pad - y * (H - 2 * pad)} stroke="#e7e5e4" />
              <text x={4} y={H - pad - y * (H - 2 * pad) + 4} fontSize="11" fill="#78716c">{y * 100}%</text></g>)}
            <polyline fill="none" stroke="#ea580c" strokeWidth="3" points={pts.map((p) => p.join(",")).join(" ")} />
            {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="5" fill="#ea580c" />)}
          </svg>
        )}
        <p className="mt-2 text-xs text-stone-500">{r.improve.note}</p>
        <div className="mt-3"><Button onClick={() => go(`/r/${r.slug}/run/fresh`)}>Re-check now (fresh answers)</Button></div>
      </Card>
    </div>
  );
}

const validJson = (t: string) => { try { JSON.parse(t); return true; } catch { return false; } };

const PACK_FILE: Record<string, string> = {
  pack_restaurant_schema: "schema-restaurant.json", pack_faq_schema: "schema-faq.json", pack_menu_schema: "schema-menu.json",
  pack_about: "about.txt", pack_menu_copy: "menu-descriptions.txt", pack_landing: "landing-page.html",
};

/** Website content pack: schemas built from facts + Claude-written wording (cached), each approved separately. */
function ContentPackSection({ r, reload }: { r: R; reload: () => void }) {
  const pack = r.make.pack;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zipBusy, setZipBusy] = useState(false);
  const generated = pack.generated;

  async function write(regenerate: boolean) {
    if (regenerate && !window.confirm("This replaces the current About, menu and landing-page text with a new version written by Claude. Continue?")) return;
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/content-pack`, { regenerate }); reload(); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  }

  async function downloadZip() {
    setZipBusy(true); setError(null);
    try {
      const res = await fetch(`/api/restaurants/${r.slug}/website-pack.zip`);
      if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail || "Couldn't build the download.");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob());
      a.download = `${r.slug}-website-pack.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setError((e as Error).message); }
    setZipBusy(false);
  }

  const approvedCount = pack.pieces.filter((p) => r.approvals[p.key]).length;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold">Website content pack</h3>
            <p className="text-sm text-stone-500">Ready-to-paste schema, About text, menu copy and a local landing page — written only from your saved facts.
              Anything we don't know shows as [OWNER TO CONFIRM].</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!pack.is_sample && (generated
              ? <Button kind="secondary" small busy={busy} disabled={!pack.can_generate} onClick={() => write(true)}>Regenerate the text</Button>
              : <Button small busy={busy} disabled={!pack.can_generate} onClick={() => write(false)}>Write the text</Button>)}
            <Button small kind="secondary" busy={zipBusy} disabled={!approvedCount} onClick={downloadZip}
              title={approvedCount ? "" : "Approve at least one piece first"}>Download website pack ({approvedCount} approved)</Button>
          </div>
        </div>
        {busy && <SlowBar label="Claude is writing the About text, menu copy and landing page from your facts… (20–60 seconds)" />}
        {pack.is_sample && <p className="mt-2 text-sm text-stone-500">The sample restaurant only shows the schemas — the written text is for your own restaurant.</p>}
        {!pack.is_sample && !pack.can_generate && <p className="mt-2 text-sm text-stone-500">Add a Claude key to <code>.env</code> to write the text. The schemas below work without it.</p>}
        {generated && <p className="mt-2 text-xs text-stone-500">Text written {generated.at}. It's saved — reloading doesn't rewrite it.</p>}
        {pack.facts_changed && <p className="mt-2 rounded bg-amber-50 p-2 text-sm text-amber-900">Your facts changed since this text was written. Regenerate to use the new facts.</p>}
        <ErrorNote error={error} />
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        {pack.pieces.map((p: PackPiece) => (
          <Draft key={`${p.key}-${generated?.at || "none"}`} r={r} k={p.key} title={p.title} kind={p.kind} text={p.text} reload={reload} strict
            file={PACK_FILE[p.key]} note={[p.note, p.flags.length ? `Marked for you to confirm (not in your facts): ${p.flags.join(", ")}` : ""].filter(Boolean).join(" ")} />
        ))}
      </div>
    </div>
  );
}

const pts = (d: number | null | undefined) => (d == null ? "—" : `${d >= 0 ? "+" : ""}${Math.round(d * 100)} pts`);

/** First vs latest check - only runs with the same questions, platforms and web-search setting. */
function CompareCard({ r }: { r: R }) {
  const m = r.improve.compare;
  if (!m.comparable || !m.first || !m.latest || !m.change) return (
    <Card><h3 className="font-semibold">Before and after</h3><p className="mt-1 text-sm text-stone-600">{m.reason}</p>
      <p className="mt-1 text-xs text-stone-500">{m.label}</p></Card>
  );
  const { first, latest, change } = m;
  const rows: [string, string, string, string][] = [
    ["AI names you in", pct(first.mention_rate), pct(latest.mention_rate), pts(change.mention_rate)],
    ["Your position when named", first.avg_rank?.toFixed(1) ?? "—", latest.avg_rank?.toFixed(1) ?? "—",
      change.avg_rank == null ? "—" : `${change.avg_rank > 0 ? "+" : ""}${change.avg_rank.toFixed(1)} (lower is better)`],
    ["Share of voice", pct(first.share_of_voice), pct(latest.share_of_voice), pts(change.share_of_voice)],
  ];
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">First check vs latest check</h3>
        <Badge kind="neutral">{m.label}</Badge>
      </div>
      <p className="mt-1 text-xs text-stone-500">Same {first.answers ?? ""} questions on {m.platforms?.join(" + ")}.
        {m.skipped ? ` ${m.skipped} other check(s) used different questions or platforms and are left out.` : ""}</p>
      <table className="mt-3 w-full text-sm">
        <thead><tr className="text-left text-stone-500"><th className="py-1 font-medium"></th><th className="font-medium">First · {first.when}</th>
          <th className="font-medium">Latest · {latest.when}</th><th className="font-medium">Change</th></tr></thead>
        <tbody>{rows.map(([label, a, b, d]) => (
          <tr key={label} className="border-t border-stone-100"><td className="py-1.5">{label}</td><td>{a}</td><td className="font-semibold">{b}</td><td>{d}</td></tr>
        ))}</tbody>
      </table>
      <More label={`Per question type (${m.by_category?.length ?? 0})`}>
        <table className="w-full text-sm">
          <tbody>{(m.by_category || []).map((c) => (
            <tr key={c.category} className="border-t border-stone-100">
              <td className="py-1">{c.category}</td><td>{pct(c.first)}</td><td>→</td><td className="font-semibold">{pct(c.latest)}</td>
              <td className="text-stone-500">{c.first != null && c.latest != null ? pts(c.latest - c.first) : "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      </More>
    </Card>
  );
}

/** Everything taken from the web for this restaurant, with how it was checked (the evidence ledger). */
function SourcesPanel({ slug }: { slug: string }) {
  const [d, setD] = useState<{ records: Evidence[]; counts: Record<string, number> } | null>(null);
  useEffect(() => { api.get<typeof d>(`/api/restaurants/${slug}/evidence`).then(setD).catch(() => setD(null)); }, [slug]);
  if (!d || !d.records.length) return null;
  const c = d.counts;
  return (
    <Card>
      <More label={`Sources — ${c.verified} verified · ${c.unverified} unverified · ${c.rejected} rejected`}>
        <p className="mb-2 text-xs text-stone-500">Every fact taken from the web, checked by fetching the cited page ourselves.
          Only ✓ verified ones are used in scores and drafts. Rejected = the page loaded but didn't say it - never shown as a fact.</p>
        <table className="w-full text-sm">
          <tbody>{d.records.map((e) => (
            <tr key={e.id} className={cx("border-t border-stone-100 align-top", e.status === "rejected" && "text-stone-400")}>
              <td className="py-1 pr-2 text-xs text-stone-500">{e.subject}</td>
              <td className="py-1 pr-2">{e.status === "rejected" ? <s>{e.text}</s> : e.text}</td>
              <td className="py-1 pr-2">{e.status === "rejected" ? <span className="text-xs">✕ rejected</span> : <EvidenceBadge ev={e} />}</td>
              <td className="py-1 text-xs text-stone-400">{e.check_note}</td>
            </tr>
          ))}</tbody>
        </table>
      </More>
    </Card>
  );
}

const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

function QuoteRow({ q }: { q: AiQuote }) {
  return (
    <li className="border-t border-stone-100 py-2 text-sm">
      <div>“{q.quote}”</div>
      <div className="mt-0.5 text-xs text-stone-500">asked: {q.question}{q.platform ? ` · ${q.platform}` : ""}
        {q.sources.map((u) => <a key={u} className="ml-2 text-sky-700 hover:underline" href={u} target="_blank" rel="noreferrer">{host(u)} ↗</a>)}</div>
    </li>
  );
}

/** What the AI assistants said about the restaurant, from the saved answers (no new AI calls). */
function AiSaysCard({ r }: { r: R }) {
  const a = r.why.ai_says;
  if (!a) return null;
  const total = a.counts.praised + a.counts.criticised + a.counts.described;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">What AI says about you</h3>
        <Badge kind="neutral">{a.label}</Badge>
      </div>
      {total === 0 ? <p className="mt-2 text-sm text-stone-500">No AI answer named you in this check, so there's nothing to quote yet.</p> : <>
        <p className="mt-1 text-sm text-stone-500">Praised in {a.counts.praised} · criticised in {a.counts.criticised} · described in {a.counts.described} sentences.</p>
        <ul className="mt-2">{a.headline.map((q, i) => <QuoteRow key={i} q={q} />)}</ul>
        {(["praised", "criticised", "described"] as const).map((k) => a.groups[k].length > 0 && (
          <More key={k} label={`${k === "praised" ? "Praised for" : k === "criticised" ? "Criticised for" : "Described as"} (${a.groups[k].length})`}>
            <ul>{a.groups[k].map((q, i) => <QuoteRow key={i} q={q} />)}</ul>
          </More>
        ))}
      </>}
    </Card>
  );
}

/** Public reviews/forum quotes (one Claude web search), checked one by one, then Business Value from verified ones only. */
function PeopleSaySection({ slug, part = "both" }: { slug: string; part?: "quotes" | "value" | "both" }) {
  const [d, setD] = useState<PeopleSay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.get<PeopleSay>(`/api/restaurants/${slug}/people-say`).then(setD).catch((e) => setError(e.message)), [slug]);
  useEffect(() => { load(); }, [load]);
  async function search() {
    if (d?.saved && !window.confirm("Search the web again? This replaces the saved quotes with a fresh search by Claude.")) return;
    setBusy(true); setError(null);
    try { setD(await api.post<PeopleSay>(`/api/restaurants/${slug}/people-say/search`)); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  if (!d) return null;
  const items = d.saved?.items || [];
  const shown = items.filter((x) => x.evidence.status === "verified"), grey = items.filter((x) => x.evidence.status !== "verified");
  const bv = d.business_value;
  return (
    <div className="space-y-5">
      {part !== "value" && <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">What people say right now</h3>
            <p className="text-sm text-stone-500">Short quotes from public review and forum pages. Each one is checked on its page before it counts.</p>
          </div>
          <Button small kind={d.saved ? "secondary" : "primary"} busy={busy} disabled={!d.can_search}
            title={d.can_search ? "" : "Needs a Claude key in .env"} onClick={search}>{d.saved ? "Search again" : "Find what people say"}</Button>
        </div>
        {busy && <SlowBar label="Claude is searching review and forum pages, then we check every quote on its page… (20–60 seconds)" />}
        <ErrorNote error={error} />
        {d.saved && <>
          <p className="mt-2 text-xs text-stone-500">Searched {d.saved.at}: {shown.length} verified · {grey.length} couldn't be checked · {d.saved.rejected} rejected (not found on the cited page)
            {d.saved.dropped_no_url ? ` · ${d.saved.dropped_no_url} dropped (no link or too long to be word-for-word)` : ""}.</p>
          <ul className="mt-2">{shown.map((x, i) => (
            <li key={i} className="border-t border-stone-100 py-2 text-sm">
              <div>“{x.quote}” {x.rating != null && <span className="text-stone-500">· {String(x.rating)}★</span>} {x.date && <span className="text-stone-500">· {x.date}</span>}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-stone-500">{x.site || host(x.source_url)} <EvidenceBadge ev={x.evidence} /></div>
            </li>))}</ul>
          {grey.length > 0 && <More label={`Not checked (${grey.length}) - not used`}>
            <ul>{grey.map((x, i) => <li key={i} className="border-t border-stone-100 py-2 text-sm text-stone-400">“{x.quote}” <EvidenceBadge ev={x.evidence} /></li>)}</ul>
          </More>}
        </>}
      </Card>}
      {part !== "quotes" && <Card>
        <h3 className="font-semibold">Business value - what reviews say to fix</h3>
        {!bv.ready ? <p className="mt-1 text-sm text-stone-500">{bv.reason}</p> : <>
          <p className="mt-1 font-medium">{bv.sentiment}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(bv.aspects || {}).map(([k, v]) => (
              <div key={k} className={cx("rounded-lg p-2 text-sm", v.negative ? "bg-amber-50" : v.mentions ? "bg-green-50" : "bg-stone-50")}>
                <div className="font-medium">{k.replace("_", " / ")}</div><div className="text-xs text-stone-600">{v.status}</div>
                <div className="text-xs text-stone-400">{v.positive} 👍 · {v.negative} 👎</div>
              </div>))}
          </div>
          <h4 className="mt-4 text-sm font-semibold">Top actions</h4>
          {(bv.actions || []).length === 0 ? <p className="text-sm text-stone-500">No complaints and nothing missing - doing well.</p> :
            <ol className="mt-1 space-y-2">{(bv.actions || []).map((x, i) => (
              <li key={i} className="rounded-lg bg-stone-50 p-2 text-sm">
                <div><Badge kind={x.kind === "gap" ? "neutral" : "vfm"}>{x.kind === "gap" ? `${x.label}: ${x.category}` : x.category}</Badge> <span className="font-medium">{x.action}</span></div>
                <div className="mt-0.5 text-xs text-stone-500">{x.evidence}</div>
                {x.quote && <div className="mt-0.5 text-xs">“{x.quote}” {x.source_url && <a className="text-sky-700" href={x.source_url} target="_blank" rel="noreferrer">{host(x.source_url)} ↗</a>}</div>}
              </li>))}</ol>}
          <p className="mt-2 text-xs text-stone-400">Only checked quotes and reviews you pasted are counted.</p>
        </>}
        {part === "value" && !d.saved && d.can_search && <div className="mt-3"><Button small busy={busy} onClick={search}>Find what people say</Button></div>}
        {part === "value" && busy && <SlowBar label="Searching review and forum pages, then checking every quote… (20–60 seconds)" />}
      </Card>}
    </div>
  );
}

type HKState = { reminders: Record<string, number>; showHidden: boolean; now: Housekeeping["site_now"]; pdf_keys: string[] } | null;
const HK = createContext<HKState>(null);
const activeReminders = (r: R) => Object.values(r.make?.housekeeping?.reminders || {}).filter((t) => t > Date.now() / 1000).length;

async function downloadUrl(url: string, name: string): Promise<string | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return (await res.json().catch(() => ({}))).detail || "Couldn't build the download.";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
    return null;
  } catch { return "Can't reach PlateRank. Is the terminal running `python run.py` still open?"; }
}

/** Hashtags + keywords from the profile and the question types being lost, plus a consistency checklist. */
function SocialCard({ s }: { s: Housekeeping["social"] }) {
  return (
    <Card>
      <h3 className="font-semibold">Social media hygiene</h3>
      <p className="text-sm text-stone-500">{s.note}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">{s.hashtags.map((t) => <span key={t} className="rounded-full bg-sky-50 px-2 py-0.5 text-sm text-sky-800">{t}</span>)}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button small kind="ghost" onClick={() => copy(s.hashtags.join(" "))}>Copy hashtags</Button>
        <Button small kind="ghost" onClick={() => copy(s.keywords.join("\n"))}>Copy search keywords</Button>
      </div>
      <p className="mt-2 text-xs text-stone-500">Search keywords to use in bios, captions and video titles: {s.keywords.join(" · ")}</p>
      <ul className="mt-3 space-y-1 text-sm">{s.checklist.map((c) => <li key={c}>☐ {c}</li>)}</ul>
    </Card>
  );
}

/** Data farming: Reddit agent. Every subreddit, rule and thread is checked; the owner posts, never PlateRank. */
function FarmTab({ r, reload }: { r: R; reload: () => void }) {
  const [d, setD] = useState<Farm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posted, setPosted] = useState<Record<string, string>>({});
  const [useEdit, setUseEdit] = useState<Record<string, string>>({});
  const [onScreen, setOnScreen] = useState<Record<string, string>>({});
  const load = useCallback(() => api.get<Farm>(`/api/restaurants/${r.slug}/reddit`).then(setD).catch((e) => setError(e.message)), [r.slug]);
  useEffect(() => { load(); }, [load]);
  const reloadAll = () => { reload(); load(); };
  async function find() {
    if (d?.at && !window.confirm("Search Reddit again? This replaces the saved subreddits, threads and drafts (posted links are kept).")) return;
    setBusy(true); setError(null);
    try { setD(await api.post<Farm>(`/api/restaurants/${r.slug}/reddit/find`)); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  async function markPosted(key: string) {
    setError(null);
    try { setD(await api.post<Farm>(`/api/restaurants/${r.slug}/reddit/posted`, { key, url: posted[key] || "" })); } catch (e) { setError((e as Error).message); }
  }
  const hk = r.make?.housekeeping;
  if (!d) return <ErrorNote error={error} />;
  return (
    <HK.Provider value={hk ? { reminders: hk.reminders, showHidden: false, now: null, pdf_keys: [] } : null}>
    <div className="space-y-5">
      <div className="rounded-lg border border-brand-500 bg-brand-50 px-4 py-3 text-sm font-medium text-brand-700">{d.note}</div>
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Reddit: where locals ask where to eat</h3>
            <p className="text-sm text-stone-500">Finds your city and neighbourhood subreddits (with their rules) and live threads asking for what you serve,
              then drafts replies in your voice. Only ✓ verified subreddits, rules and threads are used.</p>
          </div>
          <Button small busy={busy} disabled={!d.can_search} title={d.can_search ? "" : "Needs a Claude key in .env"} onClick={find}>
            {d.at ? "Search again" : "Find subreddits & conversations"}</Button>
        </div>
        {busy && <SlowBar label="Claude is finding subreddits, their rules and recent threads, then we check each one… (30–90 seconds)" />}
        <ErrorNote error={error} />
        {d.at && d.counts && <p className="mt-2 text-xs text-stone-500">Searched {d.at}: {d.counts.subreddits_verified} of {d.counts.subreddits_found} subreddits
          and {d.counts.threads_verified} of {d.counts.threads_found} threads verified - the rest couldn't be checked and aren't used.</p>}
        {d.cited && <p className={cx("mt-2 rounded p-2 text-sm", d.cited.status === "cited" ? "bg-green-50 text-green-800" : "bg-stone-50 text-stone-600")}>{d.cited.note}</p>}
      </Card>
      <OwnerSubCard slug={r.slug} onDone={(f) => setD(f)} />
      {(d.subreddits || []).length > 0 && (
        <Card>
          <h3 className="font-semibold">Subreddits and their rules</h3>
          <ul className="mt-2 space-y-2 text-sm">{(d.subreddits || []).map((s) => (
            <li key={s.name} className="border-t border-stone-100 pt-2">
              <div className="flex flex-wrap items-center gap-2"><a className="font-medium text-sky-700" href={s.url} target="_blank" rel="noreferrer">r/{s.name}</a>
                <EvidenceBadge ev={s.evidence} />
                <Badge kind={s.self_promotion === "allowed" ? "LIVE" : "neutral"}>self-promotion: {s.self_promotion}</Badge>
                {s.weekly_thread && <Badge kind="neutral">weekly thread: {s.weekly_thread}</Badge>}
                {s.flair_required && <Badge kind="neutral">flair required</Badge>}</div>
              {s.rule_quote ? <div className="mt-1 text-xs text-stone-600">Rule: “{s.rule_quote}” <EvidenceBadge ev={s.rule_evidence} /></div>
                : <div className="mt-1 text-xs text-stone-400">Rule not verified - treat as “no self-promotion”{s.rules_url && <> · <a className="text-sky-700" href={s.rules_url} target="_blank" rel="noreferrer">read the rules ↗</a></>}</div>}
            </li>))}</ul>
        </Card>
      )}
      {(d.drafts || []).length > 0 ? (
        <div className="grid gap-5 lg:grid-cols-2">{(d.drafts || []).map((x) => (
          <div key={x.key} className="space-y-2">
            {x.type === "reply" && x.thread_url && <p className="text-xs text-stone-500">Thread: <a className="text-sky-700" href={x.thread_url} target="_blank" rel="noreferrer">{x.thread_title} ↗</a></p>}
            {x.type === "post" && <p className="text-xs text-stone-500">Title: {x.post_title}{x.flair_required ? " · pick a flair when posting" : ""}</p>}
            <AgentReviewPanel slug={r.slug} draftKey={x.key} currentText={onScreen[x.key] ?? (useEdit[x.key] || r.approvals[x.key]?.text || x.text)}
              onUseEdit={(t) => setUseEdit({ ...useEdit, [x.key]: t })} />
            <Draft key={`${x.key}-${useEdit[x.key] ? "edit" : "orig"}`} r={r} k={x.key} title={x.title} kind="text" text={useEdit[x.key] || x.text} reload={reloadAll} strict
              onText={(t) => setOnScreen((s) => (s[x.key] === t ? s : { ...s, [x.key]: t }))}
              note={[x.owner_note || "", x.rule ? `Follows r/${x.subreddit}'s rule: “${x.rule}”` : "", x.flags.length ? `Marked for you to confirm (not in your facts): ${x.flags.join(", ")}` : ""].filter(Boolean).join(" ")}
              open={d.links[x.key] ? { ...d.links[x.key], tip: d.post_note } : undefined} />
            {r.approvals[x.key] && (d.posted?.[x.key]
              ? <p className="text-xs text-green-700">Posted {d.posted[x.key].at}: <a className="text-sky-700" href={d.posted[x.key].url} target="_blank" rel="noreferrer">{d.posted[x.key].url}</a></p>
              : <div className="flex gap-2"><input className={cx(inputCls, "text-sm")} placeholder="After posting, paste the link to your post here"
                  value={posted[x.key] || ""} onChange={(e) => setPosted({ ...posted, [x.key]: e.target.value })} />
                  <Button small kind="secondary" disabled={!posted[x.key]} onClick={() => markPosted(x.key)}>Mark as posted</Button></div>)}
          </div>))}
        </div>
      ) : d.at && <Card><p className="text-sm text-stone-500">No verified threads or open subreddits to draft for yet. Try again later - threads come and go.</p></Card>}
      <p className="text-xs text-stone-400">{d.post_note} PlateRank never posts by itself.</p>
    </div>
    </HK.Provider>
  );
}

const initials = (n: string) => n.replace(/^@/, "").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");

/** Social media: REAL creators found by web search, each checked in the evidence ledger. Nothing estimated. */
function SocialTab({ r, reload }: { r: R; reload: () => void }) {
  const [d, setD] = useState<CreatorsView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const load = useCallback(() => api.get<CreatorsView>(`/api/restaurants/${r.slug}/creators`).then(setD).catch((e) => setError(e.message)), [r.slug]);
  useEffect(() => { load(); }, [load]);
  async function find() {
    if (d?.at && !window.confirm("Search for creators again? This replaces the list (saved creators stay saved).")) return;
    setBusy("find"); setError(null);
    try { setD(await api.post<CreatorsView>(`/api/restaurants/${r.slug}/creators/find`)); } catch (e) { setError((e as Error).message); }
    setBusy(null);
  }
  async function save() {
    setBusy("save"); setError(null);
    try { setD(await api.post<CreatorsView>(`/api/restaurants/${r.slug}/creators/save`, { handles: Object.keys(ticked).filter((k) => ticked[k]) })); setTicked({}); }
    catch (e) { setError((e as Error).message); }
    setBusy(null);
  }
  const hk = r.make?.housekeeping;
  if (!d) return <ErrorNote error={error} />;
  const nTicked = Object.values(ticked).filter(Boolean).length;
  return (
    <HK.Provider value={hk ? { reminders: hk.reminders, showHidden: false, now: null, pdf_keys: [] } : null}>
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Local food creators</h3>
            <p className="text-sm text-stone-500">Real creators who cover your cuisine and area - YouTube first (AI assistants read and cite it), then TikTok, Instagram and blogs.
              Follower counts appear only when we could check them on a page; otherwise “unknown”.</p>
          </div>
          <Button small busy={busy === "find"} disabled={!d.can_search} title={d.can_search ? "" : "Needs a Claude key in .env"} onClick={find}>
            {d.at ? "Search again" : "Find creators"}</Button>
        </div>
        {busy === "find" && <SlowBar label="Claude is searching for local food creators, then we check each profile link… (20–60 seconds)" />}
        <ErrorNote error={error} />
        {d.at && <p className="mt-2 text-xs text-stone-500">Searched {d.at}: {d.creators.filter((c) => c.verified).length} verified ·
          {" "}{d.creators.filter((c) => !c.verified).length} couldn't be checked · {d.rejected} rejected · {d.dropped_no_url} dropped (no profile link).
          {d.lost_categories.length ? ` Matched against the question types you're losing: ${d.lost_categories.join(", ")}.` : " Run a check to match them against the question types you're losing."}</p>}
      </Card>
      {d.creators.length > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="text-left text-xs text-stone-500"><th></th><th className="py-1">Creator</th><th>Platform</th><th>Followers</th><th>Local to</th><th>Niches</th><th>Match</th></tr></thead>
              <tbody>{d.creators.map((c) => (
                <tr key={c.handle} className={cx("border-t border-stone-100 align-top", !c.verified && "opacity-60")}>
                  <td className="py-2 pr-2"><input type="checkbox" className="h-4 w-4 accent-brand-600" disabled={!c.verified || c.saved}
                    checked={c.saved || !!ticked[c.handle]} onChange={(e) => setTicked({ ...ticked, [c.handle]: e.target.checked })}
                    title={c.verified ? (c.saved ? "Saved" : "Tick to save") : "Not checked - open the link first"} /></td>
                  <td className="py-2 pr-2"><div className="flex items-center gap-2">
                    {c.photo_url ? <img src={c.photo_url} alt="" className="h-8 w-8 rounded-full object-cover" />
                      : <span className="flex h-8 w-8 items-center justify-center rounded-full bg-stone-200 text-xs font-semibold text-stone-600">{initials(c.name)}</span>}
                    <div><a className="font-medium text-sky-700 hover:underline" href={c.url} target="_blank" rel="noreferrer">{c.name}</a>
                      <div className="text-xs text-stone-500">{c.handle !== c.name ? c.handle : ""}</div><EvidenceBadge ev={c.evidence} /></div></div></td>
                  <td className="py-2 pr-2">{c.platform}</td>
                  <td className="py-2 pr-2">{c.followers != null ? <>{c.followers.toLocaleString()} <EvidenceBadge ev={c.followers_evidence} /></> : <span className="text-stone-400">unknown</span>}</td>
                  <td className="py-2 pr-2">{c.local_to || <span className="text-stone-400">unknown</span>}</td>
                  <td className="py-2 pr-2 text-xs">{c.niches.join(", ")}</td>
                  <td className="py-2 font-semibold" title={c.why}>{c.score_low != null ? `${c.score_low}-${c.score_high}` : c.relevance_score}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Button small busy={busy === "save"} disabled={!nTicked} onClick={save}>Save ticked creators ({nTicked})</Button>
            <span className="text-xs text-stone-500">Saved to data/live/creators_live.json with their verified status and link. A score range means followers or engagement are unknown.</span>
          </div>
        </Card>
      )}
      {r.make?.creators?.length > 0 && (
        <More label={`Your saved creators, matched to the questions you're losing (${r.make.creators.length})`}>
          <p className="mb-2 text-xs text-stone-500">{r.make.creators_note}</p>
          {r.make.creators.map((c) => (
            <div key={c.handle} className="mb-3 space-y-1">
              <div className="text-sm"><b>{c.handle}</b> <span className="text-stone-500">{c.platform} · {c.followers != null ? `${c.followers.toLocaleString()} followers` : "followers unknown"} · match {c.relevance_score}</span></div>
              <p className="text-sm"><b>Video idea:</b> “{c.brief.concept_title}” — {c.brief.hook}</p>
              <Draft r={r} k={`outreach_${c.handle.replace(/^@/, "")}`} title={`Message to ${c.handle}`} kind="text" text={c.outreach} reload={reload} />
            </div>))}
        </More>
      )}
      {d.creators.filter((c) => c.verified).map((c) => (
        <More key={c.handle} label={`${c.name}: strategy, brief and message`}>
          <div className="space-y-2">
            <p className="text-sm"><b>Video idea:</b> “{c.brief.concept_title}” — {c.brief.hook}</p>
            <Button small kind="secondary" onClick={() => download(`${c.handle.replace(/^@/, "")}-strategy-and-brief.txt`, c.brief_text)}>⬇ Strategy & brief</Button>
            <Draft r={r} k={c.outreach_key} title={`Message to ${c.name}`} kind="text" text={c.outreach} reload={() => { reload(); load(); }} />
          </div>
        </More>
      ))}
    </div>
    </HK.Provider>
  );
}

function Headline({ text }: { text?: string }) {
  return text ? <p className="text-lg font-semibold text-stone-800">{text}</p> : null;
}

/** 1 Where you rank: scorecard, what AI says, what people say, sources - details under "Show more". */
function RankTab({ r, reload }: { r: R; reload: () => void }) {
  return (
    <div className="space-y-5">
      <Rank r={r} />
      <AiSaysCard r={r} />
      <PeopleSaySection slug={r.slug} part="quotes" />
      <More label="Show more: why competitors are named instead"><Why r={r} reload={reload} /></More>
      <SourcesPanel slug={r.slug} />
    </div>
  );
}

/** 4 Business value: what checked reviews say to fix; the full value-for-money detail under "Show more". */
function BusinessTab({ r, reload }: { r: R; reload: () => void }) {
  return (
    <div className="space-y-5">
      <PeopleSaySection slug={r.slug} part="value" />
      {r.change && <More label="Show more: value for money and every change by tool"><Change r={r} reload={reload} /></More>}
      {!r.change && !r.is_sample && <More label="Show more: paste reviews you have"><ReviewsForm r={r} reload={reload} /></More>}
    </div>
  );
}

const TAB_NAME: Record<string, string> = Object.fromEntries(TABS.map(([k, , label]) => [k, label]));

/** 6 Your to-do list: one ranked list from every tab (ranking is plain code), done ticks saved. */
function TodoTab({ r, reload }: { r: R; reload: () => void }) {
  const [error, setError] = useState<string | null>(null);
  async function tick(id: string, done: boolean) {
    setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/todo`, { id, done }); reload(); } catch (e) { setError((e as Error).message); }
  }
  return (
    <Card>
      <ErrorNote error={error} />
      {r.todo.length === 0 ? <p className="text-sm text-stone-500">Nothing yet - open the other tabs (or run a check) and the actions will appear here.</p> : (
        <ol className="space-y-2">{r.todo.map((t, i) => (
          <li key={t.id} className={cx("flex items-start gap-3 rounded-lg border border-stone-200 p-3", t.done && "opacity-60")}>
            <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={t.done} onChange={(e) => tick(t.id, e.target.checked)} title="Mark as done" />
            <div className="min-w-0 flex-1">
              <div className={cx("font-medium", t.done && "line-through")}>{i + 1}. {t.title}</div>
              <div className="text-sm text-stone-500">{t.why}</div>
              <div className="mt-1 flex flex-wrap gap-3 text-xs">
                <a className="text-brand-700 underline" href={`#/r/${r.slug}/results/${t.tab}`}>Fix it in {TAB_NAME[t.tab] || t.tab} →</a>
                {t.link && <a className="text-sky-700" href={t.link} target="_blank" rel="noreferrer">evidence ↗</a>}
              </div>
            </div>
          </li>))}
        </ol>
      )}
      <p className="mt-3 text-xs text-stone-400">Ranked by the evidence: competitor gaps first, then what reviews say, then your website, creators and Reddit.</p>
    </Card>
  );
}

/** A subreddit the owner knows -> 2 owner-voiced post drafts written from the profile (no AI). */
function OwnerSubCard({ slug, onDone }: { slug: string; onDone: (f: Farm) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function add() {
    setBusy(true); setError(null);
    try { onDone(await api.post<Farm>(`/api/restaurants/${slug}/reddit/owner-sub`, { subreddit: name })); setName(""); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <Card>
      <h3 className="font-semibold">Add a subreddit you know</h3>
      <p className="text-sm text-stone-500">We draft 2 posts in your voice from your saved facts. You check that subreddit's rules and post them yourself.</p>
      <div className="mt-2 flex gap-2">
        <input className={inputCls} placeholder="e.g. sandiego" value={name} onChange={(e) => setName(e.target.value)} />
        <Button small busy={busy} disabled={!name.trim()} onClick={add}>Draft 2 posts</Button>
      </div>
      <ErrorNote error={error} />
    </Card>
  );
}

/** Re-check only some question types (fresh answers), compared per type with the first full check. */
function PartialCard({ r }: { r: R }) {
  const m = r.improve.compare.partial;
  const cats = (r.rank?.by_category || []).map((c) => c.category);
  const [pick, setPick] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const liveChanges = Object.keys(r.approvals).some((k) => k.startsWith("pack_") || k.startsWith("reddit_"));
  const note = liveChanges ? "Directional - AI answers vary run to run." : "No website changes are live yet - this shows how re-checks work, not an improvement.";
  async function start() {
    const chosen = Object.keys(pick).filter((k) => pick[k]);
    if (!window.confirm(`Ask the ${chosen.join(" + ")} questions again with fresh answers? This uses Claude.`)) return;
    setBusy(true); setError(null);
    try {
      const job = await api.post<{ id: string }>(`/api/restaurants/${r.slug}/run`, { runs: 1, reuse: false, web_search: true, platforms: ["claude"], categories: chosen, note });
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1500));
        const j = await api.get<{ state: string; done: number; total: number; error: string | null }>(`/api/jobs/${job.id}`);
        setProgress(`${j.done}/${j.total}`);
        if (j.state !== "running") { if (j.error) setError(j.error); break; }
      }
      window.location.reload();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <Card>
      <h3 className="font-semibold">Re-check only some question types</h3>
      {m && <div className="mt-2 rounded-lg bg-stone-50 p-3">
        <p className="text-sm font-medium text-amber-800">{m.note}</p>
        {m.reason ? <p className="text-sm text-stone-600">{m.reason}</p> : <table className="mt-2 w-full text-sm"><tbody>
          <tr className="text-left text-xs text-stone-500"><th className="py-1 font-medium">Question type</th><th className="font-medium">First · {m.first_when}</th><th className="font-medium">Re-check · {m.when}</th></tr>
          {m.by_category.map((c) => <tr key={c.category} className="border-t border-stone-100"><td className="py-1">{c.category.replace(/-/g, " ")}</td><td>{pct(c.first)}</td><td className="font-semibold">{pct(c.latest)}</td></tr>)}
        </tbody></table>}
      </div>}
      <div className="mt-3 flex flex-wrap gap-2">{cats.map((c) => (
        <label key={c} className="flex items-center gap-1 rounded-full border border-stone-200 px-2 py-0.5 text-sm">
          <input type="checkbox" className="accent-brand-600" checked={!!pick[c]} onChange={(e) => setPick({ ...pick, [c]: e.target.checked })} />{c.replace(/-/g, " ")}
        </label>))}</div>
      <div className="mt-3"><Button small busy={busy} disabled={!Object.values(pick).some(Boolean) || r.is_sample} onClick={start}>Re-check these (fresh answers)</Button></div>
      {busy && <SlowBar label={`Asking those questions again… ${progress}`} />}
      <ErrorNote error={error} />
    </Card>
  );
}

const VERDICT_KIND: Record<string, BadgeKind> = { "Ready for you to post": "LIVE", "Post after edits": "DEMO", "Don't post": "FAILED" };

/** Promoter vs Skeptic on one draft. The verdict and summary are computed by code; the owner decides. */
function AgentReviewPanel({ slug, draftKey, currentText, onUseEdit }: { slug: string; draftKey: string; currentText: string; onUseEdit: (text: string) => void }) {
  const [rv, setRv] = useState<AgentReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(fresh = false) {
    setBusy(true); setError(null);
    try { setRv(await api.post<AgentReview>(`/api/restaurants/${slug}/drafts/${encodeURIComponent(draftKey)}/agent-review?fresh=${fresh}`, { text: currentText })); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  const stale = !!rv && ![rv.reviewed_text, rv.input_text].some((t) => (t || "").trim() === currentText.trim());
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold">Two-agent review</span>
        <div className="flex gap-2">
          <Button small kind="secondary" busy={busy} onClick={() => run(false)}>{!rv ? "Review with 2 agents" : stale ? "Review this version" : "Show review"}</Button>
          {rv && <Button small kind="ghost" busy={busy} onClick={() => run(true)} title="Ignore the saved review and ask both agents again">Review again</Button>}
        </div>
      </div>
      {busy && <SlowBar label="A Promoter and a Skeptic are debating this draft… (10–40 seconds)" />}
      <ErrorNote error={error} />
      {stale && <p className="mt-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">Out of date - the draft changed after this review. Click “Review this version” to check the new wording.</p>}
      {rv && <div className={cx("mt-2 space-y-3", stale && "opacity-50")}>
        <div className="flex flex-wrap items-center gap-2">
          {stale ? <Badge kind="neutral">out of date</Badge> : <Badge kind={VERDICT_KIND[rv.verdict] || "neutral"}>{rv.verdict}</Badge>}
          <span className="text-xs text-stone-500">{rv.label}</span>
          {rv.cached && <span className="text-xs text-stone-400">Same answer as last time (saved)</span>}
        </div>
        <p className="text-sm text-stone-700">{rv.summary}</p>
        {rv.transcript.length > 0 && <ul className="space-y-1.5">{rv.transcript.map((m, i) => (
          <li key={i} className={cx("rounded-lg p-2 text-sm", m.agent === "Promoter" ? "bg-sky-50" : "bg-amber-50")}>
            <span className="text-xs font-semibold">{m.agent} · round {m.round}</span>
            <div>{m.text}</div>
            {m.note && <div className="text-xs text-stone-500">{m.note}</div>}
            {m.citations.length > 0 && <div className="text-xs text-stone-400">cites {m.citations.join(", ")}</div>}
          </li>))}</ul>}
        {rv.checklist.length > 0 && <table className="w-full text-sm"><tbody>
          {rv.checklist.map((c) => (
            <tr key={c.rule} className="border-t border-stone-100 align-top">
              <td className="py-1 pr-2 font-medium">{c.rule}<span className="ml-1 text-xs text-stone-400">{c.level}</span></td>
              <td className={cx("py-1 pr-2 font-semibold", c.result === "pass" ? "text-green-700" : c.result === "fail" ? "text-red-700" : "text-stone-400")}>{c.result}</td>
              <td className="py-1 pr-2">{c.reason}</td>
              <td className="py-1 text-xs text-stone-400">{c.cite}</td>
            </tr>))}
        </tbody></table>}
        {rv.suggested_edit && <div className="rounded-lg bg-stone-50 p-2 text-sm">
          <div className="text-xs font-semibold text-stone-600">Suggested edit</div>
          <div className="whitespace-pre-wrap">{rv.suggested_edit}</div>
          <div className="mt-2"><Button small onClick={() => onUseEdit(rv.suggested_edit!)}>Use suggested edit</Button></div>
        </div>}
      </div>}
    </div>
  );
}
