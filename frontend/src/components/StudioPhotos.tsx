import { useEffect, useRef, useState } from "react";
import { t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Garment, type Photo } from "../lib/api";
import { PrimaryButton, SecondaryButton } from "./Controls";
import { Icon } from "./Icon";
import { FadeImg, Skeleton } from "./Skeleton";

type View = "front" | "back" | "extra";
type Pair = { view: View; before: Photo; after: Photo };

/**
 * «Editar foto con Codex»: redibuja las fotos hechas con el móvil como fotos de tienda (fondo liso,
 * prenda bien colocada). Opción temporal para probarlo: se enseña el antes y el después y no se cambia
 * nada hasta aceptar. Las fotos de la cámara se guardan y se puede volver a ellas.
 */
export function StudioPhotos({ garment, onChange }: { garment: Garment; onChange: (g: Garment) => void }) {
  const views = (["front", "back", "extra"] as const).filter((v) => garment[`photo_${v}`]);
  const [step, setStep] = useState<{ done: number } | null>(null); // generando: cuántas van
  const [pairs, setPairs] = useState<Pair[] | null>(null); // para revisar
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Lo generado y aún sin dueño: si se sale de la pantalla sin decidir, se tira.
  const pending = useRef<string[]>([]);
  useEffect(
    () => () => {
      if (pending.current.length) api.discardPhotos(pending.current).catch(() => undefined);
    },
    [],
  );

  const message = (e: unknown) => (e instanceof ApiError && e.message ? e.message : t.comun.errorRed);

  const generate = async () => {
    setError(null);
    setStep({ done: 0 });
    const made: Pair[] = [];
    try {
      for (const view of views) {
        const after = await api.studioPhoto(garment.id, view);
        pending.current.push(after.id);
        made.push({ view, before: garment[`photo_${view}`] as Photo, after });
        setStep({ done: made.length });
      }
      setPairs(made);
    } catch (e) {
      setError(message(e));
      // Lo que sí salió se enseña igualmente; si no salió nada, no hay nada que revisar.
      if (made.length) setPairs(made);
    } finally {
      setStep(null);
    }
  };

  const discard = () => {
    api.discardPhotos(pending.current).catch(() => undefined);
    pending.current = [];
    setPairs(null);
    setError(null);
  };

  const apply = () => {
    if (!pairs) return;
    setBusy(true);
    setError(null);
    api
      .studioApply(garment.id, Object.fromEntries(pairs.map((p) => [p.view, p.after.id])))
      .then((g) => {
        pending.current = [];
        setPairs(null);
        onChange(g);
      })
      .catch((e) => setError(message(e)))
      .finally(() => setBusy(false));
  };

  const revert = () => {
    setBusy(true);
    setError(null);
    api
      .studioRevert(garment.id)
      .then(onChange)
      .catch((e) => setError(message(e)))
      .finally(() => setBusy(false));
  };

  const label = (view: View) =>
    garment.category === "calzado"
      ? { front: t.ficha.lateral, back: t.ficha.frente, extra: t.ficha.otroLado }[view]
      : { front: t.ficha.delante, back: t.ficha.detras, extra: t.ficha.otroLado }[view];

  return (
    <div className="flex animate-enter flex-col gap-3 rounded-xl border border-line bg-card-2 p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-control text-text-2">
          <Icon name="auto_awesome" size={22} />
        </span>
        <div>
          <p className="font-display text-lg font-semibold leading-6">{t.ficha.estudio.titulo}</p>
          <p className="mt-0.5 text-xs text-text-2">
            {garment.photos_edited ? t.ficha.estudio.editadas : t.ficha.estudio.texto}
          </p>
        </div>
      </div>

      {step && (
        <div role="status" className="flex animate-enter flex-col gap-3">
          <p className="shimmer-text text-sm font-medium">
            {t.ficha.estudio.editando(Math.min(step.done + 1, views.length), views.length)}
          </p>
          <div className="grid grid-cols-2 gap-2">
            <FadeImg
              src={mediaUrl((garment[`photo_${views[Math.min(step.done, views.length - 1)]}`] as Photo).thumb_url)}
              alt=""
              className="aspect-[3/4] w-full rounded-xl object-cover"
            />
            <Skeleton className="aspect-[3/4] w-full" />
          </div>
          <p className="text-xs text-text-3">{t.ficha.estudio.tarda}</p>
        </div>
      )}

      {pairs && !step && (
        <div className="flex animate-enter flex-col gap-3">
          {pairs.map((pair) => (
            <div key={pair.view} className="flex flex-col gap-1.5">
              <span className="label-caps text-text-2">{label(pair.view)}</span>
              <div className="grid grid-cols-2 gap-2">
                {[pair.before, pair.after].map((photo, i) => (
                  <a
                    key={photo.id}
                    href={mediaUrl(photo.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="relative overflow-hidden rounded-xl bg-card"
                  >
                    <FadeImg src={mediaUrl(photo.url)} alt="" className="aspect-[3/4] w-full object-contain" />
                    <span className="label-caps absolute left-2 top-2 rounded-full bg-card/90 px-2 py-0.5 backdrop-blur-md">
                      {i === 0 ? t.ficha.estudio.antes : t.ficha.estudio.despues}
                    </span>
                  </a>
                ))}
              </div>
            </div>
          ))}
          <p className="text-xs text-text-3">{t.ficha.estudio.aviso}</p>
          <PrimaryButton disabled={busy} onClick={apply}>
            <Icon name="check_circle" size={20} />
            {t.ficha.estudio.usar}
          </PrimaryButton>
          <SecondaryButton disabled={busy} onClick={discard}>
            {t.ficha.estudio.descartar}
          </SecondaryButton>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {!step && !pairs && (
        <>
          <SecondaryButton disabled={busy} onClick={generate}>
            <Icon name="auto_awesome" size={18} />
            {garment.photos_edited ? t.ficha.estudio.repetir : t.ficha.estudio.boton}
          </SecondaryButton>
          {garment.photos_edited && (
            <button
              type="button"
              disabled={busy}
              onClick={revert}
              className="h-11 text-xs font-medium text-text-2 underline disabled:opacity-40"
            >
              {t.ficha.estudio.volver}
            </button>
          )}
        </>
      )}
    </div>
  );
}
