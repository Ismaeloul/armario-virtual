import { useEffect, useRef, useState } from "react";
import { cap, t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Garment } from "../lib/api";
import { inputClass, PrimaryButton, SecondaryButton } from "./Controls";
import { BottomSheet } from "./BottomSheet";
import { Icon } from "./Icon";
import { FadeImg } from "./Skeleton";
import { StudioReview, type StudioView } from "./StudioReview";

/**
 * «Fotos de tienda» en la Ficha, para las prendas cuyas fotos (o alguna de ellas) siguen siendo las de
 * la cámara: Codex las redibuja todas a la vez, se compara cada una con la original y solo las que
 * llevan el visto bueno sustituyen a la foto. Las de la cámara se guardan.
 */
export function StudioCard({ garment, onChange }: { garment: Garment; onChange: (g: Garment) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const accepted = useRef<Partial<Record<StudioView, string>>>({});
  const pending = (["pair", "front", "back", "extra"] as const).filter(
    (v) => garment[`photo_${v}`] && !garment.photos_edited_views.includes(v),
  );
  // Las de tienda (Compras) ya son fotos de producto, y lo ya redibujado no se repite.
  if (garment.store_name || pending.length === 0) return null;

  const apply = () => {
    setBusy(true);
    setError(null);
    api
      .studioApply(garment.id, accepted.current)
      .then((g) => {
        accepted.current = {};
        setCount(0);
        setOpen(false);
        onChange(g);
      })
      .catch((e) => setError(e instanceof ApiError && e.message ? e.message : t.comun.errorRed))
      .finally(() => setBusy(false));
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line bg-card-2 p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-control text-text-2">
          <Icon name="auto_awesome" size={22} />
        </span>
        <div>
          <p className="font-display text-lg font-semibold leading-6">{t.ficha.estudio.titulo}</p>
          <p className="mt-0.5 text-xs text-text-2">{t.ficha.estudio.texto}</p>
        </div>
      </div>
      {open ? (
        <>
          <StudioReview
            photos={Object.fromEntries(pending.map((v) => [v, garment[`photo_${v}`]!]))}
            // Las vistas que ya son de Codex van solo de referencia, para que no confunda delante y detrás.
            references={Object.fromEntries(
              (["pair", "front", "back", "extra"] as const)
                .filter((v) => garment[`photo_${v}`] && !pending.includes(v))
                .map((v) => [v, garment[`photo_${v}`]!]),
            )}
            kind={garment.category === "calzado" ? "calzado" : "ropa"}
            onAccepted={(ids) => {
              accepted.current = ids;
              setCount(Object.keys(ids).length);
            }}
          />
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <PrimaryButton disabled={busy || count === 0} onClick={apply}>
            <Icon name="check_circle" size={20} />
            {t.ficha.estudio.usar(count)}
          </PrimaryButton>
          <SecondaryButton disabled={busy} onClick={() => setOpen(false)}>
            {t.comun.cancelar}
          </SecondaryButton>
        </>
      ) : (
        <SecondaryButton onClick={() => setOpen(true)}>
          <Icon name="auto_awesome" size={18} />
          {t.ficha.estudio.boton}
        </SecondaryButton>
      )}
    </div>
  );
}

/**
 * «Pareja»: la otra mitad de un conjunto (la sudadera y el pantalón de un chándal). Hoy puede
 * proponerlas por separado, pero juntas compiten con ventaja.
 */
export function PairCard({ garment, onChange }: { garment: Garment; onChange: (g: Garment) => void }) {
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const set = (pairId: number | null) => {
    setBusy(true);
    setError(false);
    api
      .setPair(garment.id, pairId)
      .then((g) => {
        setPicking(false);
        onChange(g);
      })
      .catch(() => setError(true))
      .finally(() => setBusy(false));
  };

  // Los conjuntos son de ropa (arriba y abajo): el calzado no lleva pareja.
  if (garment.category === "calzado") return null;

  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-display text-lg font-semibold">{t.ficha.pareja.titulo}</h3>
      {garment.pair ? (
        <div className="flex items-center gap-3 rounded-xl border border-line bg-card-2 p-2.5">
          <FadeImg
            src={mediaUrl(garment.pair.photo.thumb_url)}
            alt=""
            className="h-16 w-14 shrink-0 rounded-lg object-cover"
          />
          <div className="min-w-0 flex-1">
            <span className="label-caps text-text-2">{cap(garment.pair.type)}</span>
            <p className="truncate text-sm font-medium">{garment.pair.name}</p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => set(null)}
            className="min-h-11 shrink-0 px-2 text-xs font-medium text-text-2 underline disabled:opacity-40"
          >
            {t.ficha.pareja.quitar}
          </button>
        </div>
      ) : (
        <>
          <p className="text-xs text-text-2">{t.ficha.pareja.texto}</p>
          <SecondaryButton disabled={busy} onClick={() => setPicking(true)}>
            <Icon name="add" size={18} />
            {t.ficha.pareja.anadir}
          </SecondaryButton>
        </>
      )}
      {error && <p className="text-center text-xs text-danger">{t.comun.errorRed}</p>}
      {picking && <PairPicker garment={garment} busy={busy} onPick={set} onClose={() => setPicking(false)} />}
    </div>
  );
}

function PairPicker({
  garment,
  busy,
  onPick,
  onClose,
}: {
  garment: Garment;
  busy: boolean;
  onPick: (id: number) => void;
  onClose: () => void;
}) {
  const [all, setAll] = useState<Garment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.garments().then(setAll).catch(() => setFailed(true));
  }, []);

  // La pareja es de otra parte del cuerpo: la de arriba con la de abajo.
  const words = query.trim().toLowerCase();
  const options = (all ?? []).filter(
    (g) =>
      g.id !== garment.id &&
      g.category !== garment.category &&
      g.category !== "calzado" &&
      (!words || `${g.name} ${g.type} ${g.brand ?? ""}`.toLowerCase().includes(words)),
  );

  return (
    <BottomSheet
      label={t.ficha.pareja.elegir}
      onClose={onClose}
      locked={busy}
      header={
        <div className="flex flex-col gap-3 px-5 pb-3">
          <h2 className="font-display text-lg font-semibold tracking-tight">{t.ficha.pareja.elegir}</h2>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.ficha.pareja.buscar}
            className={inputClass}
          />
        </div>
      }
    >
      <div className="grid grid-cols-3 gap-2.5 px-5">
        {failed && <p className="col-span-3 py-6 text-center text-sm text-text-2">{t.comun.errorRed}</p>}
        {all && options.length === 0 && (
          <p className="col-span-3 py-6 text-center text-sm text-text-3">{t.ficha.pareja.ninguna}</p>
        )}
        {options.map((g) => (
          <button
            key={g.id}
            type="button"
            disabled={busy}
            onClick={() => onPick(g.id)}
            className="card flex flex-col p-1.5 text-left active:scale-[0.97] disabled:opacity-40"
          >
            <FadeImg
              src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
              alt=""
              loading="lazy"
              className="aspect-[3/4] w-full rounded-lg bg-card-2 object-cover"
            />
            <span className="mt-1.5 line-clamp-2 px-0.5 text-[11px] font-medium leading-tight">{g.name}</span>
          </button>
        ))}
      </div>
    </BottomSheet>
  );
}
