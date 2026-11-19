import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Segmented } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BackHeader, BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { FadeImg, GridSkeleton, stagger } from "../components/Skeleton";
import { api, mediaUrl, type Catalog, type Garment } from "../lib/api";

/** El catálogo. Con `laundryOnly`, el mismo listado pero solo con lo que está en la lavadora. */
export default function Armario({ laundryOnly = false }: { laundryOnly?: boolean }) {
  const [all, setGarments] = useState<Garment[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [season, setSeason] = useState("todas");
  const [category, setCategory] = useState("todo");

  const [ownCount, setOwnCount] = useState(0);
  useEffect(() => {
    if (!laundryOnly) api.tasteOwn().then((list) => setOwnCount(list.length)).catch(() => undefined);
  }, [laundryOnly]);

  const load = () => {
    setFailed(false);
    Promise.all([api.garments(), api.catalog()])
      .then(([g, c]) => {
        setGarments(g);
        setCatalog(c);
      })
      .catch(() => setFailed(true));
  };
  useEffect(load, []);

  const garments = useMemo(
    () => (all && laundryOnly ? all.filter((g) => g.in_laundry) : all),
    [all, laundryOnly],
  );

  const visible = useMemo(
    () =>
      (garments ?? []).filter(
        (g) => (season === "todas" || g.season === season) && (category === "todo" || g.category === category),
      ),
    [garments, season, category],
  );

  const laundry = (garments ?? []).filter((g) => g.in_laundry).length;
  const count = (cat: string) => (garments ?? []).filter((g) => g.category === cat).length;

  return (
    <>
      {laundryOnly ? <BackHeader title={t.armario.lavadora.cabecera} /> : <MainHeader title={t.app} brand />}
      <Screen>
        {failed && (
          <div className="card mt-6 flex flex-col items-center gap-3 p-6 text-center">
            <Icon name="error" className="text-danger" size={28} />
            <p className="text-sm text-text-2">{t.comun.errorRed}</p>
            <button type="button" onClick={load} className="text-sm font-semibold text-primary">
              {t.comun.reintentar}
            </button>
          </div>
        )}

        {!failed && (garments === null || !catalog) && <GridSkeleton cards={laundryOnly ? 2 : 6} />}

        {!failed && garments && catalog && garments.length === 0 && laundryOnly && (
          <p className="mt-10 text-center text-sm text-text-3">{t.armario.lavadora.vacio}</p>
        )}

        {!failed && garments && catalog && garments.length === 0 && !laundryOnly && (
          <div className="card mt-10 flex flex-col items-center gap-3 p-8 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-card-2 text-primary">
              <Icon name="checkroom" size={28} />
            </div>
            <h2 className="font-display text-xl font-semibold tracking-tight">{t.armario.vacio.titulo}</h2>
            <p className="text-sm text-text-2">{t.armario.vacio.texto}</p>
            <Link
              to="/nueva"
              className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98]"
            >
              <Icon name="add_a_photo" size={20} />
              {t.armario.vacio.boton}
            </Link>
          </div>
        )}

        {!failed && garments && catalog && garments.length > 0 && (
          <div className={laundryOnly ? "animate-slide" : "animate-enter"}>
            <section>
              <span className="label-caps text-text-2">
                {laundryOnly ? t.armario.lavadora.etiqueta : t.armario.etiqueta}
              </span>
              <h2 className="mt-0.5 font-display text-[32px] font-semibold leading-[38px] tracking-tight">
                {laundryOnly ? t.armario.lavadora.titulo : t.armario.titulo}
              </h2>
              <p className="mt-0.5 text-sm text-text-2">
                {laundryOnly ? t.armario.enLavadoTexto : t.armario.prendas(garments.length)}
              </p>
            </section>

            {!laundryOnly && (
              <div className="mt-3 flex justify-end">
                <Link
                  to="/armario/outfits"
                  className="flex h-10 items-center gap-1.5 rounded-full border border-line bg-card-2 pr-3.5 pl-3 text-xs font-medium text-text active:scale-[0.97]"
                >
                  <Icon name="checkroom" size={18} className="text-primary" />
                  {t.armario.outfits.botonN(ownCount)}
                </Link>
              </div>
            )}

            <div className={laundryOnly ? "mt-4" : "mt-2"}>
              <Segmented
                value={season}
                onChange={setSeason}
                options={[
                  { value: "todas", label: t.armario.todas },
                  ...Object.entries(catalog.seasons).map(([value, label]) => ({ value, label })),
                ]}
              />
            </div>

            <div className="-mx-5 mt-4 flex gap-1.5 overflow-x-auto px-5">
              {[["todo", t.armario.todo, garments.length] as const,
                ...Object.entries(catalog.categories).map(([k, label]) => [k, label, count(k)] as const)].map(
                ([key, label, n]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={category === key}
                    onClick={() => setCategory(key)}
                    className={`flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-3.5 text-xs font-medium ${
                      category === key ? "bg-primary text-on-primary" : "bg-card-2 text-text-2"
                    }`}
                  >
                    {label}
                    <span className="opacity-70">{n}</span>
                  </button>
                ),
              )}
            </div>

            {laundry > 0 && !laundryOnly && (
              <Link to="/armario/lavadora" className="mt-4 flex items-center gap-2.5 rounded-xl border border-line bg-chip/40 p-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-chip text-on-chip">
                  <Icon name="laundry" size={18} />
                </div>
                <div>
                  <p className="text-xs font-semibold">{t.armario.enLavado(laundry)}</p>
                  <p className="label-caps font-medium normal-case tracking-normal text-text-2">
                    {t.armario.enLavadoTexto}
                  </p>
                </div>
                <Icon name="chevron_right" size={18} className="ml-auto text-text-2" />
              </Link>
            )}

            {visible.length === 0 ? (
              <p className="mt-10 text-center text-sm text-text-3">{t.armario.sinResultados}</p>
            ) : (
              <section key={`${season}-${category}`} className="mt-4 grid grid-cols-2 gap-3.5">
                {visible.map((g, i) => (
                  <Link
                    key={g.id}
                    to={`/prenda/${g.id}`}
                    style={stagger(i)}
                    className="card flex animate-enter flex-col p-2.5 transition-transform active:scale-[0.97]"
                  >
                    <div className="relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-card-2">
                      <FadeImg
                        src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                        alt={g.name}
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                      {g.on_order ? (
                        <div className="absolute left-2 top-2 flex items-center gap-1 rounded-full border border-line bg-card/90 px-2 py-0.5 backdrop-blur-md">
                          <Icon name="package_box" size={13} className="text-primary" />
                          <span className="label-caps tracking-tight">{t.armario.pedida}</span>
                        </div>
                      ) : g.in_laundry && (
                        <div className="absolute left-2 top-2 flex items-center gap-1 rounded-full border border-line bg-card/90 px-2 py-0.5 backdrop-blur-md">
                          <Icon name="laundry" size={13} className="text-primary" />
                          <span className="label-caps tracking-tight">{t.armario.lavando}</span>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col px-1 pb-1 pt-2.5">
                      <span className="label-caps truncate text-text-2">
                        {cap(g.type)} · {cap(g.color_primary.name)}
                      </span>
                      <h3 className="mt-0.5 truncate font-display text-lg font-semibold leading-6 tracking-tight">
                        {g.name}
                      </h3>
                      <p className="mt-0.5 truncate text-[13px] text-text-2">
                        {[g.brand, g.size && t.armario.talla(g.size)].filter(Boolean).join(" · ") ||
                          catalog.seasons[g.season]}
                      </p>
                    </div>
                  </Link>
                ))}
              </section>
            )}
          </div>
        )}
      </Screen>

      {/* Botón flotante "+": solo en Armario, encima de la barra inferior. */}
      <div className={`pointer-events-none fixed inset-x-0 bottom-0 z-50 mx-auto max-w-md ${laundryOnly ? "hidden" : ""}`}>
        <Link
          to="/nueva"
          aria-label={t.armario.anadir}
          className="pointer-events-auto absolute right-5 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-on-primary shadow-float transition-transform active:scale-95"
          style={{ bottom: "calc(env(safe-area-inset-bottom, 0px) + 5rem)" }}
        >
          <Icon name="add" size={28} />
        </Link>
      </div>
      <BottomNav />
    </>
  );
}
