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
  in_laundry: boolean;
  favorite: boolean;
  ai_provider: string | null;
  wear_count: number;
  last_worn_on: string | null;
};

export type Draft = GarmentFields & { confidence: number };

export type Analysis = {
  photo_front: Photo;
  photo_back: Photo | null;
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
  updateSettings: (changes: Partial<Settings>) => request<Settings>("/api/settings", json("PATCH", changes)),
  garments: () => request<Garment[]>("/api/garments"),
  garment: (id: number) => request<Garment>(`/api/garments/${id}`),
  updateGarment: (id: number, changes: Partial<GarmentFields> & { favorite?: boolean; in_laundry?: boolean }) =>
    request<Garment>(`/api/garments/${id}`, json("PATCH", changes)),
  deleteGarment: (id: number) => request<void>(`/api/garments/${id}`, { method: "DELETE" }),
  wearGarment: (id: number) => request<Garment>(`/api/garments/${id}/wear`, json("POST", {})),
  clearLaundry: () => request<{ cleared: number }>("/api/laundry/clear", { method: "POST" }),

  /** Sube fotos nuevas o reutiliza las ya subidas (ids) para reintentar el análisis. */
  analyze: (opts: { front?: File; back?: File; frontId?: string; backId?: string; skipAi?: boolean }) => {
    const form = new FormData();
    if (opts.front) form.append("front", opts.front);
    if (opts.back) form.append("back", opts.back);
    if (opts.frontId) form.append("front_id", opts.frontId);
    if (opts.backId) form.append("back_id", opts.backId);
    if (opts.skipAi) form.append("skip_ai", "true");
    return request<Analysis>("/api/garments/analyze", { method: "POST", body: form });
  },

  createGarment: (
    body: GarmentFields & {
      photo_front: string;
      photo_back: string | null;
      ai_provider: string | null;
      ai_confidence: number | null;
    },
  ) => request<Garment>("/api/garments", json("POST", body)),
};
