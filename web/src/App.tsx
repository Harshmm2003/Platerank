import { useCallback, useEffect, useRef, useState } from "react";
import { api, RestaurantCard, Status } from "./api";
import { Badge, Button, Card, ErrorNote } from "./ui";
import Setup from "./Setup";
import RunPage from "./RunPage";
import Results from "./Results";

// Hash routes: #/  ·  #/home (Home, never auto-opens a pinned restaurant)  ·  #/new  ·  #/r/<slug>/setup/<step>  ·  #/r/<slug>/run  ·  #/r/<slug>/results/<tab>
function useRoute() {
  const [hash, setHash] = useState(window.location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => { setHash(window.location.hash.slice(1) || "/"); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.split("/").filter(Boolean);
}

export const go = (path: string) => { window.location.hash = path; };

type RestaurantList = { restaurants: RestaurantCard[]; example: RestaurantCard };
const openPath = (r: RestaurantCard) => (r.last_run ? `/r/${r.slug}/results` : `/r/${r.slug}/run`);

export default function App() {
  const parts = useRoute();
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => { api.get<Status>("/api/status").then(setStatus).catch(() => setStatus(null)); }, []);
  const [list, setList] = useState<RestaurantList | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const reload = useCallback(() => api.get<RestaurantList>("/api/restaurants").then(setList).catch((e) => setListError(e.message)), []);
  const route = parts.join("/");
  useEffect(() => { reload(); }, [reload, route]); // re-read on every page change, so "last checked" stays current

  // Exactly one pinned restaurant: opening the app (no page in the address) goes straight to it.
  const pinned = list?.restaurants.filter((r) => r.pinned) ?? [];
  const focus = pinned.length === 1 ? pinned[0] : null;
  const opened = useRef(false);
  useEffect(() => {
    if (!list || opened.current) return;
    opened.current = true;
    if (focus && parts.length === 0) go(openPath(focus));
  }, [list]);

  let page;
  if (parts[0] === "new") page = <Setup key="new" slug={null} step={1} status={status} />;
  else if (parts[0] === "r" && parts[1]) {
    const slug = parts[1];
    if (parts[2] === "setup") page = <Setup key={`${slug}-${parts[3]}`} slug={slug} step={Number(parts[3] || 1)} status={status} />;
    else if (parts[2] === "run") page = <RunPage key={`${slug}-${parts[3] || ""}`} slug={slug} status={status} fresh={parts[3] === "fresh"} />;
    else page = <Results key={slug} slug={slug} tab={parts[3] || "rank"} />;
  } else page = <Home status={status} data={list} error={listError} reload={reload} />;

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <a href="#/" className="flex items-center gap-2 font-bold text-lg">
            <span>🍽️</span> PlateRank <span className="text-brand-600">AI</span>
          </a>
          {focus ? (
            <div className="flex items-center gap-3 text-sm">
              <a href={`#${openPath(focus)}`} className="font-semibold text-stone-800">📌 {focus.name}</a>
              <a href="#/home" className="text-brand-700 underline">Switch restaurant</a>
            </div>
          ) : (
            <div className="text-sm text-stone-500 hidden sm:block">Get recommended by AI, not just ranked on Google</div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{page}</main>
    </div>
  );
}

function Home({ status, data, error, reload }: { status: Status | null; data: RestaurantList | null; error: string | null; reload: () => Promise<unknown> }) {
  const [pinError, setPinError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const togglePin = async (r: RestaurantCard) => {
    setBusy(r.slug); setPinError(null);
    try { await api.post(`/api/restaurants/${r.slug}/pin`, { pinned: !r.pinned }); await reload(); }
    catch (e) { setPinError((e as Error).message); }
    finally { setBusy(null); }
  };
  const pinned = data?.restaurants.filter((r) => r.pinned) ?? [];
  const others = data?.restaurants.filter((r) => !r.pinned) ?? [];

  const card = (r: RestaurantCard) => (
    <Card key={r.slug} className={r.pinned ? "border-brand-500" : undefined}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{r.name}</div>
          <div className="text-sm text-stone-500">{r.cuisine} · {r.area}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge kind="LIVE">real data</Badge>
          {r.pinned && <Badge kind="pinned">📌 Pinned</Badge>}
        </div>
      </div>
      <div className="mt-2 text-xs text-stone-500">{r.competitors} competitors · {r.last_run ? `last checked ${r.last_run}` : "not checked in this app yet"}</div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button small onClick={() => go(openPath(r))}>{r.last_run ? "See results" : "Run check"}</Button>
        {!r.last_run && <Button small kind="secondary" onClick={() => go(`/r/${r.slug}/results/housekeeping`)}>Website drafts</Button>}
        <Button small kind="secondary" onClick={() => go(`/r/${r.slug}/setup/1`)}>Edit</Button>
        <Button small kind="ghost" busy={busy === r.slug} onClick={() => togglePin(r)}
                title={r.pinned ? "Stop focusing the app on this restaurant" : "Focus the app on this restaurant"}>
          {r.pinned ? "Unpin" : "📌 Pin"}
        </Button>
      </div>
    </Card>
  );
  const sample = data && (
    <Card className="bg-amber-50/40">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{data.example.name}</div>
          <div className="text-sm text-stone-500">{data.example.cuisine} · {data.example.area}</div>
        </div>
        <Badge kind="SAMPLE">SAMPLE</Badge>
      </div>
      <div className="mt-2 text-xs text-stone-500">Fictional restaurant from the hackathon brief. Every number is sample data.</div>
      <div className="mt-4"><Button small kind="secondary" onClick={() => go(`/r/example/run`)}>Open the sample</Button></div>
    </Card>
  );
  const newCard = (
    <button onClick={() => go("/new")} className="cursor-pointer rounded-2xl border-2 border-dashed border-brand-500 bg-brand-50 p-5 text-left hover:bg-brand-100">
      <div className="text-2xl">＋</div>
      <div className="mt-2 font-semibold text-brand-700">Check a restaurant</div>
      <div className="text-sm text-stone-600">Search by name — most details fill in for you.</div>
    </button>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Does AI recommend your restaurant?</h1>
        <p className="mt-2 max-w-2xl text-stone-600">
          People now ask Claude and other assistants where to eat. PlateRank asks them the same questions your customers do,
          shows who they recommend instead, and drafts the fixes — you approve everything.
        </p>
      </div>
      {status && !status.claude_key && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          No Claude key found in <code>.env</code>, so live checks are off. You can still open the sample and re-show saved answers.
          Add <code>ANTHROPIC_API_KEY=…</code> to <code>.env</code> and restart <code>python run.py</code>.
        </div>
      )}
      <ErrorNote error={error || pinError} />
      {pinned.length > 0 ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pinned.map(card)}
            {newCard}
          </div>
          <details className="rounded-2xl border border-stone-200 bg-white/60 p-4">
            <summary className="cursor-pointer font-semibold text-stone-700">Other restaurants ({others.length + 1}, incl. the SAMPLE)</summary>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {others.map(card)}
              {sample}
            </div>
          </details>
        </>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {newCard}
          {others.map(card)}
          {sample}
        </div>
      )}
    </div>
  );
}
