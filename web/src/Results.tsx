import { useCallback, useEffect, useState } from "react";
import { api, pct, Results as R } from "./api";
import { Badge, BadgeKind, Bar, Button, Card, ErrorNote, Field, inputCls, More, ROUTE_LABEL, SourceLinks, Stat, copy, cx, download } from "./ui";
import { go } from "./App";

const TABS = [
  ["rank", "1", "Where do I rank?"],
  ["why", "2", "Why are competitors winning?"],
  ["change", "3", "What should I change?"],
  ["make", "4", "Make the changes"],
  ["improve", "5", "Did it improve?"],
] as const;

export default function Results({ slug, tab }: { slug: string; tab: string }) {
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.get<R>(`/api/restaurants/${slug}/results`).then(setR).catch((e) => setError(e.message)), [slug]);
  useEffect(() => { load(); }, [load]);

  if (error) return (
    <Card><ErrorNote error={error} /><div className="mt-3"><Button onClick={() => go(`/r/${slug}/run`)}>Run a check</Button></div></Card>
  );
  if (!r) return <p className="text-stone-500">Loading results…</p>;
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
            <span>· checked {r.meta.when} · {r.meta.platforms.join(" + ")}{r.meta.web_search ? " with web search" : ""}{r.meta.cost_usd ? ` · cost $${r.meta.cost_usd.toFixed(2)}` : ""}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button kind="secondary" onClick={() => go(`/r/${slug}/run`)}>Check again</Button>
          {!r.is_sample && <Button kind="ghost" onClick={() => go(`/r/${slug}/setup/1`)}>Edit setup</Button>}
        </div>
      </div>

      <nav className="flex gap-1 overflow-x-auto border-b border-stone-200">
        {TABS.map(([key, n, label]) => (
          <a key={key} href={`#/r/${slug}/results/${key}`}
            className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium", tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-stone-500 hover:text-stone-800")}>
            <span className="mr-1 text-xs text-stone-400">{n}</span>{label}
          </a>
        ))}
      </nav>

      {r.empty ? <Card>No answers came back in the last check, so there's nothing to score. Try again in a few minutes.</Card> :
        tab === "why" ? <Why r={r} reload={load} /> :
        tab === "change" ? <Change r={r} reload={load} /> :
        tab === "make" ? <Make r={r} reload={load} /> :
        tab === "improve" ? <Improve r={r} /> : <Rank r={r} />}
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
        <Stat label="Question types where you never appear" value={`${k.categories_at_zero.length}`} hint={k.categories_at_zero.slice(0, 4).join(", ")} tone={k.categories_at_zero.length ? "bad" : undefined} />
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
              {c.category} · {pct(c.mention_rate)}
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
  const [auto, setAuto] = useState<{ restaurant: string; rating?: number; review_count?: number; price_level?: number; sources?: Record<string, string>; error?: string }[] | null>(null);

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
            Find public ratings (≈5¢ each)</Button>}
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
                    {Object.values(a.sources || {})[0] && <a className="text-sky-700" href={Object.values(a.sources || {})[0]} target="_blank" rel="noreferrer">source ↗</a>}
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
        <h3 className="font-semibold">Your to-do list, most important first</h3>
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
            {ch.price_scenario && (
              <p className="text-sm text-stone-600">{ch.price_scenario.item}: ${ch.price_scenario.current} vs area ${ch.price_scenario.area_average} ({ch.price_scenario.current_premium_pct > 0 ? "+" : ""}{ch.price_scenario.current_premium_pct}%). {ch.price_scenario.note}</p>
            )}
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
function Draft({ r, k, title, kind, text: initial, reload }: { r: R; k: string; title: string; kind: "text" | "code"; text: string; reload: () => void }) {
  const approved = r.approvals[k];
  const [text, setText] = useState(approved?.text || initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function approve(undo = false) {
    setBusy(true); setError(null);
    try { await api.post(`/api/restaurants/${r.slug}/approve`, { key: k, text, undo }); reload(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{title}</h3>
        {approved ? <Badge kind="LIVE">approved {approved.at}</Badge> : <Badge kind="neutral">draft</Badge>}
      </div>
      <textarea className={cx(inputCls, "mt-3 h-48 text-sm", kind === "code" && "font-mono")} value={text} readOnly={!!approved} onChange={(e) => setText(e.target.value)} />
      {text.includes("OWNER TO CONFIRM") && <p className="mt-1 text-xs text-amber-800">Fill in each [OWNER TO CONFIRM] before approving — we don't guess facts.</p>}
      <ErrorNote error={error} />
      <div className="mt-3 flex flex-wrap gap-2">
        {approved ? <Button kind="secondary" small busy={busy} onClick={() => approve(true)}>Undo approval</Button>
          : <Button small busy={busy} onClick={() => approve()}>✓ Approve</Button>}
        <Button kind="ghost" small onClick={() => copy(text)}>Copy</Button>
        <Button kind="ghost" small onClick={() => download(`${k}.txt`, text)}>Download</Button>
      </div>
      <p className="mt-2 text-xs text-stone-400">Approving only records your decision. PlateRank never publishes or sends anything.</p>
    </Card>
  );
}

function Make({ r, reload }: { r: R; reload: () => void }) {
  const m = r.make;
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        {m.drafts.map((d) => <Draft key={d.key} r={r} k={d.key} title={d.title} kind={d.kind} text={d.text} reload={reload} />)}
      </div>
      <Card>
        <h3 className="font-semibold">Food creators to work with</h3>
        <p className="text-sm text-stone-500">{m.creators_note} YouTube counts most: AI assistants read and cite it.</p>
        {m.creators.length === 0 && <p className="mt-3 text-sm text-stone-500">No creators to show yet.</p>}
      </Card>
      {m.creators.map((c) => (
        <div key={c.handle} className="space-y-2">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><span className="font-semibold">{c.handle}</span> <span className="text-sm text-stone-500">{c.platform} · {c.followers.toLocaleString()} followers</span></div>
              <span className="text-sm">match <b>{c.relevance_score}</b>/100</span>
            </div>
            <p className="mt-1 text-xs text-stone-500">{c.why}</p>
            <p className="mt-2 text-sm"><b>Video idea:</b> “{c.brief.concept_title}” — {c.brief.hook}</p>
          </Card>
          <div className="pl-4">
            <More label={r.approvals[`outreach_${c.handle.replace(/^@/, "")}`] ? `Message to ${c.handle} ✓ approved` : `Message to ${c.handle}`}>
              <Draft r={r} k={`outreach_${c.handle.replace(/^@/, "")}`} title={`Message to ${c.handle}`} kind="text" text={c.outreach} reload={reload} />
            </More>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- 5
function Improve({ r }: { r: R }) {
  const h = r.improve.history;
  if (r.is_sample) return <Card>The sample has no history. Run a real restaurant twice to see the trend here.</Card>;
  const W = 640, H = 200, pad = 30;
  const pts = h.map((x, i) => [pad + (h.length > 1 ? (i / (h.length - 1)) * (W - 2 * pad) : (W - 2 * pad) / 2), H - pad - x.mention_rate * (H - 2 * pad)]);
  const first = h[0], last = h[h.length - 1];
  return (
    <div className="space-y-5">
      {h.length >= 2 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="First check" value={pct(first.mention_rate)} hint={new Date(first.ts * 1000).toLocaleString()} />
          <Stat label="Latest check" value={pct(last.mention_rate)} hint={new Date(last.ts * 1000).toLocaleString()} />
          <Stat label="Change" value={`${last.mention_rate >= first.mention_rate ? "+" : ""}${Math.round((last.mention_rate - first.mention_rate) * 100)} pts`} tone={last.mention_rate > first.mention_rate ? "good" : undefined} hint="directional — answers vary run to run" />
        </div>
      )}
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
        <div className="mt-3"><Button onClick={() => go(`/r/${r.slug}/run`)}>Run a fresh check</Button></div>
      </Card>
    </div>
  );
}
