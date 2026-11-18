// Cliente de la API. La URL base es configurable (VITE_API_URL) para que la app
// empaquetada con Capacitor pueda apuntar al servidor; en web se usa el mismo origen.
const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export type Color = { name: string; hex: string };
export type Photo = { id: string; url: string; thumb_url: string };

export type GarmentFields = {
  name: string;
  type: string;
  color_primary: Color;
  colors_secondary: Color[];
  pattern: string;
  style: string;
  closure: string | null;
  hood: boolean;
  fit: string | null;
  thickness: string | null;
  details: string;
  season: string;
  brand: string | null;
  size: string | null;
  notes: string;
};

export type Garment = GarmentFields & {
  id: number;
  category: string;
  photo_front: Photo;
  photo_back: Photo | null;
  photo_extra: Photo | null;
  photo_label: Photo | null;
  in_laundry: boolean;
  favorite: boolean;
  ai_provider: string | null;
  wear_count: number;
  last_worn_on: string | null;
};

export type Draft = GarmentFields & { confidence: number; color_primary_alt: string | null };

export type Analysis = {
  photo_front: Photo;
  photo_back: Photo | null;
  photo_extra: Photo | null;
  photo_label: Photo | null;
  draft: Draft | null;
  provider: string | null;
  model?: string | null;
  fallback_used: boolean;
  error: string | null;
};

export type Catalog = {
  categories: Record<string, string>;
  types: Record<string, string>;
  seasons: Record<string, string>;
  colors: string[];
  patterns: string[];
  styles: string[];
  closures: string[];
  fits: string[];
  thicknesses: string[];
  ai_providers: string[];
  themes: string[];
};

export type CodexModels = {
  models: { slug: string; name: string; efforts: string[]; default_effort: string | null }[];
  efforts: string[];
};

export type Settings = {
  theme: string;
  ai_provider: string;
  codex_model: string;
  codex_effort: string;
  city: string;
  notify_enabled: boolean;
  notify_time: string;
};

export type AIStatus = { codex_installed: boolean; codex_logged_in: boolean; claude_configured: boolean };

export type CodexLogin = {
  state: "idle" | "pending" | "done" | "failed";
  url: string | null;
  code: string | null;
  error: string | null;
};

export type UsageWindow = { used_percent: number | null; window_minutes: number | null; resets_at: number | null };
export type CodexUsage = {
  plan: string | null;
  allowed: boolean;
  primary: UsageWindow | null;
  secondary: UsageWindow | null;
};

export type Weather = {
  city: string;
  temp_now: number;
  temp_max: number;
  temp_min: number;
  rain_probability: number;
  description: string;
  icon: string;
};

export type Today = {
  date: string;
  city: string;
  weather: Weather | null;
  outfit: { id: number; status: string; affinity: number; day_kind: string; garments: Garment[] } | null;
  missing: string[];
  notes: string[];
  in_laundry: number;
  total: number;
};

export type Taste = {
  combo: { garments: Garment[]; affinity: number } | null;
  rated: number;
  liked: number;
  remaining: number;
  learned: { likes: string[][]; dislikes: string[][] };
};

export type ShopReason = { text: string; kind: "pro" | "contra" };
export type ShopSize = { name: string; in_stock: boolean };

/** Un producto de una tienda propuesto en Compras. */
export type ShopItem = {
  id: number;
  store: string;
  store_name: string;
  name: string;
  price_cents: number;
  url: string;
  store_color: string;
  type: string;
  category: string;
  color: string;
  photos: Photo[];
  score: number;
  reasons: ShopReason[];
  status: string;
  sizes: ShopSize[];
  liked_at: string | null;
  expires_at: string | null;
  expires_soon: boolean;
};

/** Un resultado del buscador por referencia: el producto y si ya estaba guardado. */
export type ShopLookupItem = ShopItem & {
  /** Ya estaba en Me gustan o en el armario. */
  saved: "gustado" | "comprado" | null;
  /** La prenda del armario, si ya estaba comprado. */
  garment_id: number | null;
};

export type ShopStore = {
  key: string;
  name: string;
  enabled: boolean;
  categories: { slug: string; label: string; enabled: boolean }[];
  /** Día de la semana en que se consulta (lunes = 0). */
  weekday: number;
  status: {
    state: "ok" | "failed" | "never";
    at: string | null;
    found: number;
    added: number;
    failed: number;
    error: string | null;
  };
  next_check: string | null;
};

export type ShopState = {
  stores: ShopStore[];
  /** Hay una consulta del catálogo o un «Ver más» en marcha, y cuál de los dos. */
  running: boolean;
  job: "consulta" | "mas" | null;
  pending: number;
  liked: number;
  /** Cómo fue el último «Ver más» desde la última consulta semanal. `low`: lo que trajo ya encaja menos. */
  last_more: { added: number; low: boolean; error: string | null } | null;
};
export type ShopNext = {
  item: ShopItem | null;
  /** Cuántas quedan con el filtro puesto, contando esta. */
  remaining: number;
  /** Cuántas prendas del catálogo puede traer aún «Ver más» con el filtro puesto. */
  more: number;
  /** Hay una decisión que «Volver» puede deshacer. */
  can_undo: boolean;
};
/** El filtro de Descubrir: una tienda y un tipo de prenda (nuestras categorías). null = todo. */
export type ShopFilter = { store: string | null; category: string | null };
export type ShopDiscardReason = "estilo" | "color" | "caro" | "ya_tengo";

const shopQuery = (filter?: ShopFilter) => {
  const query = new URLSearchParams();
  if (filter?.store) query.set("store", filter.store);
  if (filter?.category) query.set("category", filter.category);
  const text = query.toString();
  return text ? `?${text}` : "";
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* respuesta sin JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** Las fotos se sirven desde el backend: hay que anteponer la URL base. */
export const mediaUrl = (path: string) => BASE + path;

export const api = {
  catalog: () => request<Catalog>("/api/catalog"),
  settings: () => request<Settings>("/api/settings"),
  codexModels: () => request<CodexModels>("/api/ai/codex/models"),
  codexLoginStart: () => request<CodexLogin>("/api/ai/codex/login", { method: "POST" }),
  codexLoginStatus: () => request<CodexLogin>("/api/ai/codex/login"),
  codexLoginCancel: () => request<void>("/api/ai/codex/login", { method: "DELETE" }),
  codexLogout: () => request<AIStatus>("/api/ai/codex/logout", { method: "POST" }),
  codexUsage: () => request<CodexUsage>("/api/ai/codex/usage"),
  aiStatus: () => request<AIStatus>("/api/ai/status"),
  /** La clave se envía al servidor y no vuelve nunca. Cadena vacía = borrarla. */
  saveClaudeKey: (key: string) => request<Settings>("/api/settings", json("PATCH", { anthropic_api_key: key })),
  updateSettings: (changes: Partial<Settings>) => request<Settings>("/api/settings", json("PATCH", changes)),
  tasteNext: () => request<Taste>("/api/taste/next"),
  tasteForget: () => request<void>("/api/taste", { method: "DELETE" }),
  tasteRate: (body: { garment_ids: number[]; liked: boolean; reasons: string[]; culprit_ids: number[] }) =>
    request<Taste>("/api/taste/rate", json("POST", body)),
  shopState: () => request<ShopState>("/api/shop/state"),
  shopSettings: (body: { store: string; enabled?: boolean; categories?: string[] }) =>
    request<ShopState>("/api/shop/settings", json("PATCH", body)),
  /** Lanza la consulta en segundo plano y vuelve ya; el avance se sigue con shopState. */
  shopRefresh: (store?: string) => request<ShopState>("/api/shop/refresh", json("POST", { store: store ?? null })),
  /** «Ver más»: trae en segundo plano la siguiente tanda del catálogo guardado; se sigue con shopState. */
  shopMore: (filter: ShopFilter) => request<ShopState>("/api/shop/more", json("POST", filter)),
  shopNext: (filter?: ShopFilter) => request<ShopNext>(`/api/shop/next${shopQuery(filter)}`),
  shopLike: (id: number, filter?: ShopFilter) =>
    request<ShopNext>(`/api/shop/items/${id}/like${shopQuery(filter)}`, { method: "POST" }),
  shopDislike: (id: number, filter?: ShopFilter) =>
    request<ShopNext>(`/api/shop/items/${id}/dislike${shopQuery(filter)}`, { method: "POST" }),
  /** «Volver»: deshace la última decisión y devuelve esa propuesta. */
  shopUndo: (filter?: ShopFilter) => request<ShopNext>(`/api/shop/undo${shopQuery(filter)}`, { method: "POST" }),
  /** Por qué se descartó (opcional). */
  shopReason: (id: number, reason: ShopDiscardReason) =>
    request<void>(`/api/shop/items/${id}/reason`, json("POST", { reason })),
  shopLiked: () => request<ShopItem[]>("/api/shop/liked"),
  /** El buscador: una referencia, un enlace de producto o texto. Tarda unos segundos (habla con la tienda). */
  shopLookup: (query: string) => request<ShopLookupItem[]>("/api/shop/lookup", json("POST", { query })),
  shopRemove: (id: number) => request<void>(`/api/shop/items/${id}`, { method: "DELETE" }),
  shopBought: (id: number, size: string | null) =>
    request<{ garment_id: number; analyzed: boolean }>(`/api/shop/items/${id}/bought`, json("POST", { size })),
  today: () => request<Today>("/api/today"),
  todayNext: (action: "otra" | "pasar") => request<Today>("/api/today/next", json("POST", { action })),
  todayChoose: () => request<Today>("/api/today/choose", { method: "POST" }),
  todayUnchoose: () => request<Today>("/api/today/unchoose", { method: "POST" }),
  garments: () => request<Garment[]>("/api/garments"),
  garment: (id: number) => request<Garment>(`/api/garments/${id}`),
  updateGarment: (id: number, changes: Partial<GarmentFields> & { favorite?: boolean; in_laundry?: boolean }) =>
    request<Garment>(`/api/garments/${id}`, json("PATCH", changes)),
  deleteGarment: (id: number) => request<void>(`/api/garments/${id}`, { method: "DELETE" }),
  wearGarment: (id: number) => request<Garment>(`/api/garments/${id}/wear`, json("POST", {})),
  /** Gira 90° a la derecha. Devuelve la foto con un id nuevo. */
  rotatePhoto: (photoId: string) => request<Photo>(`/api/photos/${photoId}/rotate`, { method: "POST" }),
  clearLaundry: () => request<{ cleared: number }>("/api/laundry/clear", { method: "POST" }),

  /** Sube fotos nuevas o reutiliza las ya subidas (ids) para reintentar el análisis. */
  analyze: (opts: {
    front?: File;
    back?: File;
    extra?: File;
    label?: File;
    frontId?: string;
    backId?: string;
    extraId?: string;
    labelId?: string;
    kind?: "ropa" | "calzado";
    skipAi?: boolean;
  }) => {
    const form = new FormData();
    if (opts.front) form.append("front", opts.front);
    if (opts.back) form.append("back", opts.back);
    if (opts.extra) form.append("extra", opts.extra);
    if (opts.label) form.append("label", opts.label);
    if (opts.frontId) form.append("front_id", opts.frontId);
    if (opts.backId) form.append("back_id", opts.backId);
    if (opts.extraId) form.append("extra_id", opts.extraId);
    if (opts.labelId) form.append("label_id", opts.labelId);
    if (opts.kind) form.append("kind", opts.kind);
    if (opts.skipAi) form.append("skip_ai", "true");
    return request<Analysis>("/api/garments/analyze", { method: "POST", body: form });
  },

  createGarment: (
    body: GarmentFields & {
      photo_front: string;
      photo_back: string | null;
      photo_extra: string | null;
      photo_label: string | null;
      ai_provider: string | null;
      ai_model: string | null;
      ai_confidence: number | null;
      ai_draft: Draft | null;
    },
  ) => request<Garment>("/api/garments", json("POST", body)),
};
