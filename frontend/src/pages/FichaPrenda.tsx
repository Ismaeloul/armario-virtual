import { externalHref } from "../lib/links";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PrimaryButton, RotateButton, Switch } from "../components/Controls";
import { CopyRow } from "../components/CopyButton";
import { Icon, type IconName } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { DetailSkeleton, FadeImg } from "../components/Skeleton";
import { cap, t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Catalog, type Garment } from "../lib/api";

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
  // "missing": la prenda no existe (404); "red": no se pudo cargar (servidor caído, etc.).
  const [loadError, setLoadError] = useState<"missing" | "red" | null>(null);
  const [view, setView] = useState<"photo_front" | "photo_back" | "photo_extra" | "photo_label">("photo_front");
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);
  const [photoError, setPhotoError] = useState(false);
  const [patchError, setPatchError] = useState(false);
  const [wearing, setWearing] = useState(false);
  const [worn, setWorn] = useState(false);
  const [wearError, setWearError] = useState(false);

  const load = () => {
    setLoadError(null);
    api
      .garment(Number(id))
      .then(setGarment)
      .catch((e) => setLoadError(e instanceof ApiError && e.status === 404 ? "missing" : "red"));
    api
      .catalog()
      .then(setCatalog)
      .catch(() => setLoadError((current) => current ?? "red"));
  };
  useEffect(load, [id]);

  // Tras apuntar un uso, el botón lo confirma unos segundos y no deja repetirlo sin querer.
  useEffect(() => {
    if (!worn) return;
    const timer = setTimeout(() => setWorn(false), 2500);
    return () => clearTimeout(timer);
  }, [worn]);

  if (loadError) {
    return (
      <>
        <BackHeader title={t.ficha.cabecera} />
        <Screen withNav={false}>
          <div className="mt-10 flex flex-col items-center gap-2 text-center">
            <p className="text-sm text-text-2">{loadError === "missing" ? t.ficha.noExiste : t.comun.errorRed}</p>
            {loadError === "missing" ? (
              <Link
                to="/armario"
                replace
                className="inline-flex min-h-11 items-center px-3 text-sm font-semibold text-primary"
              >
                {t.ficha.irArmario}
              </Link>
            ) : (
              <button type="button" onClick={load} className="min-h-11 px-3 text-sm font-semibold text-primary">
                {t.comun.reintentar}
              </button>
            )}
          </div>
        </Screen>
      </>
    );
  }
  if (!garment || !catalog) {
    return (
      <>
        <BackHeader title={t.ficha.cabecera} />
        <Screen withNav={false}>
          <DetailSkeleton />
        </Screen>
      </>
    );
  }

  // Cambios inmediatos (favorita, lavadora, uso): se pinta ya y se confirma con el servidor.
  // Si falla, se deshacen solo las claves cambiadas, sin pisar otros cambios hechos mientras tanto.
  const patch = (changes: { favorite?: boolean; in_laundry?: boolean; on_order?: boolean }) => {
    const previous: typeof changes = {};
    for (const key of Object.keys(changes) as (keyof typeof changes)[]) previous[key] = garment[key];
    setPatchError(false);
    setGarment((g) => (g ? { ...g, ...changes } : g));
    api
      .updateGarment(garment.id, changes)
      .then(setGarment)
      .catch(() => {
        setGarment((g) => (g ? { ...g, ...previous } : g));
        setPatchError(true);
      });
  };

  const remove = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteGarment(garment.id);
      navigate("/armario", { replace: true });
    } catch {
      setDeleteError(t.ficha.errorEliminar);
      setDeleting(false);
    }
  };

  const wear = () => {
    setWearing(true);
    setWearError(false);
    api
      .wearGarment(garment.id)
      .then((g) => {
        setGarment(g);
        setWorn(true);
      })
      .catch(() => setWearError(true))
      .finally(() => setWearing(false));
  };

  const views = (
    [
      ["photo_front", garment.category === "calzado" ? t.ficha.lateral : t.ficha.delante],
      ["photo_back", garment.category === "calzado" ? t.ficha.frente : t.ficha.detras],
      ["photo_extra", t.ficha.otroLado],
      ["photo_label", t.ficha.etiqueta],
    ] as const
  ).filter(([key]) => garment[key]);
  const photo = garment[view] ?? garment.photo_front;
  const brandSize = [garment.brand, garment.size].filter(Boolean).join(" · ");

  return (
    <>
      <BackHeader title={t.ficha.cabecera} />
      <Screen withNav={false}>
        <div className="flex animate-slide flex-col gap-4">
          {/* Foto: delante / detrás */}
          <div className="relative overflow-hidden rounded-xl border border-line bg-card-2">
            <FadeImg key={photo.id} src={mediaUrl(photo.url)} alt={garment.name} className="aspect-[3/4] w-full object-contain" />
            <RotateButton
              className="absolute right-3 top-3"
              disabled={rotating}
              onClick={() => {
                setRotating(true);
                setPhotoError(false);
                api
                  .rotatePhoto(photo.id)
                  .then(() => api.garment(garment.id))
                  .then(setGarment)
                  .catch(() => setPhotoError(true))
                  .finally(() => setRotating(false));
              }}
            />
            <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full border border-line bg-card/90 px-2.5 py-1 backdrop-blur-md">
              {garment.on_order ? (
                <Icon name="package_box" size={13} className="text-primary" />
              ) : garment.in_laundry ? (
                <Icon name="laundry" size={13} className="text-primary" />
              ) : (
                <span className="h-2 w-2 rounded-full bg-primary" />
              )}
              <span className="label-caps">
                {garment.on_order ? t.ficha.pedida : garment.in_laundry ? t.ficha.enLavadora : t.ficha.disponible}
              </span>
            </div>
            {views.length > 1 && (
              <div className="absolute bottom-3 left-3 right-3 flex justify-center">
                <div className="flex gap-1 rounded-full bg-text/75 p-1 backdrop-blur-md">
                  {views.map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      aria-pressed={view === key}
                      onClick={() => setView(key)}
                      className={`rounded-full px-3 py-2 text-[11px] font-medium ${
                        view === key ? "bg-bg text-text" : "text-bg"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          {photoError && <p className="-mt-2 text-center text-xs text-danger">{t.comun.errorRed}</p>}

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
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-card-2 active:scale-90 ${
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

          {/* Pedida y aún sin llegar: en vez de la lavadora, el aviso y «Ya me ha llegado». */}
          {garment.on_order && (
            <div className="flex flex-col gap-3 rounded-xl border border-line bg-card-2 p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-chip text-on-chip">
                  <Icon name="package_box" size={22} />
                </span>
                <div>
                  <p className="font-display text-lg font-semibold leading-6">{t.ficha.pedidaTitulo}</p>
                  <p className="mt-0.5 text-xs text-text-2">
                    {garment.ordered_at && `${t.ficha.pedidaDesde(
                        new Date(garment.ordered_at).toLocaleDateString("es-ES", { day: "numeric", month: "long" }),
                      )} `}
                    {t.ficha.pedidaTexto}
                  </p>
                </div>
              </div>
              <PrimaryButton onClick={() => patch({ on_order: false })}>
                <Icon name="check_circle" size={20} />
                {t.ficha.recibida}
              </PrimaryButton>
            </div>
          )}
          <div
            className={`flex items-center justify-between gap-4 rounded-xl border border-line bg-card-2 p-4 ${
              garment.on_order ? "hidden" : ""
            }`}
          >
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
            <Switch
              checked={garment.in_laundry}
              label={t.ficha.lavadora}
              onChange={() => patch({ in_laundry: !garment.in_laundry })}
            />
          </div>
          {patchError && <p className="-mt-2 text-center text-xs text-danger">{t.comun.errorRed}</p>}

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
            {(garment.closure || garment.fit || garment.thickness || garment.hood) && (
              <Row icon="style" label={t.ficha.filas.rasgos}>
                {[garment.closure, garment.fit, garment.thickness, garment.hood ? t.ficha.filas.capucha : null]
                  .filter((v): v is string => Boolean(v))
                  .map((v) => (
                    <Pill key={v}>{cap(v)}</Pill>
                  ))}
              </Row>
            )}
            <Row icon="calendar" label={t.ficha.filas.temporada}>
              <Pill strong>{catalog.seasons[garment.season]}</Pill>
            </Row>
            {brandSize && (
              <Row icon="sell" label={t.ficha.filas.marca}>
                <Pill>{brandSize}</Pill>
              </Row>
            )}
          </div>

          {/* De dónde vino: la referencia (de Compras o escrita a mano), la tienda y su página. Sin precio. */}
          {(garment.reference || garment.store_name || garment.store_url) && (
            <div className="flex flex-col gap-2">
              <h3 className="font-display text-lg font-semibold">{t.ficha.tienda.titulo}</h3>
              {garment.reference && <CopyRow label={t.ficha.tienda.referencia} value={garment.reference} />}
              {garment.store_name && <CopyRow label={t.ficha.tienda.tienda} value={garment.store_name} />}
              {garment.store_url && (
                <CopyRow
                  label={t.ficha.tienda.enlace}
                  value={garment.store_url}
                >
                  <a
                    href={externalHref(garment.store_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={t.ficha.tienda.abrir}
                    className="block truncate py-1 text-sm font-medium text-primary underline underline-offset-2 active:opacity-60"
                  >
                    {garment.store_url.replace(/^https?:\/\/(www\.)?/, "")}
                  </a>
                </CopyRow>
              )}
            </div>
          )}

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
              disabled={wearing || worn}
              onClick={wear}
              className={`h-11 items-center justify-center gap-1.5 rounded-xl border border-line text-xs font-medium active:scale-[0.98] ${
                garment.on_order ? "hidden" : "flex"
              } ${worn ? "bg-chip text-on-chip" : "bg-control disabled:opacity-40"}`}
            >
              <Icon name="check_circle" size={18} />
              {worn ? t.ficha.registrado : t.ficha.ponerHoy}
            </button>
            {wearError && <p className="text-center text-xs text-danger">{t.comun.errorRed}</p>}
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
              onClick={() => {
                setDeleteError(null);
                setConfirming(true);
              }}
              className="flex h-11 items-center justify-center gap-1.5 text-xs font-medium text-danger active:opacity-60"
            >
              <Icon name="delete_icon" size={18} />
              {t.ficha.eliminar}
            </button>
          </div>
        </div>
      </Screen>
      <ConfirmDialog
        open={confirming}
        title={t.ficha.confirmarTitulo}
        text={t.ficha.confirmarEliminar}
        confirmLabel={t.ficha.eliminarBoton}
        busyLabel={t.ficha.eliminando}
        busy={deleting}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
