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
  photo_label: Photo | null;
  draft: Draft | null;
  provider: string | null;
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
  ai_providers: string[];
  themes: string[];
};

export type Settings = {
  theme: string;
  ai_provider: string;
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
  codexLoginStart: () => request<CodexLogin>("/api/ai/codex/login", { method: "POST" }),
  codexLoginStatus: () => request<CodexLogin>("/api/ai/codex/login"),
  codexLoginCancel: () => request<void>("/api/ai/codex/login", { method: "DELETE" }),
  codexLogout: () => request<AIStatus>("/api/ai/codex/logout", { method: "POST" }),
  codexUsage: () => request<CodexUsage>("/api/ai/codex/usage"),
  aiStatus: () => request<AIStatus>("/api/ai/status"),
  /** La clave se envía al servidor y no vuelve nunca. Cadena vacía = borrarla. */
  saveClaudeKey: (key: string) => request<Settings>("/api/settings", json("PATCH", { anthropic_api_key: key })),
  updateSettings: (changes: Partial<Settings>) => request<Settings>("/api/settings", json("PATCH", changes)),
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
    label?: File;
    frontId?: string;
    backId?: string;
    labelId?: string;
    skipAi?: boolean;
  }) => {
    const form = new FormData();
    if (opts.front) form.append("front", opts.front);
    if (opts.back) form.append("back", opts.back);
    if (opts.label) form.append("label", opts.label);
    if (opts.frontId) form.append("front_id", opts.frontId);
    if (opts.backId) form.append("back_id", opts.backId);
    if (opts.labelId) form.append("label_id", opts.labelId);
    if (opts.skipAi) form.append("skip_ai", "true");
    return request<Analysis>("/api/garments/analyze", { method: "POST", body: form });
  },

  createGarment: (
    body: GarmentFields & {
      photo_front: string;
      photo_back: string | null;
      photo_label: string | null;
      ai_provider: string | null;
      ai_confidence: number | null;
      ai_draft: Draft | null;
    },
  ) => request<Garment>("/api/garments", json("POST", body)),
};
