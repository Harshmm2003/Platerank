import { useEffect, useRef, useState } from "react";
import { api, City, Competitor, Evidence, miles, Nearby, NearbyResult, PlaceDetails, PlaceHit, Profile, Source, Status } from "./api";
import { Badge, Button, Card, ErrorNote, EvidenceBadge, Field, inputCls, More, SlowBar, SourceLinks, cx } from "./ui";
import { go } from "./App";

const PRICE = ["unknown", "$", "$$", "$$$", "$$$$"];
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function Steps({ step }: { step: number }) {
  const names = ["Your restaurant", "Competitors nearby", "Run the check"];
  return (
    <ol className="mb-6 flex flex-wrap gap-2 text-sm">
      {names.map((n, i) => (
        <li key={n} className={cx("rounded-full px-3 py-1", i + 1 === step ? "bg-brand-600 text-white" : i + 1 < step ? "bg-brand-100 text-brand-700" : "bg-stone-100 text-stone-500")}>
          {i + 1}. {n}
        </li>
      ))}
    </ol>
  );
}

export default function Setup({ slug, step, status }: { slug: string | null; step: number; status: Status | null }) {
  const [profile, setProfile] = useState<Profile | null>(slug ? null : { name: "", cuisine: "", area: "", competitors: [] });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!slug) return;
    if (slug === "example") { go("/r/example/run"); return; }
    api.get<{ profile: Profile }>(`/api/restaurants/${slug}`).then((d) => setProfile(d.profile)).catch((e) => setError(e.message));
  }, [slug]);

  if (!profile) return <div><ErrorNote error={error} />{!error && <p className="text-stone-500">Loading…</p>}</div>;
  return (
    <div>
      <Steps step={step} />
      {step === 1 ? <StepRestaurant slug={slug} initial={profile} status={status} /> : <StepCompetitors slug={slug!} initial={profile} status={status} />}
    </div>
  );
}

// ---------------------------------------------------------------- step 1
let citiesCache: City[] | null = null;

function CityPicker({ value, onPick }: { value: City | null; onPick: (c: City) => void }) {
  const [all, setAll] = useState<City[]>(citiesCache || []);
  const [q, setQ] = useState(value ? `${value.name}, ${value.state}` : "");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (citiesCache) return;
    api.get<{ cities: City[] }>("/api/cities").then((d) => { citiesCache = d.cities; setAll(d.cities); }).catch(() => undefined);
  }, []);
  useEffect(() => { if (value) setQ(`${value.name}, ${value.state}`); }, [value]);
  const needle = q.toLowerCase().replace(",", " ").split(/\s+/).filter(Boolean);
  const shown = (value && q === `${value.name}, ${value.state}` ? all
    : all.filter((c) => { const hay = `${c.name} ${c.state} ${c.state_name}`.toLowerCase(); return needle.every((n) => hay.includes(n)); }))
    .slice(0, 60);
  return (
    <div className="relative">
      <input className={inputCls} placeholder="Choose a city…" value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => { setOpen(false); if (value) setQ(`${value.name}, ${value.state}`); else setQ(""); }, 150)} />
      <span className="pointer-events-none absolute right-3 top-2.5 text-stone-400">▾</span>
      {open && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-stone-200 bg-white shadow-lg">
          {shown.map((c) => (
            <li key={c.id}>
              <button className={cx("flex w-full cursor-pointer justify-between gap-2 px-3 py-1.5 text-left hover:bg-brand-50", value?.id === c.id && "bg-brand-50 font-semibold")}
                onMouseDown={(e) => { e.preventDefault(); onPick(c); setOpen(false); }}>
                <span>{c.name}, {c.state}</span>
                <span className="text-xs text-stone-400">{c.population >= 1e6 ? `${(c.population / 1e6).toFixed(1)}M` : `${Math.round(c.population / 1000)}k`} people</span>
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-stone-500">No US city with 50,000+ people matches “{q}”.</li>}
        </ul>
      )}
    </div>
  );
}

function RestaurantSearch({ city, onPick, onSearching, onWeb, canWeb, webBusy }: { city: City | null; onPick: (h: PlaceHit) => void;
  onSearching: (b: boolean) => void; onWeb: (name: string) => void; canWeb: boolean; webBusy?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<PlaceHit[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>(undefined);
  const picked = useRef<string>("");
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!city || q.trim().length < 2) { setHits(null); return; }
    if (q === picked.current) return;  // just picked from the list - don't search again
    timer.current = window.setTimeout(() => {
      onSearching(true);
      api.get<{ results: PlaceHit[] }>(`/api/places/search?q=${encodeURIComponent(q)}&city=${encodeURIComponent(city.id)}`)
        .then((d) => { setHits(d.results); setOpen(true); setError(null); })
        .catch((e) => setError(e.message)).finally(() => onSearching(false));
    }, 350);
  }, [q, city]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="relative">
      <input className={cx(inputCls, "text-lg")} disabled={!city}
        placeholder={city ? `Start typing a restaurant in ${city.name}…` : "Choose the city first"} value={q}
        onChange={(e) => setQ(e.target.value)} onFocus={() => hits?.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)} />
      {open && hits && hits.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-stone-200 bg-white shadow-lg">
          {hits.map((h) => (
            <li key={`${h.osm_type}${h.osm_id}`}>
              <button className="w-full cursor-pointer px-3 py-2 text-left hover:bg-brand-50"
                onMouseDown={(e) => { e.preventDefault(); picked.current = h.name; onPick(h); setOpen(false); setQ(h.name); }}>
                <div className="font-medium">{h.name} <span className="text-xs text-stone-400">{h.kind?.replace("_", " ")}</span></div>
                <div className="text-sm text-stone-500">{h.address || "address not listed"}</div>
              </button>
            </li>
          ))}
          {canWeb && !webBusy && (
            <li className="border-t border-stone-100">
              <button className="w-full cursor-pointer px-3 py-2 text-left text-sm text-sky-700 hover:bg-sky-50"
                onMouseDown={(e) => { e.preventDefault(); picked.current = q; setOpen(false); onWeb(q); }}>
                Not in this list? Find “{q}” on the web instead
              </button>
            </li>
          )}
        </ul>
      )}
      {hits && hits.length === 0 && q !== picked.current && (
        <div className="mt-2 flex flex-wrap items-center gap-3 rounded-lg bg-stone-50 p-3 text-sm text-stone-600">
          <span>“{q}” isn't on the free map (OpenStreetMap) in {city?.name}.</span>
          {canWeb ? <Button small busy={webBusy} onClick={() => { picked.current = q; onWeb(q); }}>Find it on the web</Button>
            : <span>Fill in the fields below by hand.</span>}
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}

/** Step-by-step progress for the lookup: map search -> public details -> done. */
function LookupProgress({ stage, detail }: { stage: "idle" | "searching" | "details" | "done" | "web"; detail?: string }) {
  if (stage === "idle") return null;
  if (stage === "web") return <div className="mt-4 rounded-lg bg-sky-50 p-3"><SlowBar label={detail || "Looking it up on the web…"} /></div>;
  const steps = [["searching", "Searching the map"], ["details", "Reading public details"], ["done", "Details filled in"]] as const;
  const order = { searching: 0, details: 1, done: 2, web: 2 } as const;
  const at = order[stage];
  const pctDone = stage === "searching" ? 30 : stage === "details" ? 70 : 100;
  const busy = stage === "searching" || stage === "details";
  return (
    <div className="mt-4 rounded-lg bg-stone-50 p-3">
      <div className="h-2 w-full overflow-hidden rounded-full bg-stone-200">
        <div className={cx("h-2 rounded-full bg-brand-500 transition-all duration-700", busy && "animate-pulse")} style={{ width: `${pctDone}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {steps.map(([key, label], i) => (
          <span key={key} className={cx(i < at || stage === "done" ? "text-green-700" : i === at ? "font-semibold text-brand-700" : "text-stone-400")}>
            {i < at || (stage === "done") ? "✓" : i === at ? "●" : "○"} {label}
          </span>
        ))}
      </div>
      {detail && <div className="mt-1 text-xs text-stone-500">{detail}</div>}
    </div>
  );
}

type WebFacts = { price_level?: number | null; google_rating?: number | null; google_review_count?: number | null; website?: string | null;
  hours?: string | null; cuisine?: string | null; sources?: Record<string, string>; _engine?: string; _cost_usd?: number;
  _evidence?: Record<string, Evidence>; _unverified?: Record<string, unknown>; _rejected?: number };

function StepRestaurant({ slug, initial, status }: { slug: string | null; initial: Profile; status: Status | null }) {
  const [p, setP] = useState<Profile>(initial);
  const [found, setFound] = useState<Record<string, string>>(initial.facts_source || {});
  const [facts, setFacts] = useState<WebFacts | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [stage, setStage] = useState<"idle" | "searching" | "details" | "done" | "web">("idle");
  const [stageNote, setStageNote] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [city, setCity] = useState<City | null>(null);
  const set = (k: keyof Profile, v: unknown) => setP((x) => ({ ...x, [k]: v }));
  const menu = p.menu || {};
  const setMenu = (k: string, v: unknown) => setP((x) => ({ ...x, menu: { ...(x.menu || {}), [k]: v } }));

  // editing a saved restaurant: show its city as already chosen
  useEffect(() => {
    if (!initial.city) return;
    api.get<{ cities: City[] }>("/api/cities").then((d) => {
      citiesCache = d.cities;
      const c = d.cities.find((x) => x.id === initial.city_id) ||
        d.cities.find((x) => x.name.toLowerCase() === initial.city!.toLowerCase() && (!initial.state || x.state === initial.state)) ||
        (/^new york$/i.test(initial.city!) ? d.cities.find((x) => x.id === "New York City|NY") : undefined);
      if (c) setCity(c);
    }).catch(() => undefined);
  }, [initial.city, initial.city_id, initial.state]);

  function pickCity(c: City) {
    setCity(c);
    setP((x) => ({ ...x, city: c.name, state: c.state, city_id: c.id }));
    setStage("idle");
  }

  async function pick(h: PlaceHit) {
    setError(null); setStage("details"); setStageNote(`Found “${h.name}”. Reading its public details from OpenStreetMap…`);
    const base: Partial<Profile> = { name: h.name, address: h.address, neighbourhood: h.neighbourhood || p.neighbourhood,
      area: p.area || h.neighbourhood || "", lat: h.lat, lon: h.lon };
    const src: Record<string, string> = { name: "OpenStreetMap", address: "OpenStreetMap", neighbourhood: "OpenStreetMap" };
    let filled = 3;
    try {
      const d = await api.get<PlaceDetails>(`/api/places/details?osm_type=${h.osm_type}&osm_id=${h.osm_id}`);
      if (d.cuisine) { base.cuisine = d.cuisine.split(",")[0].trim(); src.cuisine = "OpenStreetMap"; filled++; }
      if (d.website) { base.website = d.website; src.website = "OpenStreetMap"; filled++; }
      if (d.hours) { base.hours = d.hours; src.hours = "OpenStreetMap"; filled++; }
      if (d.address) base.address = d.address;
      setStage("done");
      setStageNote(`${filled} details filled from the map. Check them below${!d.cuisine || !d.website ? " — the map didn't list everything, so fill in the blanks" : ""}.`);
    } catch (e) {
      setError((e as Error).message);
      setStage("done"); setStageNote("Name and address filled; the map couldn't give more details — fill in the rest.");
    }
    setP((x) => ({ ...x, ...base }));
    setFound((f) => ({ ...f, ...src }));
  }

  async function webLookup(name: string) {
    if (!city) return;
    setError(null); setStage("web"); setStageNote(`“${name}” isn't on the map — Claude is looking it up on the web (10–30 seconds)…`);
    try {
      const f = await api.post<WebFacts & { name?: string; address?: string; neighbourhood?: string; phone?: string;
        _point?: { lat: number; lon: number; precision: string } | null }>("/api/web-lookup", { name, city: city.id });
      const src = f.sources || {};
      const upd: Partial<Profile> = { name: f.name || name };
      const fs: Record<string, string> = { name: src.name || "web" };
      const take = (k: keyof Profile, v: unknown, sk: string) => { if (v) { (upd as Record<string, unknown>)[k] = v; fs[k as string] = src[sk] || "web"; } };
      take("address", f.address, "address"); take("neighbourhood", f.neighbourhood, "neighbourhood");
      take("cuisine", f.cuisine, "cuisine"); take("website", f.website, "website"); take("hours", f.hours, "hours");
      take("price_level", f.price_level, "price_level");
      if (f.neighbourhood && !p.area) upd.area = f.neighbourhood;
      if (f._point) { upd.lat = f._point.lat; upd.lon = f._point.lon; }
      setP((x) => ({ ...x, ...upd }));
      setFound((x) => ({ ...x, ...fs }));
      setFacts(f);  // rating + review count are saved with the profile, like "Search the web"
      setStage("done");
      const nUnver = Object.keys(f._unverified || {}).length, nRej = f._rejected || 0;
      setStageNote(`Found on the web and checked on the cited pages: ${Object.keys(fs).length} details used.` +
        (nUnver ? ` ${nUnver} couldn't be checked (left blank - see the links in “Look up public facts”).` : "") +
        (nRej ? ` ${nRej} rejected - not found on the cited page.` : "") +
        (f._point ? ` Placed on the map by its ${f._point.precision} for the nearby-competitor search.` : " Couldn't place the address on the map, so nearby competitors will come from Claude instead."));
    } catch (e) {
      setError((e as Error).message); setStage("idle");
    }
  }

  async function lookup() {
    setError(null); setBusy("facts");
    try { setFacts(await api.post<WebFacts>("/api/web-facts", { profile: p })); }
    catch (e) { setError((e as Error).message); }
    setBusy(null);
  }

  function useFacts() {
    if (!facts) return;
    const src = facts.sources || {};
    const upd: Partial<Profile> = {};
    const f: Record<string, string> = {};
    if (facts.price_level) { upd.price_level = facts.price_level; f.price_level = src.price_level || "web"; }
    if (facts.website && !p.website) { upd.website = facts.website; f.website = src.website || "web"; }
    if (facts.hours && !p.hours) { upd.hours = facts.hours; f.hours = src.hours || "web"; }
    if (facts.cuisine && !p.cuisine) { upd.cuisine = facts.cuisine; f.cuisine = src.cuisine || "web"; }
    setP((x) => ({ ...x, ...upd }));
    setFound((x) => ({ ...x, ...f }));
  }

  async function save() {
    setError(null); setBusy("save");
    try {
      const d = await api.put<{ slug: string }>("/api/restaurants", { profile: { ...p, facts_source: found }, previous_slug: slug });
      if (facts && (facts.google_rating || facts.google_review_count)) {
        await api.post(`/api/restaurants/${d.slug}/listings`, { restaurant: p.name, rating: facts.google_rating ?? null,
          review_count: facts.google_review_count ?? null, price_level: facts.price_level ?? null,
          source: `Claude web search: ${Object.values(facts.sources || {}).join(" ")}`.slice(0, 500) });
      }
      go(`/r/${d.slug}/setup/2`);
    } catch (e) { setError((e as Error).message); }
    setBusy(null);
  }

  const tag = (k: string) => found[k] ? <Badge kind={found[k] === "OpenStreetMap" ? "osm" : "web"} title={found[k]}>{found[k] === "OpenStreetMap" ? "from map" : "from web"}</Badge> : null;
  const label = (text: string, k: string) => <span className="inline-flex items-center gap-2">{text} {tag(k)}</span>;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <Card>
          <h2 className="text-xl font-semibold">Find your restaurant</h2>
          <p className="mb-3 text-sm text-stone-500">Choose the city, then pick the restaurant from the list — its public details fill in. You can change anything.</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="City" required><CityPicker value={city} onPick={pickCity} /></Field>
            <div className="sm:col-span-2">
              <Field label="Restaurant"><RestaurantSearch city={city} onPick={pick} onWeb={webLookup} canWeb={!!status?.claude_key} webBusy={stage === "web"}
                onSearching={(b) => { if (b) { setStage("searching"); setStageNote(`Looking for matches in ${city?.name}…`); } else setStage((s) => (s === "searching" ? "idle" : s)); }} /></Field>
            </div>
          </div>
          <LookupProgress stage={stage} detail={stageNote} />
        </Card>

        <Card>
          <h2 className="mb-4 text-xl font-semibold">The basics</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Restaurant name" required><input className={inputCls} value={p.name} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label={label("Cuisine, as customers say it", "cuisine")} required hint="e.g. sushi — this goes into every question we ask the AI">
              <input className={inputCls} value={p.cuisine} onChange={(e) => set("cuisine", e.target.value)} />
            </Field>
            <Field label="Area customers search by" required hint="A neighbourhood, station or campus — e.g. Penn Station">
              <input className={inputCls} value={p.area} onChange={(e) => set("area", e.target.value)} />
            </Field>
            <Field label={label("Neighbourhood", "neighbourhood")}><input className={inputCls} value={p.neighbourhood || ""} onChange={(e) => set("neighbourhood", e.target.value)} /></Field>
            <Field label={label("Address", "address")}><input className={inputCls} value={p.address || ""} onChange={(e) => set("address", e.target.value)} /></Field>
            <Field label={label("Website", "website")}><input className={inputCls} value={p.website || ""} onChange={(e) => set("website", e.target.value)} /></Field>
            <Field label={label("Opening hours", "hours")}><input className={inputCls} value={p.hours || ""} onChange={(e) => set("hours", e.target.value)} /></Field>
            <Field label={label("Price level", "price_level")} hint="As shown on Google Maps">
              <select className={inputCls} value={p.price_level || 0} onChange={(e) => set("price_level", Number(e.target.value) || null)}>
                {PRICE.map((x, i) => <option key={x} value={i}>{x}</option>)}
              </select>
            </Field>
          </div>
        </Card>

        <Card>
          <h2 className="text-xl font-semibold">Owner details <span className="text-base font-normal text-stone-500">(optional — only you know these)</span></h2>
          <p className="mb-4 text-sm text-stone-500">Used for the price comparison and the website drafts. Leave blank if unsure — nothing is guessed.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Hero dish" hint="The dish you're known for"><input className={inputCls} value={menu.hero_dish_name || ""} onChange={(e) => setMenu("hero_dish_name", e.target.value)} /></Field>
            <Field label="Hero dish price ($)"><input type="number" min={0} className={inputCls} value={menu.hero_dish_price ?? ""} onChange={(e) => setMenu("hero_dish_price", e.target.value ? Number(e.target.value) : null)} /></Field>
            <Field label="Everyday item people compare" hint="e.g. a roll, coffee, miso soup"><input className={inputCls} value={p.anchor_item || ""} onChange={(e) => set("anchor_item", e.target.value)} /></Field>
            <Field label="Its price ($)"><input type="number" min={0} className={inputCls} value={menu.anchor_price ?? ""} onChange={(e) => setMenu("anchor_price", e.target.value ? Number(e.target.value) : null)} /></Field>
            <Field label="Signature dishes" hint="comma-separated — used in the AI questions"><input className={inputCls} value={(p.signature_terms || []).join(", ")} onChange={(e) => set("signature_terms", list(e.target.value))} /></Field>
            <Field label="Other names AI might use" hint="e.g. a short name"><input className={inputCls} value={(p.aliases || []).join(", ")} onChange={(e) => set("aliases", list(e.target.value))} /></Field>
            <Field label="Landmarks people search by" hint="e.g. a station or venue"><input className={inputCls} value={(p.landmarks || []).join(", ")} onChange={(e) => set("landmarks", list(e.target.value))} /></Field>
            <Field label="Phone number" hint="used in the website schema"><input className={inputCls} value={p.phone || ""} onChange={(e) => set("phone", e.target.value)} /></Field>
            <Field label="Year opened"><input type="number" min={1800} max={2100} className={inputCls} value={p.year_opened ?? ""} onChange={(e) => set("year_opened", e.target.value ? Number(e.target.value) : null)} /></Field>
            <Field label="What you're known for" hint="comma-separated, e.g. happy hour, cocktails, private events, catering, gluten-free — adds matching AI questions"><input className={inputCls} value={(p.highlights || []).join(", ")} onChange={(e) => set("highlights", list(e.target.value))} /></Field>
            <Field label="Other words for your cuisine" hint="e.g. a broader style people also search for"><input className={inputCls} value={(p.cuisine_alternates || []).join(", ")} onChange={(e) => set("cuisine_alternates", list(e.target.value))} /></Field>
            <Field label="Nicknames for your area" hint="e.g. the short name locals use"><input className={inputCls} value={(p.area_nicknames || []).join(", ")} onChange={(e) => set("area_nicknames", list(e.target.value))} /></Field>
          </div>
        </Card>
        <ErrorNote error={error} />
        <div className="flex gap-3">
          <Button onClick={save} busy={busy === "save"} disabled={!p.name.trim() || !p.cuisine.trim() || !p.area.trim() || !city}
            title={!city ? "Choose the city first" : ""}>Save and pick competitors →</Button>
          <Button kind="ghost" onClick={() => go("/")}>Cancel</Button>
        </div>
      </div>

      <div className="space-y-4">
        <Card>
          <h3 className="font-semibold">Look up public facts</h3>
          <p className="mt-1 text-sm text-stone-500">Claude searches the web for the Google price level, rating and review count — with a link for each, for you to check.</p>
          <div className="mt-3">
            <Button kind="secondary" onClick={lookup} busy={busy === "facts"} disabled={!p.name.trim() || !status?.claude_key || stage === "web"}
              title={status?.claude_key ? "" : "Needs a Claude key in .env"}>Search the web</Button>
          </div>
          {busy === "facts" && <SlowBar label={`Claude is searching the web for ${p.name}… (10–30 seconds)`} />}
          {facts && (
            <div className="mt-4 space-y-2 text-sm">
              {([["Price level", facts.price_level ? PRICE[facts.price_level] : null, "price_level"], ["Google rating", facts.google_rating, "google_rating"],
                ["Google reviews", facts.google_review_count, "google_review_count"], ["Website", facts.website, "website"], ["Hours", facts.hours, "hours"]] as const)
                .map(([k, v, key]) => (
                  <div key={k} className="flex justify-between gap-2 border-b border-stone-100 pb-1">
                    <span className="text-stone-500">{k}</span>
                    <span className="flex flex-col items-end text-right">
                      {v != null ? v : facts._unverified?.[key] != null
                        ? <span className="text-stone-400 line-through decoration-stone-300" title="Not used - we couldn't check it on the cited page">{String(facts._unverified[key])}</span>
                        : <span className="text-stone-400">not found</span>}
                      <EvidenceBadge ev={facts._evidence?.[key]} />
                    </span>
                  </div>
                ))}
              {!!facts._rejected && <p className="text-xs text-stone-500">{facts._rejected} claim{facts._rejected > 1 ? "s" : ""} rejected - not found on the cited page.</p>}
              <p className="text-xs text-stone-400">Only ✓ verified values are used. Greyed ones couldn't be checked - open the link and type them in yourself if they're right.</p>
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-stone-400">{facts._engine}</span>
                <Button small onClick={useFacts}>Use these</Button>
              </div>
            </div>
          )}
        </Card>
        <Card className="bg-stone-50 text-sm text-stone-600">
          <div className="font-semibold text-stone-800">Where the details come from</div>
          <p className="mt-1"><Badge kind="osm">from map</Badge> OpenStreetMap (free public map data).</p>
          <p className="mt-1"><Badge kind="web">from web</Badge> Found by Claude's web search, with the link.</p>
          <p className="mt-1">Everything else is what you type. PlateRank never invents a fact.</p>
          <p className="mt-2 text-xs text-stone-400">City list: every US city or borough with 50,000+ people (GeoNames).</p>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- step 2
type Suggestion = { name: string; website?: string; address?: string; why?: string; source_url?: string; site_responds?: boolean | null; evidence?: Evidence };

function StepCompetitors({ slug, initial, status }: { slug: string; initial: Profile; status: Status | null }) {
  const [p, setP] = useState<Profile>(initial);
  const [radius, setRadius] = useState(800);
  const [map, setMap] = useState<NearbyResult | null>(null);
  const [mapBusy, setMapBusy] = useState(false);
  const [claudeBusy, setClaudeBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const latest = useRef(0);
  const freshNext = useRef(false);  // "Refresh" skips the saved results once
  const retryMap = () => { freshNext.current = true; setRefresh((n) => n + 1); };
  const [sugg, setSugg] = useState<{ suggestions: Suggestion[]; sources: Source[]; engine?: string; grounded: boolean; rejected?: number } | null>(null);
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const comps = p.competitors || [];
  const has = (n: string) => comps.some((c) => c.name.toLowerCase() === n.toLowerCase());
  const toggle = (c: Competitor) => setP((x) => ({ ...x, competitors: has(c.name) ? comps.filter((k) => k.name.toLowerCase() !== c.name.toLowerCase()) : [...comps, c] }));

  // Map search only once the slider stops moving; answers to older slider positions are ignored.
  // A slow/busy map comes back as saved results or map_unavailable (calm note), never as an error.
  useEffect(() => {
    if (p.lat == null || p.lon == null) return;
    const id = ++latest.current;
    const t = window.setTimeout(() => {
      const fresh = freshNext.current;
      freshNext.current = false;
      setMapBusy(true);
      api.get<NearbyResult>(`/api/places/nearby?lat=${p.lat}&lon=${p.lon}&radius=${radius}&cuisine=${encodeURIComponent(p.cuisine)}` +
        `&exclude=${encodeURIComponent(p.name)}&slug=${encodeURIComponent(slug)}${fresh ? "&fresh=true" : ""}`)
        .then((d) => { if (id === latest.current) setMap(d); })
        .catch((e) => { if (id === latest.current) setError(e.message); })
        .finally(() => { if (id === latest.current) setMapBusy(false); });
    }, 600);
    return () => window.clearTimeout(t);
  }, [radius, p.lat, p.lon, p.cuisine, p.name, slug, refresh]);

  async function askClaude() {
    setClaudeBusy(true); setError(null);
    try { setSugg(await api.post(`/api/restaurants/${slug}/suggest-competitors`)); } catch (e) { setError((e as Error).message); }
    setClaudeBusy(false);
  }

  async function save() {
    setBusy("save"); setError(null);
    try { await api.put("/api/restaurants", { profile: { ...p, competitors: comps }, previous_slug: slug }); go(`/r/${slug}/run`); }
    catch (e) { setError((e as Error).message); }
    setBusy(null);
  }

  const nearby = map && !map.map_unavailable ? map.results : null;
  const same = nearby?.filter((n) => n.same_cuisine) || [];
  const other = nearby?.filter((n) => !n.same_cuisine) || [];
  const Row = ({ n }: { n: Nearby }) => (
    <label className="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2 hover:bg-stone-50">
      <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={has(n.name)} onChange={() => toggle({ name: n.name, website: n.website, address: n.address, source: n.source })} />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{n.name} <span className="text-sm font-normal text-stone-500">· {miles(n.distance_m)}</span></div>
        <div className="truncate text-xs text-stone-500">{[n.cuisine, n.address].filter(Boolean).join(" · ") || "no details on the map"}</div>
      </div>
    </label>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <Card>
          <h2 className="text-xl font-semibold">Who do you compete with?</h2>
          <p className="text-sm text-stone-500">Tick the places your customers would otherwise choose. You decide — nothing is added for you.</p>
          {p.lat == null ? (
            <p className="mt-4 rounded-lg bg-stone-50 p-3 text-sm text-stone-600">No map location saved (the restaurant wasn't picked from the search list), so nearby places can't be listed. Use Claude's suggestions or add names below.</p>
          ) : (
            <div className="mt-4">
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium whitespace-nowrap">Within {miles(radius)}</span>
                <input type="range" min={200} max={3200} step={100} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="w-full accent-brand-600" />
              </div>
              {mapBusy && <SlowBar label="Looking for nearby restaurants…" />}
              {!mapBusy && map?.map_unavailable && (
                <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-stone-100 p-3 text-sm text-stone-600">
                  <span>The free map is slow right now - use Claude's suggestions below{status?.claude_key ? "" : ", or add names on the right"}.</span>
                  {status?.claude_key && <Button small kind="secondary" onClick={askClaude} busy={claudeBusy}>Suggest competitors</Button>}
                  <button className="cursor-pointer text-xs text-stone-500 underline" onClick={retryMap}>Try the map again</button>
                </div>
              )}
              {nearby && (
                <div className="mt-3">
                  <div className="text-sm font-semibold text-stone-700">Same kind of food ({same.length})</div>
                  {same.length ? same.map((n) => <Row key={n.name} n={n} />) : <p className="py-2 text-sm text-stone-500">None tagged as {p.cuisine} on the map in this radius — widen it, or ask Claude.</p>}
                  {other.length > 0 && <More label={`Other restaurants nearby (${other.length})`}>{other.map((n) => <Row key={n.name} n={n} />)}</More>}
                  <p className="mt-2 text-xs text-stone-400">
                    {map?.cached_at ? <>Saved map results from {map.cached_at}{map.cached_radius && map.cached_radius !== radius ? ` (searched within ${miles(map.cached_radius)})` : ""} · </> : null}
                    From OpenStreetMap — it can miss places or list closed ones.
                    {map?.cached_at && <> <button className="cursor-pointer underline" disabled={mapBusy} onClick={retryMap}>Refresh from the map</button></>}
                  </p>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="font-semibold">Ask Claude who else competes</h3>
              <p className="text-sm text-stone-500">Searches the web, with sources.</p>
            </div>
            <Button kind="secondary" onClick={askClaude} busy={claudeBusy} disabled={!status?.claude_key}>Suggest competitors</Button>
          </div>
          {claudeBusy && <SlowBar label="Claude is searching the web for competitors… (10–30 seconds)" />}
          {sugg && (
            <div className="mt-3">
              {!sugg.grounded && <p className="mb-2 rounded bg-amber-50 p-2 text-sm text-amber-900">Not web-verified — check each one.</p>}
              {sugg.suggestions.map((s) => (
                <label key={s.name} className={cx("flex items-start gap-3 rounded-lg px-2 py-2", s.evidence?.status === "verified" ? "cursor-pointer hover:bg-stone-50" : "opacity-60")}>
                  <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={has(s.name)} disabled={s.evidence?.status !== "verified" && !has(s.name)}
                    title={s.evidence?.status === "verified" ? "" : "Not checked - open the link; if it's right, add it by name on the right"}
                    onChange={() => toggle({ name: s.name, website: s.website || "", address: s.address, source: s.source_url || "Claude web search" })} />
                  <div className="min-w-0">
                    <div className="font-medium">{s.name} {s.site_responds === false && <Badge kind="FAILED">site didn't load</Badge>}</div>
                    <div className="text-xs text-stone-500">{[s.address, s.why].filter(Boolean).join(" · ")}</div>
                    <EvidenceBadge ev={s.evidence} />
                  </div>
                </label>
              ))}
              {!!sugg.rejected && <p className="mt-1 text-xs text-stone-500">{sugg.rejected} suggestion{sugg.rejected > 1 ? "s" : ""} rejected - the cited page doesn't mention {sugg.rejected > 1 ? "them" : "it"}.</p>}
              <SourceLinks sources={sugg.sources} />
            </div>
          )}
        </Card>
        <ErrorNote error={error} />
      </div>

      <div className="space-y-4">
        <Card>
          <h3 className="font-semibold">Your competitors ({comps.length})</h3>
          {comps.length === 0 && <p className="mt-2 text-sm text-stone-500">None yet — tick at least one.</p>}
          <ul className="mt-2 space-y-1">
            {comps.map((c) => (
              <li key={c.name} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">{c.name}</span>
                <button className="cursor-pointer text-stone-400 hover:text-red-600" onClick={() => toggle(c)} title="Remove">✕</button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <input className={inputCls} placeholder="Add by name" value={manual} onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && manual.trim()) { toggle({ name: manual.trim() }); setManual(""); } }} />
            <Button small kind="secondary" disabled={!manual.trim()} onClick={() => { toggle({ name: manual.trim() }); setManual(""); }}>Add</Button>
          </div>
          <div className="mt-5 flex flex-col gap-2">
            <Button onClick={save} busy={busy === "save"} disabled={!comps.length}>Save and continue →</Button>
            <Button kind="ghost" onClick={() => go(`/r/${slug}/setup/1`)}>← Back</Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
