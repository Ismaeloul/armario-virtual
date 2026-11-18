import { useEffect, useRef, useState } from "react";
import { t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Photo } from "../lib/api";
import { inputClass, RotateButton } from "./Controls";
import { Icon } from "./Icon";
import { FadeImg, Skeleton } from "./Skeleton";
import { ZoomViewer } from "./ZoomViewer";

export type StudioView = "front" | "back" | "extra";

type Slot = {
  status: "wait" | "working" | "done" | "error";
  edited: Photo | null;
  verdict: "ok" | "no" | null; // el visto bueno, o que no ha quedado bien
  feedback: string;
  note: string | null; // lo que se le ha pedido corregir en el intento en marcha
  error: string | null;
};

const EMPTY: Slot = { status: "wait", edited: null, verdict: null, feedback: "", note: null, error: null };

/**
 * Fotos de tienda al añadir una prenda: junto a cada foto hecha con el móvil sale la que redibuja Codex
 * (fondo liso, prenda bien colocada). Con el visto bueno se usa la de Codex; si no ha quedado bien se
 * le explica qué ha fallado y la rehace. Sin visto bueno, la prenda se guarda con la foto original.
 * Las fotos se editan de una en una. `onAccepted` avisa de qué editadas tienen el visto bueno.
 */
export function StudioReview({
  photos,
  kind,
  onRotate,
  onAccepted,
}: {
  photos: Partial<Record<StudioView, Photo>>;
  kind: "ropa" | "calzado";
  onRotate: (view: StudioView) => void;
  onAccepted: (accepted: Partial<Record<StudioView, string>>) => void;
}) {
  const views = (["front", "back", "extra"] as const).filter((v) => photos[v]);
  const [slots, setSlots] = useState<Partial<Record<StudioView, Slot>>>({});
  // La foto abierta en grande para mirarla de cerca: de qué vista y cuál de las dos (0 la tuya, 1 la de Codex).
  const [zoom, setZoom] = useState<{ view: StudioView; index: number } | null>(null);
  const slot = (view: StudioView): Slot => slots[view] ?? EMPTY;
  const patch = (view: StudioView, changes: Partial<Slot>) =>
    setSlots((all) => ({ ...all, [view]: { ...(all[view] ?? EMPTY), ...changes } }));

  // Todo lo generado en esta pantalla: lo que no acabe en la prenda se tira al salir.
  const made = useRef<string[]>([]);
  const kept = useRef<string[]>([]);
  useEffect(
    () => () => {
      const unused = made.current.filter((id) => !kept.current.includes(id));
      if (unused.length) api.discardPhotos(unused).catch(() => undefined);
    },
    [],
  );

  // Si se gira (o cambia) la foto original, la editada de esa vista ya no vale: se vuelve a hacer.
  const sources = useRef<Partial<Record<StudioView, string>>>({});
  useEffect(() => {
    for (const view of views) {
      const id = photos[view]!.id;
      if (sources.current[view] && sources.current[view] !== id) patch(view, { ...EMPTY });
      sources.current[view] = id;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos.front?.id, photos.back?.id, photos.extra?.id]);

  // De una en una: la primera que esté esperando, si no hay ninguna en marcha.
  const busy = views.some((v) => slot(v).status === "working");
  const next = busy ? undefined : views.find((v) => slot(v).status === "wait");
  useEffect(() => {
    if (!next) return;
    const source = photos[next]!;
    const current = slot(next);
    patch(next, { status: "working", error: null });
    api
      .studio({
        photo: source.id,
        view: next,
        kind,
        others: views.filter((v) => v !== next).map((v) => ({ view: v, photo: photos[v]!.id })),
        feedback: current.note,
        previous: current.note && current.edited ? current.edited.id : null,
      })
      .then((edited) => {
        made.current.push(edited.id);
        if (sources.current[next] !== source.id) return; // la original cambió mientras tanto
        patch(next, { status: "done", edited, verdict: null, feedback: "", note: null });
      })
      .catch((e) => {
        if (sources.current[next] !== source.id) return;
        patch(next, {
          status: "error",
          error: e instanceof ApiError && e.message ? e.message : t.comun.errorRed,
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [next]);

  // Qué editadas tienen el visto bueno.
  const accepted = Object.fromEntries(
    views.filter((v) => slot(v).verdict === "ok" && slot(v).edited).map((v) => [v, slot(v).edited!.id]),
  ) as Partial<Record<StudioView, string>>;
  const key = JSON.stringify(accepted);
  useEffect(() => {
    kept.current = Object.values(accepted);
    onAccepted(accepted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const label = (view: StudioView) =>
    kind === "calzado"
      ? { front: t.nueva.lateral, back: t.nueva.frente, extra: t.nueva.otroLado }[view]
      : { front: t.nueva.delante, back: t.nueva.detras, extra: t.nueva.otroLado }[view];

  const chip = "label-caps absolute left-2 top-2 rounded-full border border-line bg-card/90 px-2 py-0.5 backdrop-blur-md";
  const choice = (on: boolean) =>
    `flex h-11 items-center justify-center gap-1.5 rounded-xl border text-xs font-medium transition-colors duration-200 active:scale-[0.98] ${
      on ? "border-primary bg-primary text-on-primary" : "border-line bg-control text-text"
    }`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2.5">
        <Icon name="auto_awesome" size={18} className="mt-0.5 shrink-0 text-primary" />
        <p className="text-xs text-text-2">{t.nueva.estudio.texto}</p>
      </div>

      {views.map((view) => {
        const s = slot(view);
        const source = photos[view]!;
        return (
          <div key={view} className="flex animate-enter flex-col gap-2">
            <span className="label-caps text-text-2">{label(view)}</span>
            <div className="grid grid-cols-2 gap-2">
              <div className="relative overflow-hidden rounded-xl border border-line bg-card-2">
                <button
                  type="button"
                  aria-label={t.nueva.estudio.ampliar(t.nueva.estudio.tuya)}
                  onClick={() => setZoom({ view, index: 0 })}
                  className="block w-full cursor-zoom-in active:opacity-80"
                >
                  <FadeImg key={source.id} src={mediaUrl(source.url)} alt="" className="aspect-[3/4] w-full object-cover" />
                </button>
                <span className={`${chip} pointer-events-none`}>{t.nueva.estudio.tuya}</span>
                <RotateButton className="absolute right-2 top-2" onClick={() => onRotate(view)} />
              </div>
              <div className="relative overflow-hidden rounded-xl border border-line bg-card-2">
                {s.status === "done" && s.edited ? (
                  <button
                    type="button"
                    aria-label={t.nueva.estudio.ampliar(t.nueva.estudio.codex)}
                    onClick={() => setZoom({ view, index: 1 })}
                    className="block w-full cursor-zoom-in active:opacity-80"
                  >
                    <FadeImg
                      key={s.edited.id}
                      src={mediaUrl(s.edited.url)}
                      alt=""
                      className="aspect-[3/4] w-full object-cover"
                    />
                  </button>
                ) : s.status === "error" ? (
                  <div className="flex aspect-[3/4] w-full flex-col items-center justify-center gap-2 p-3 text-center">
                    <Icon name="error" size={24} className="text-danger" />
                    <p className="text-[11px] leading-tight text-text-2">{s.error}</p>
                    <button
                      type="button"
                      onClick={() => patch(view, { status: "wait", error: null })}
                      className="min-h-11 px-2 text-xs font-semibold text-primary"
                    >
                      {t.comun.reintentar}
                    </button>
                  </div>
                ) : (
                  <div role="status" className="relative aspect-[3/4] w-full">
                    <Skeleton className="absolute inset-0 rounded-none" />
                    <p className="shimmer-text absolute inset-x-2 bottom-3 text-center text-[11px] font-medium">
                      {s.status === "working" ? t.nueva.estudio.editando : t.nueva.estudio.enCola}
                    </p>
                  </div>
                )}
                <span className={`${chip} pointer-events-none`}>{t.nueva.estudio.codex}</span>
              </div>
            </div>

            {s.status === "done" && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    aria-pressed={s.verdict === "ok"}
                    onClick={() => patch(view, { verdict: s.verdict === "ok" ? null : "ok" })}
                    className={choice(s.verdict === "ok")}
                  >
                    <Icon name="check" size={18} />
                    {t.nueva.estudio.vale}
                  </button>
                  <button
                    type="button"
                    aria-pressed={s.verdict === "no"}
                    onClick={() => patch(view, { verdict: s.verdict === "no" ? null : "no" })}
                    className={choice(s.verdict === "no")}
                  >
                    <Icon name="close" size={18} />
                    {t.nueva.estudio.noVale}
                  </button>
                </div>
                {s.verdict === "no" && (
                  <div className="flex animate-enter flex-col gap-2">
                    <textarea
                      rows={2}
                      maxLength={400}
                      value={s.feedback}
                      onChange={(e) => patch(view, { feedback: e.target.value })}
                      placeholder={t.nueva.estudio.queFalla}
                      className={`${inputClass} resize-none`}
                    />
                    <button
                      type="button"
                      disabled={!s.feedback.trim()}
                      onClick={() =>
                        // Se queda la editada a la vista (va de «intento anterior») hasta que llegue la nueva.
                        patch(view, { status: "wait", verdict: null, note: s.feedback.trim() })
                      }
                      className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-primary text-xs font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
                    >
                      <Icon name="refresh" size={18} />
                      {t.nueva.estudio.rehacer}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}

      <p className="text-xs text-text-3">{t.nueva.estudio.aviso}</p>

      {/* En grande y con zoom, encima del formulario: la tuya y, si ya está, la de Codex para comparar. */}
      {zoom && photos[zoom.view] && (
        <ZoomViewer
          photos={[
            { label: t.nueva.estudio.tuya, url: mediaUrl(photos[zoom.view]!.url) },
            ...(slot(zoom.view).status === "done" && slot(zoom.view).edited
              ? [{ label: t.nueva.estudio.codex, url: mediaUrl(slot(zoom.view).edited!.url) }]
              : []),
          ]}
          start={zoom.index}
          closeLabel={t.nueva.estudio.cerrar}
          onClose={() => setZoom(null)}
        />
      )}
    </div>
  );
}
