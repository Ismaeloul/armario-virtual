import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PrimaryButton } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { ORDER, OutfitPicker } from "../components/OwnOutfits";
import { FadeImg, ListSkeleton, stagger } from "../components/Skeleton";
import { ZoomViewer } from "../components/ZoomViewer";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Catalog, type Garment, type OwnOutfit } from "../lib/api";

/** De dentro afuera, como se viste uno: arriba, capa, abajo y calzado. */
const sorted = (garments: Garment[]) =>
  [...garments].sort((a, b) => ORDER.indexOf(a.category) - ORDER.indexOf(b.category));

/**
 * «Tus outfits», dentro del Armario: los que el usuario ha montado él mismo o ha guardado desde Gustos
 * con «Me gusta y guardar». Cada uno cuenta el doble para el algoritmo.
 */
export default function TusOutfits() {
  const [list, setList] = useState<OwnOutfit[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [picking, setPicking] = useState(false);
  const [open, setOpen] = useState<OwnOutfit | null>(null);

  const load = () => {
    setFailed(false);
    api.tasteOwn().then(setList).catch(() => setFailed(true));
  };
  useEffect(() => {
    load();
    api.catalog().then(setCatalog).catch(() => undefined);
  }, []);

  return (
    <>
      <BackHeader title={t.armario.outfits.cabecera} />
      <Screen withNav={false}>
        <div className="flex min-w-0 animate-slide flex-col gap-4">
          <section>
            <span className="label-caps text-text-2">{t.armario.outfits.etiqueta}</span>
            <h2 className="mt-0.5 font-display text-[32px] font-semibold leading-[38px] tracking-tight">
              {t.armario.outfits.titulo}
            </h2>
            <p className="mt-0.5 text-sm text-text-2">
              {list && list.length > 0 ? `${t.armario.outfits.n(list.length)} · ` : ""}
              {t.armario.outfits.texto}
            </p>
          </section>

          <PrimaryButton onClick={() => setPicking(true)}>
            <Icon name="add" size={20} />
            {t.armario.outfits.anadir}
          </PrimaryButton>

          {failed && (
            <div className="card flex flex-col items-center gap-3 p-6 text-center">
              <p className="text-sm text-text-2">{t.comun.errorRed}</p>
              <button type="button" onClick={load} className="min-h-11 px-3 text-sm font-semibold text-primary">
                {t.comun.reintentar}
              </button>
            </div>
          )}
          {!failed && !list && <ListSkeleton rows={3} />}

          {list && list.length === 0 && (
            <div className="card flex flex-col items-center gap-2 p-8 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-card-2 text-primary">
                <Icon name="checkroom" size={28} />
              </span>
              <h3 className="font-display text-lg font-semibold tracking-tight">{t.armario.outfits.vacioTitulo}</h3>
              <p className="text-sm text-text-2">{t.armario.outfits.vacioTexto}</p>
            </div>
          )}

          {list && list.length > 0 && (
            <ul className="flex min-w-0 flex-col gap-3">
              {list.map((outfit, i) => (
                <li key={outfit.id} style={stagger(i)} className="min-w-0 animate-enter">
                  <button
                    type="button"
                    aria-label={t.armario.outfits.verOutfit(i + 1)}
                    onClick={() => setOpen(outfit)}
                    className="card flex w-full min-w-0 max-w-full flex-col gap-2.5 overflow-hidden p-3 text-left active:scale-[0.99]"
                  >
                    <div className="flex w-full min-w-0 gap-2 overflow-x-auto">
                      {sorted(outfit.garments).map((g) => (
                        <FadeImg
                          key={g.id}
                          src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                          alt={g.name}
                          className="h-28 w-[5.25rem] shrink-0 rounded-xl bg-card-2 object-cover"
                        />
                      ))}
                    </div>
                    <div className="flex items-center justify-between gap-2 px-0.5">
                      <span className="truncate text-xs text-text-2">
                        {sorted(outfit.garments)
                          .map((g) => cap(g.type))
                          .join(" · ")}
                      </span>
                      <span className="label-caps shrink-0 rounded-full bg-chip px-2 py-0.5 text-on-chip">
                        {t.armario.outfits.afinidad(outfit.affinity)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Screen>

      {picking && (
        <OutfitPicker
          catalog={catalog}
          onClose={() => setPicking(false)}
          onSaved={() => {
            setPicking(false);
            load();
          }}
        />
      )}
      {open && (
        <OutfitCard
          outfit={open}
          catalog={catalog}
          onClose={() => setOpen(null)}
          onRemoved={() => {
            setOpen(null);
            setList((all) => all?.filter((o) => o.id !== open.id) ?? null);
          }}
        />
      )}
    </>
  );
}

/** La tarjeta de un outfit: sus prendas como en Hoy, cada una enlazada a su ficha. */
function OutfitCard({
  outfit,
  catalog,
  onClose,
  onRemoved,
}: {
  outfit: OwnOutfit;
  catalog: Catalog | null;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<Garment | null>(null);

  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !viewing && onClose();
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, viewing]);

  const remove = () => {
    setBusy(true);
    setError(null);
    api
      .tasteOwnDelete(outfit.id)
      .then(onRemoved)
      .catch(() => {
        setError(t.comun.errorRed);
        setBusy(false);
      });
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade items-end justify-center bg-scrim backdrop-blur-[2px]"
      style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 2.5rem)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.armario.outfits.titulo}
        className="flex max-h-full w-full max-w-md animate-sheet flex-col rounded-t-3xl border border-line bg-bg"
      >
        <div className="flex items-center justify-between gap-2 py-3 pr-2 pl-5">
          <span className="flex items-center gap-1.5 rounded-full bg-chip px-3 py-1 text-on-chip">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            <span className="label-caps">{t.armario.outfits.afinidad(outfit.affinity)}</span>
          </span>
          <button
            type="button"
            aria-label={t.armario.outfits.cerrar}
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center active:opacity-60"
          >
            <Icon name="close" size={22} />
          </button>
        </div>

        <div
          className="flex min-h-0 flex-col gap-3 overflow-y-auto px-5"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1.25rem)" }}
        >
          {sorted(outfit.garments).map((g, i) => (
            <div
              key={g.id}
              style={stagger(i, 60)}
              className="flex animate-enter items-center gap-3.5 rounded-2xl border border-line bg-card-2 p-2.5"
            >
              <button
                type="button"
                aria-label={t.gustos.verFoto(g.name)}
                onClick={() => setViewing(g)}
                className="shrink-0 cursor-zoom-in active:opacity-80"
              >
                <FadeImg
                  src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                  alt=""
                  className="h-24 w-20 rounded-xl object-cover"
                />
              </button>
              <Link to={`/prenda/${g.id}`} className="min-w-0 flex-1 active:opacity-70">
                <span className="label-caps text-text-2">{catalog?.categories[g.category] ?? ""}</span>
                <h4 className="truncate text-base font-medium">{g.name}</h4>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="flex items-center gap-1 rounded-full bg-control px-2 py-0.5 text-[11px] text-text-2">
                    <span
                      className="h-2 w-2 rounded-full border border-text/10"
                      style={{ background: g.color_primary.hex }}
                    />
                    {cap(g.color_primary.name)}
                  </span>
                  <span className="rounded-full bg-control px-2 py-0.5 text-[11px] text-text-2">{cap(g.type)}</span>
                </div>
              </Link>
              <Icon name="chevron_right" size={18} className="shrink-0 text-text-3" />
            </div>
          ))}

          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="mt-1 flex h-11 items-center justify-center gap-1.5 text-xs font-medium text-danger active:opacity-60"
          >
            <Icon name="delete_icon" size={18} />
            {t.armario.outfits.quitar}
          </button>
        </div>
      </div>

      {viewing && (
        <ZoomViewer
          photos={(
            [
              [viewing.photo_pair, t.ficha.juntas],
              [viewing.photo_front, viewing.category === "calzado" ? t.ficha.lateral : t.ficha.delante],
              [viewing.photo_back, viewing.category === "calzado" ? t.ficha.frente : t.ficha.detras],
              [viewing.photo_extra, t.ficha.otroLado],
            ] as const
          ).flatMap(([photo, label]) => (photo ? [{ label, url: mediaUrl(photo.url) }] : []))}
          closeLabel={t.armario.outfits.cerrar}
          onClose={() => setViewing(null)}
        />
      )}
      <ConfirmDialog
        open={confirming}
        title={t.armario.outfits.quitarTitulo}
        text={t.armario.outfits.quitarTexto}
        confirmLabel={t.armario.outfits.quitar}
        busyLabel={t.armario.outfits.quitando}
        busy={busy}
        error={error}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </div>,
    document.body,
  );
}
