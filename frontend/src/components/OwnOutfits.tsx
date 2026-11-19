import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Catalog, type Garment, type Taste } from "../lib/api";
import { PrimaryButton, SecondaryButton } from "./Controls";
import { Icon } from "./Icon";
import { FadeImg } from "./Skeleton";

// El orden en que se montan: de dentro afuera, como se viste uno.
export const ORDER = ["parte_superior", "capa_exterior", "parte_inferior", "calzado"];

/** Montar un outfit a mano con las prendas del armario (para «Tus outfits»). */
export function OutfitPicker({
  catalog,
  onClose,
  onSaved,
}: {
  catalog: Catalog | null;
  onClose: () => void;
  onSaved: (state: Taste) => void;
}) {
  const [all, setAll] = useState<Garment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [chosen, setChosen] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.garments().then(setAll).catch(() => setFailed(true));
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
    };
  }, []);

  const byId = new Map((all ?? []).map((g) => [g.id, g]));
  const picked = chosen.map((id) => byId.get(id)).filter((g): g is Garment => !!g);
  const has = (category: string) => picked.some((g) => g.category === category);
  const complete = has("parte_superior") && has("parte_inferior");

  // Abajo y calzado, uno solo: elegir otro sustituye al anterior. Arriba y capa, varios.
  const toggle = (g: Garment) =>
    setChosen((ids) => {
      if (ids.includes(g.id)) return ids.filter((id) => id !== g.id);
      const single = g.category === "parte_inferior" || g.category === "calzado";
      const kept = single ? ids.filter((id) => byId.get(id)?.category !== g.category) : ids;
      return [...kept, g.id];
    });

  const save = () => {
    setBusy(true);
    setError(null);
    api
      .tasteOwnAdd(chosen)
      .then(onSaved)
      .catch((e) => {
        setError(e instanceof ApiError && e.status < 500 ? e.message : t.comun.errorRed);
        setBusy(false);
      });
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade items-end justify-center bg-scrim backdrop-blur-[2px]"
      style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 2.5rem)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.armario.outfits.elegir}
        className="flex max-h-full w-full max-w-md animate-sheet flex-col rounded-t-3xl border border-line bg-bg"
      >
        <div className="flex items-center justify-between gap-2 py-3 pr-2 pl-5">
          <h2 className="font-display text-lg font-semibold tracking-tight">{t.armario.outfits.elegir}</h2>
          <button
            type="button"
            aria-label={t.comun.cancelar}
            disabled={busy}
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center active:opacity-60"
          >
            <Icon name="close" size={22} />
          </button>
        </div>
        <p className="px-5 pb-2 text-xs text-text-2">{t.armario.outfits.elegirTexto}</p>

        <div className="min-h-0 overflow-y-auto px-5 pb-3">
          {failed && <p className="py-6 text-center text-sm text-text-2">{t.comun.errorRed}</p>}
          {ORDER.map((category) => {
            const items = (all ?? []).filter((g) => g.category === category);
            if (!items.length) return null;
            return (
              <div key={category} className="mb-4">
                <span className="label-caps text-text-2">{catalog?.categories[category] ?? category}</span>
                <div className="mt-1.5 grid grid-cols-4 gap-2">
                  {items.map((g) => {
                    const on = chosen.includes(g.id);
                    return (
                      <button
                        key={g.id}
                        type="button"
                        aria-pressed={on}
                        aria-label={g.name}
                        onClick={() => toggle(g)}
                        className={`relative overflow-hidden rounded-xl border-2 transition-colors duration-200 active:scale-[0.97] ${
                          on ? "border-primary" : "border-transparent"
                        }`}
                      >
                        <FadeImg
                          src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                          alt=""
                          loading="lazy"
                          className="aspect-[3/4] w-full bg-card-2 object-cover"
                        />
                        {on && (
                          <span className="absolute top-1 right-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-on-primary">
                            <Icon name="check" size={13} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div
          className="flex flex-col gap-2 border-t border-line px-5 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1rem)" }}
        >
          {picked.length > 0 && (
            <div className="flex gap-1.5 overflow-x-auto">
              {ORDER.flatMap((c) => picked.filter((g) => g.category === c)).map((g) => (
                <FadeImg
                  key={g.id}
                  src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                  alt={g.name}
                  className="h-12 w-9 shrink-0 rounded-md object-cover"
                />
              ))}
            </div>
          )}
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          {picked.length >= 2 && !complete && <p className="text-xs text-text-2">{t.armario.outfits.falta}</p>}
          <PrimaryButton disabled={busy || picked.length < 2 || !complete} onClick={save}>
            {busy ? t.armario.outfits.guardando : t.armario.outfits.guardar(picked.length)}
          </PrimaryButton>
          <SecondaryButton disabled={busy} onClick={onClose}>
            {t.comun.cancelar}
          </SecondaryButton>
        </div>
      </div>
    </div>,
    document.body,
  );
}
