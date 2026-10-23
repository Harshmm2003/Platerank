// Tiny typed client for the Python backend (api.py). Errors carry the backend's plain-English message.

export class ApiError extends Error {}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Can't reach PlateRank. Is the terminal running `python run.py` still open?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.detail || `Request failed (${res.status}).`);
  return data as T;
}

export const api = {
  get: <T>(url: string) => req<T>("GET", url),
  post: <T>(url: string, body?: unknown) => req<T>("POST", url, body ?? {}),
  put: <T>(url: string, body: unknown) => req<T>("PUT", url, body),
};

// ---------------------------------------------------------------- shapes
export type Status = { claude_key: boolean; gemini_key: boolean; platforms: string[]; claude_model: string; discovery_model: string };

export type Competitor = { name: string; website?: string; aliases?: string[]; address?: string; source?: string };

export type Profile = {
  name: string;
  website?: string;
  cuisine: string;
  area: string;
  neighbourhood?: string;
  city?: string;
  state?: string;
  city_id?: string;
  address?: string;
  hours?: string;
  lat?: number;
  lon?: number;
  price_level?: number | null;
  landmarks?: string[];
  aliases?: string[];
  signature_terms?: string[];
  highlights?: string[];
  cuisine_alternates?: string[];
  area_nicknames?: string[];
  anchor_item?: string;
  menu?: { hero_dish_name?: string; hero_dish_price?: number | null; anchor_price?: number | null; source?: string };
  competitors?: Competitor[];
  competitor_menus?: Record<string, { entree_price?: number; anchor_price?: number; source?: string }>;
  facts_source?: Record<string, string>;
  pinned?: boolean;
};

export type RestaurantCard = { slug: string; name: string; cuisine: string; area: string; competitors?: number; last_run?: string | null; sample?: boolean; pinned?: boolean };

export type City = { id: string; name: string; state: string; state_name: string; lat: number; lon: number; population: number; radius_km: number };
export type PlaceHit = { name: string; osm_type: string; osm_id: number; kind: string; address: string; city: string; neighbourhood: string; lat: number; lon: number };
export type PlaceDetails = { name: string; cuisine: string; website: string; hours: string; phone: string; address: string; lat: number; lon: number; source: string };
export type Nearby = { name: string; cuisine: string; same_cuisine: boolean; website: string; address: string; distance_m: number | null; source: string };
export type Source = { url: string; title: string };

export type Job = { id: string; state: "running" | "done" | "failed"; done: number; total: number; note: string; error: string | null; meta: RunMeta | null };
export type RunMeta = { when: string; platforms: string[]; runs: number; web_search: boolean; counts: Record<string, number>; cost_usd: number; questions: number };

export type Gap = { gap: string; evidence: string; affected_categories: string[]; action: "standard" | "creator" | "vfm"; priority: number };
export type Move = { title: string; evidence: string; quote?: string; route: "standard" | "creator" | "vfm"; priority: number | null; categories: string[] };

export type Results = {
  restaurant: string;
  slug: string;
  is_sample: boolean;
  meta: RunMeta;
  questions: Record<string, string>;
  approvals: Record<string, { at: string; text: string }>;
  empty?: boolean;
  rank: {
    mention_rate: number; mentions: number; answers: number; avg_rank: number | null; share_of_voice: number;
    top_competitor: { name: string; mention_rate: number } | null;
    scorecard: { restaurant: string; mention_rate: number; mentions: number; avg_rank: number | null; share_of_voice: number }[];
    by_category: { category: string; queries: number; target_mentions: number; mention_rate: number }[];
    categories_at_zero: string[];
    answers_list: { query: string; category: string; platform: string; model: string; run: number; status: string; mentions: string[]; mentioned: boolean; rank: number | null; answer: string; note: string; sources: Source[] }[];
  };
  why: {
    gaps: Gap[]; site_gaps: string[]; site_audit: Record<string, { audit: Record<string, unknown>; source: string }>;
    ai_recommends_instead: { restaurant: string; answers_naming_it: number }[];
    competitor_frequency: { restaurant: string; appearances: number; share: number }[];
    sources_ai_used: { domain: string; answers: number }[];
    listings_note: string;
    listings: Record<string, { rating?: number; review_count?: number; price_level?: number; source?: string }>;
  };
  change: {
    moves: Move[]; lost_categories: string[]; vfm_needs_reviews: boolean;
    price_scenario: { item: string; current: number; area_average: number; current_premium_pct: number; note: string } | null;
    vfm: null | {
      benchmark_label: string; area_price_level: number | null; area_price_level_n: number;
      analyses: {
        restaurant: string; avg_rating: number; review_count: number; reviews_analysed: number; source: string;
        aspects: Record<string, { mentions: number; positive: number; negative: number; pos_ratio: number | null; pos_quotes: string[]; neg_quotes: string[] }>;
        vfm: { vfm_index: number; verdict: string; food_sentiment: number; price_sentiment: number };
        recommendations: { area: string; evidence: string; example_quote: string; recommendation: string }[];
      }[];
    };
  };
  make: {
    drafts: { key: string; title: string; kind: "text" | "code"; text: string }[];
    creators: { handle: string; name: string; platform: string; followers: number; relevance_score: number; why: string; verified?: boolean; source_url?: string;
      brief: { concept_title: string; hook: string; format: string; target_category: string; must_include_for_ai_citation: string[] }; outreach: string }[];
    creators_note: string;
  };
  improve: { history: { ts: number; platform: string; mention_rate: number; avg_rank: number | null; share_of_voice: number; answers: number }[]; note: string };
};

export const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
export const usd = (x: number | null | undefined) => (x == null ? "—" : `$${x.toFixed(x < 1 ? 2 : 0)}`);
export const miles = (m: number | null) => (m == null ? "" : m < 160 ? `${m} m` : `${(m / 1609).toFixed(2)} mi`);
