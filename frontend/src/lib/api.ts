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
  /** La referencia de la prenda en su tienda («3918/300/800»). La pone Compras o se escribe a mano. */
  reference: string | null;
};

export type Garment = GarmentFields & {
  id: number;
  category: string;
  /** De qué tienda vino y su página, si entró por Compras. */
  store_name: string | null;
  store_url: string | null;
  photo_front: Photo;
  photo_back: Photo | null;
  photo_extra: Photo | null;
  photo_label: Photo | null;
  /** Codex redibujó las fotos como «de tienda»; se puede volver a las de la cámara. */
  photos_edited: boolean;
  in_laundry: boolean;
  favorite: boolean;
  /** Pedida en la tienda y aún sin llegar: no se propone ni se puede usar. */
  on_order: boolean;
  ordered_at: string | null;
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

export type CodexModel = { slug: string; name: string; efforts: string[]; default_effort: string | null; vision?: boolean };
export type CodexModels = {
  /** Para analizar fotos: solo los que tienen visión. */
  models: CodexModel[];
  /** Para traducir los nombres de las tiendas: todos, también los que no ven. */
  translate_models: CodexModel[];
  efforts: string[];
};

export type Settings = {
  theme: string;
  ai_provider: string;
  codex_model: string;
  codex_effort: string;
  /** Los de traducir los nombres de las tiendas, aparte de los de analizar fotos. */
  codex_translate_model: string;
  codex_translate_effort: string;
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
/** Uno de los colores en los que existe un producto. Cada color es un producto aparte. */
export type ShopColor = {
  product_ref: string;
  name: string;
  hex: string;
  current: boolean;
  /** Se puede ver ya. Si no (JD Sports: aún sin descargar), sale apagado y solo enlaza a la tienda. */
  available: boolean;
  /** Su página en la tienda. */
  url: string;
};

/** Un producto de una tienda propuesto en Compras. */
export type ShopItem = {
  id: number;
  store: string;
  store_name: string;
  product_ref: string;
  /** La referencia de la tienda, legible («3918/300/800»). */
  reference: string | null;
  /** La marca, en las tiendas de varias marcas (Courir, JD Sports). */
  brand: string | null;
  /** En español si se ha podido traducir. */
  name: string;
  /** El nombre como lo escribe la tienda, si `name` está traducido (sirve para buscarlo en su web). */
  name_original: string | null;
  price_cents: number;
  /** El precio de antes (tachado), solo si la tienda dice que está rebajado; null si no hay oferta. */
  old_price_cents?: number | null;
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
  /** De qué está hecha, si la tienda lo dice. */
  composition: string | null;
  /** Los colores entre los que se puede elegir (vacío si solo hay uno). null = aún no se sabe (shopColors). */
  colors: ShopColor[] | null;
  /** Encontrado en lo guardado y aún sin fotos: llegan en segundo plano. */
  photo_pending?: boolean;
  /** «También en»: la misma zapatilla (mismo código de fabricante) en otras tiendas, de la más barata a la más cara. */
  also_in?: ShopAlsoIn[];
};

/** La misma zapatilla en otra tienda. */
export type ShopAlsoIn = { store: string; store_name: string; price_cents: number; url: string };

/** «Combina con…»: las prendas del armario que mejor van con un producto, por parte del cuerpo. */
export type ShopMatches = {
  /** Prendas que hay en el armario (0 = vacío). */
  wardrobe: number;
  groups: {
    category: string;
    garments: { id: number; name: string; type: string; photo: Photo; affinity: number }[];
  }[];
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
  /** El día sale de cuándo saca novedades la tienda; si no, es uno elegido sin ese dato. */
  weekday_after_release: boolean;
  /** Se lee con un navegador de verdad (Pull&Bear, Bershka, JD Sports): tarda más. */
  browser: boolean;
  /** De las «pesadas» del reparto de noches: como mucho una por noche. */
  heavy: boolean;
  /** Qué clase de ropa trae con las secciones elegidas (nuestras categorías: «calzado»…). */
  kinds: string[];
  /** Por qué no se puede consultar en este equipo («No disponible: falta el navegador»), o null. */
  unavailable: string | null;
  status: {
    state: "ok" | "failed" | "never";
    at: string | null;
    found: number;
    added: number;
    failed: number;
    error: string | null;
    /** Se leyeron enteras todas las secciones activas. */
    complete: boolean;
    cancelled: boolean;
    sections: number;
    sections_total: number;
    pages: number;
    seconds: number;
    /** Quedó a medias: la próxima vez se retoma por donde iba. */
    resume: boolean;
  };
  next_check: string | null;
  /** Cuándo se consultará sola, con hora local («2026-11-20T03:30:00»). */
  next_check_at: string | null;
};

/** Por dónde va la consulta del catálogo en marcha. */
export type ShopCrawl = {
  store: string | null;
  store_name: string | null;
  /** Leyendo el catálogo · eligiendo las mejores · bajando fichas y fotos. */
  phase: "catalogo" | "eligiendo" | "propuestas";
  store_index: number;
  stores_total: number;
  section: string | null;
  section_page: number;
  section_pages: number | null;
  sections_done: number;
  sections_total: number;
  pages: number;
  products: number;
  /** 0-99, nunca retrocede. */
  percent: number;
  /** false: aún no se puede estimar el total (barra indeterminada). */
  known: boolean;
  eta_seconds: number | null;
  night: boolean;
  started_at: string | null;
  cancelling: boolean;
};

export type ShopState = {
  stores: ShopStore[];
  /** Hay una consulta del catálogo o un «Ver más» en marcha, y cuál de los dos. */
  running: boolean;
  job: "consulta" | "mas" | null;
  /** La consulta del catálogo en marcha, con su avance. */
  crawl: ShopCrawl | null;
  /** Se están reponiendo propuestas de un filtro que se quedó vacío. */
  refilling: ShopFilter | null;
  /** A qué hora (HH:MM, local) se hace la consulta automática. */
  night_time: string;
  /** El reparto de la semana: por día (lunes = 0), las claves de las tiendas que tocan. */
  week: string[][];
  /** Tiendas que se consultan como mucho en una noche, y de ellas, pesadas. */
  per_night: number;
  heavy_per_night: number;
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
  /** El filtro se ha quedado vacío y se están trayendo más de eso en segundo plano. */
  refilling: boolean;
  /** Las que vienen detrás de `item` (la pila de tarjetas). */
  queue: ShopItem[];
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

// Para ver las cargas (skeletons) con calma al probar: abrir la app una vez con `?lento=1` retrasa
// cada petición de lectura; `?lento=0` lo quita. Solo afecta a ese navegador.
const SLOW_KEY = "armario-lento";
try {
  const wanted = new URLSearchParams(window.location.search).get("lento");
  if (wanted === "1") window.sessionStorage.setItem(SLOW_KEY, "1");
  if (wanted === "0") window.sessionStorage.removeItem(SLOW_KEY);
} catch {
  /* sin almacenamiento: se queda en normal */
}
const slow = () => {
  try {
    return window.sessionStorage.getItem(SLOW_KEY) === "1";
  } catch {
    return false;
  }
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if ((!init?.method || init.method === "GET") && slow()) await new Promise((done) => setTimeout(done, 1500));
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
  /** Corta la consulta del catálogo en marcha; lo leído se guarda. */
  shopCancel: () => request<ShopState>("/api/shop/refresh/cancel", { method: "POST" }),
  /** La hora de la consulta automática. */
  shopNight: (night_time: string) => request<ShopState>("/api/shop/night", json("PUT", { night_time })),
  shopUndo: (filter?: ShopFilter) => request<ShopNext>(`/api/shop/undo${shopQuery(filter)}`, { method: "POST" }),
  /** Por qué se descartó (opcional). */
  shopReason: (id: number, reason: ShopDiscardReason) =>
    request<void>(`/api/shop/items/${id}/reason`, json("POST", { reason })),
  shopLiked: () => request<ShopItem[]>("/api/shop/liked"),
  /** Unos items concretos como están ahora: para ver si ya ha llegado la foto que faltaba (`photo_pending`). */
  shopItems: (ids: number[]) => request<ShopLookupItem[]>(`/api/shop/items?ids=${ids.join(",")}`),
  /** El buscador: una referencia, un enlace de producto o texto. Tarda unos segundos (habla con la tienda). */
  shopLookup: (query: string) => request<ShopLookupItem[]>("/api/shop/lookup", json("POST", { query })),
  /** Rellena los colores de un item que aún no los sabe (pregunta a la tienda una sola vez). */
  shopColors: (id: number) => request<ShopLookupItem>(`/api/shop/items/${id}/colors`, { method: "POST" }),
  /** Elegir otro color: devuelve el item de ese color. Si no se tenía, tarda unos segundos (lo trae de la tienda). */
  shopColor: (id: number, productRef: string) =>
    request<ShopLookupItem>(`/api/shop/items/${id}/color`, json("POST", { product_ref: productRef })),
  shopMatches: (id: number) => request<ShopMatches>(`/api/shop/items/${id}/matches`),
  shopRemove: (id: number) => request<void>(`/api/shop/items/${id}`, { method: "DELETE" }),
  /** `ordered`: «La he pedido», entra en el armario como pendiente de llegar. */
  shopBought: (id: number, size: string | null, ordered = false) =>
    request<{ garment_id: number; analyzed: boolean }>(
      `/api/shop/items/${id}/bought`,
      json("POST", { size, ordered }),
    ),
  today: () => request<Today>("/api/today"),
  todayNext: (action: "otra" | "pasar") => request<Today>("/api/today/next", json("POST", { action })),
  todayChoose: () => request<Today>("/api/today/choose", { method: "POST" }),
  todayUnchoose: () => request<Today>("/api/today/unchoose", { method: "POST" }),
  garments: () => request<Garment[]>("/api/garments"),
  garment: (id: number) => request<Garment>(`/api/garments/${id}`),
  updateGarment: (id: number, changes: Partial<GarmentFields> & { favorite?: boolean; in_laundry?: boolean; on_order?: boolean }) =>
    request<Garment>(`/api/garments/${id}`, json("PATCH", changes)),
  /** Codex redibuja una foto ya subida como foto de tienda y devuelve la nueva. Tarda. Para
   *  rehacerla: `feedback` (qué salió mal) y `previous` (el intento anterior). */
  studio: (body: {
    photo: string;
    view: "front" | "back" | "extra";
    kind: "ropa" | "calzado";
    others: { view: "front" | "back" | "extra"; photo: string }[];
    feedback?: string | null;
    previous?: string | null;
  }) => request<Photo>("/api/photos/studio", json("POST", body)),
  studioApply: (id: number, photos: Partial<Record<"front" | "back" | "extra", string>>) =>
    request<Garment>(`/api/garments/${id}/studio/apply`, json("POST", photos)),
  discardPhotos: (ids: string[]) => request<void>("/api/photos/discard", json("POST", { ids })),
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
