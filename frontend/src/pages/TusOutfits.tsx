import { useEffect, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PrimaryButton } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { ORDER, OutfitPicker } from "../components/OwnOutfits";
import { FadeImg, ListSkeleton, stagger } from "../components/Skeleton";
import { GarmentSheet } from "../components/GarmentSheet";
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
  // La prenda cuya ficha está abierta en el panel, y el outfit que se va a quitar.
  const [viewing, setViewing] = useState<Garment | null>(null);
  const [removing, setRemoving] = useState<OwnOutfit | null>(null);
  const [busy, setBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const remove = () => {
    if (!removing) return;
    setBusy(true);
    setRemoveError(null);
    api
      .tasteOwnDelete(removing.id)
      .then(() => {
        setList((all) => all?.filter((o) => o.id !== removing.id) ?? null);
        setRemoving(null);
      })
      .catch(() => setRemoveError(t.comun.errorRed))
      .finally(() => setBusy(false));
  };

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
                <li
                  key={outfit.id}
                  style={stagger(i)}
                  className="card flex min-w-0 animate-enter flex-col gap-2.5 overflow-hidden p-3"
                >
                  {/* Cada foto abre directamente la ficha de esa prenda. */}
                  <div className="flex w-full min-w-0 gap-2 overflow-x-auto">
                    {sorted(outfit.garments).map((g) => (
                      <button
                        key={g.id}
                        type="button"
                        aria-label={t.armario.outfits.verPrenda(g.name)}
                        onClick={() => setViewing(g)}
                        className="shrink-0 transition-transform active:scale-[0.96]"
                      >
                        <FadeImg
                          src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                          alt=""
                          className="h-28 w-[5.25rem] rounded-xl bg-card-2 object-cover"
                        />
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 px-0.5">
                    <span className="min-w-0 flex-1 truncate text-xs text-text-2">
                      {sorted(outfit.garments)
                        .map((g) => cap(g.type))
                        .join(" · ")}
                    </span>
                    <span className="label-caps shrink-0 rounded-full bg-chip px-2 py-0.5 text-on-chip">
                      {t.armario.outfits.afinidad(outfit.affinity)}
                    </span>
                    <button
                      type="button"
                      aria-label={t.armario.outfits.quitarAria(i + 1)}
                      onClick={() => {
                        setRemoveError(null);
                        setRemoving(outfit);
                      }}
                      className="-my-2 -mr-1.5 flex h-11 w-9 shrink-0 items-center justify-center text-text-3 active:opacity-60"
                    >
                      <Icon name="delete_icon" size={17} />
                    </button>
                  </div>
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
      {viewing && (
        <GarmentSheet
          garmentId={viewing.id}
          onClose={() => setViewing(null)}
          onDeleted={() => {
            setViewing(null);
            load();
          }}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        title={t.armario.outfits.quitarTitulo}
        text={t.armario.outfits.quitarTexto}
        confirmLabel={t.armario.outfits.quitar}
        busyLabel={t.armario.outfits.quitando}
        busy={busy}
        error={removeError}
        onConfirm={remove}
        onCancel={() => setRemoving(null)}
      />
    </>
  );
}
