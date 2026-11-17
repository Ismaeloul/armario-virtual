import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PrimaryButton, RotateButton } from "../components/Controls";
import { Icon, type IconName } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Catalog, type Garment } from "../lib/api";

function Row({ icon, label, children }: { icon: IconName; label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-line bg-card p-3">
      <div className="flex shrink-0 items-center gap-2 text-text-2">
        <Icon name={icon} size={18} />
        <span className="text-sm text-text">{label}</span>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-1.5">{children}</div>
    </div>
  );
}

const Pill = ({ children, strong = false }: { children: ReactNode; strong?: boolean }) => (
  <span
    className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
      strong ? "bg-chip text-on-chip" : "bg-control text-text"
    }`}
  >
    {children}
  </span>
);

const Dot = ({ hex }: { hex: string }) => (
  <span className="h-2.5 w-2.5 rounded-full border border-text/10" style={{ background: hex }} />
);

const formatDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });

export default function FichaPrenda() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [garment, setGarment] = useState<Garment | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [missing, setMissing] = useState(false);
  const [showBack, setShowBack] = useState(false);

  useEffect(() => {
    api.garment(Number(id)).then(setGarment).catch(() => setMissing(true));
    api.catalog().then(setCatalog).catch(() => undefined);
  }, [id]);

  if (missing) {
    return (
      <>
        <BackHeader title={t.ficha.cabecera} />
        <Screen withNav={false}>
          <p className="mt-10 text-center text-sm text-text-2">{t.ficha.noExiste}</p>
        </Screen>
      </>
    );
  }
  if (!garment || !catalog) {
    return (
      <>
        <BackHeader title={t.ficha.cabecera} />
        <Screen withNav={false}>
          <p className="mt-10 text-center text-sm text-text-3">{t.comun.cargando}</p>
        </Screen>
      </>
    );
  }

  // Cambios inmediatos (favorita, lavadora, uso): se pinta ya y se confirma con el servidor.
  const patch = (changes: { favorite?: boolean; in_laundry?: boolean }) => {
    setGarment({ ...garment, ...changes });
    api.updateGarment(garment.id, changes).then(setGarment).catch(() => setGarment(garment));
  };

  const remove = async () => {
    if (!window.confirm(t.ficha.confirmarEliminar)) return;
    await api.deleteGarment(garment.id);
    navigate("/armario", { replace: true });
  };

  const photo = showBack && garment.photo_back ? garment.photo_back : garment.photo_front;
  const brandSize = [garment.brand, garment.size].filter(Boolean).join(" · ");

  return (
    <>
      <BackHeader title={t.ficha.cabecera} />
      <Screen withNav={false}>
        <div className="flex flex-col gap-4">
          {/* Foto: delante / detrás */}
          <div className="relative overflow-hidden rounded-xl border border-line bg-card-2">
            <img src={mediaUrl(photo.url)} alt={garment.name} className="aspect-[3/4] w-full object-cover" />
            <RotateButton
              className="absolute right-3 top-3"
              onClick={() =>
                api
                  .rotatePhoto(photo.id)
                  .then(() => api.garment(garment.id))
                  .then(setGarment)
                  .catch(() => undefined)
              }
            />
            <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full border border-line bg-card/90 px-2.5 py-1 backdrop-blur-md">
              {garment.in_laundry ? (
                <Icon name="laundry" size={13} className="text-primary" />
              ) : (
                <span className="h-2 w-2 rounded-full bg-primary" />
              )}
              <span className="label-caps">{garment.in_laundry ? t.ficha.enLavadora : t.ficha.disponible}</span>
            </div>
            {garment.photo_back && (
              <div className="absolute bottom-3 left-3 right-3 flex justify-center">
                <div className="flex gap-1 rounded-full bg-text/75 p-1 backdrop-blur-md">
                  {[false, true].map((back) => (
                    <button
                      key={String(back)}
                      type="button"
                      aria-pressed={showBack === back}
                      onClick={() => setShowBack(back)}
                      className={`rounded-full px-3 py-1 text-[11px] font-medium ${
                        showBack === back ? "bg-bg text-text" : "text-bg"
                      }`}
                    >
                      {back ? t.ficha.detras : t.ficha.delante}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Título */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="label-caps truncate text-text-2">
                {catalog.categories[garment.category]}
                {brandSize && ` · ${brandSize}`}
              </span>
              <button
                type="button"
                aria-label={t.ficha.favorito}
                aria-pressed={garment.favorite}
                onClick={() => patch({ favorite: !garment.favorite })}
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-card-2 active:scale-90 ${
                  garment.favorite ? "text-danger" : "text-text-2"
                }`}
              >
                <Icon name={garment.favorite ? "favorite_fill" : "favorite"} size={20} />
              </button>
            </div>
            <h2 className="mt-0.5 font-display text-2xl font-semibold tracking-tight">{garment.name}</h2>
            {garment.details && <p className="mt-1 text-sm text-text-2">{garment.details}</p>}
            {garment.notes && <p className="mt-1 text-sm text-text-3">{garment.notes}</p>}
          </div>

          {/* Lavadora */}
          <div className="flex items-center justify-between gap-4 rounded-xl border border-line bg-card-2 p-4">
            <div className="flex items-start gap-3">
              <span
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                  garment.in_laundry ? "bg-chip text-on-chip" : "bg-control text-text-2"
                }`}
              >
                <Icon name="laundry" size={22} />
              </span>
              <div>
                <p className="font-display text-lg font-semibold leading-6">{t.ficha.lavadora}</p>
                <p className="mt-0.5 text-xs text-text-2">{t.ficha.lavadoraTexto}</p>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={garment.in_laundry}
              aria-label={t.ficha.lavadora}
              onClick={() => patch({ in_laundry: !garment.in_laundry })}
              className={`flex h-7 w-12 shrink-0 items-center rounded-full p-0.5 transition-colors ${
                garment.in_laundry ? "justify-end bg-primary" : "justify-start bg-control"
              }`}
            >
              <span className="h-6 w-6 rounded-full bg-white shadow" />
            </button>
          </div>

          {/* Ficha técnica */}
          <div className="flex flex-col gap-2">
            <h3 className="font-display text-lg font-semibold">{t.ficha.detalles}</h3>
            <Row icon="checkroom" label={t.ficha.filas.tipo}>
              <Pill>{cap(garment.type)}</Pill>
            </Row>
            <Row icon="palette" label={t.ficha.filas.colores}>
              {[garment.color_primary, ...garment.colors_secondary].map((c) => (
                <Pill key={c.name}>
                  <Dot hex={c.hex} />
                  {cap(c.name)}
                </Pill>
              ))}
            </Row>
            <Row icon="texture" label={t.ficha.filas.estampado}>
              <Pill>{cap(garment.pattern)}</Pill>
            </Row>
            <Row icon="style" label={t.ficha.filas.estilo}>
              <Pill>{cap(garment.style)}</Pill>
            </Row>
            <Row icon="calendar" label={t.ficha.filas.temporada}>
              <Pill strong>{catalog.seasons[garment.season]}</Pill>
            </Row>
            {brandSize && (
              <Row icon="sell" label={t.ficha.filas.marca}>
                <Pill>{brandSize}</Pill>
              </Row>
            )}
          </div>

          {/* Uso (se deriva del historial) */}
          <div className="flex flex-col gap-2">
            <h3 className="font-display text-lg font-semibold">{t.ficha.uso}</h3>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl border border-line bg-card-2 p-4">
                <Icon name="repeat" size={20} className="text-primary" />
                <p className="mt-3 font-display text-2xl font-semibold leading-none">
                  {t.ficha.veces(garment.wear_count)}
                </p>
                <p className="mt-1 text-xs text-text-2">{t.ficha.vecesTexto}</p>
              </div>
              <div className="rounded-xl border border-line bg-card-2 p-4">
                <Icon name="history" size={20} className="text-primary" />
                <p className="mt-3 font-display text-lg font-semibold leading-tight">
                  {garment.last_worn_on ? formatDate(garment.last_worn_on) : t.ficha.nunca}
                </p>
                <p className="mt-1 text-xs text-text-2">{t.ficha.ultima}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => api.wearGarment(garment.id).then(setGarment)}
              className="flex h-11 items-center justify-center gap-1.5 rounded-xl border border-line bg-control text-xs font-medium active:scale-[0.98]"
            >
              <Icon name="check_circle" size={18} />
              {t.ficha.ponerHoy}
            </button>
          </div>

          {/* Acciones */}
          <div className="flex flex-col gap-2.5 pt-2">
            {/* "Crear look" llega en la Fase 3: visible pero desactivado. */}
            <div className="relative">
              <PrimaryButton disabled>
                <Icon name="style" size={20} />
                {t.ficha.crearLook}
              </PrimaryButton>
              <span className="label-caps absolute -top-2 right-3 rounded-full bg-chip px-2 py-0.5 text-on-chip">
                {t.ficha.pronto}
              </span>
            </div>
            <Link
              to={`/prenda/${garment.id}/editar`}
              className="flex h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-line bg-control text-xs font-medium active:scale-[0.98]"
            >
              <Icon name="edit" size={18} />
              {t.ficha.editar}
            </Link>
            <button
              type="button"
              onClick={remove}
              className="flex h-11 items-center justify-center gap-1.5 text-xs font-medium text-danger active:opacity-60"
            >
              <Icon name="delete_icon" size={18} />
              {t.ficha.eliminar}
            </button>
          </div>
        </div>
      </Screen>
    </>
  );
}
