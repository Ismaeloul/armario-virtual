import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Segmented } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Catalog, type Garment } from "../lib/api";

export default function Armario() {
  const [garments, setGarments] = useState<Garment[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [season, setSeason] = useState("todas");
  const [category, setCategory] = useState("todo");

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
      <MainHeader title={t.app} brand />
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

        {!failed && garments === null && <p className="mt-10 text-center text-sm text-text-3">{t.comun.cargando}</p>}

        {!failed && garments && catalog && garments.length === 0 && (
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
          <>
            <section>
              <span className="label-caps text-text-2">{t.armario.etiqueta}</span>
              <h2 className="mt-0.5 font-display text-[32px] font-semibold leading-[38px] tracking-tight">
                {t.armario.titulo}
              </h2>
              <p className="mt-0.5 text-sm text-text-2">{t.armario.prendas(garments.length)}</p>
            </section>

            <div className="mt-4">
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

            {laundry > 0 && (
              <div className="mt-4 flex items-center gap-2.5 rounded-xl border border-line bg-chip/40 p-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-chip text-on-chip">
                  <Icon name="laundry" size={18} />
                </div>
                <div>
                  <p className="text-xs font-semibold">{t.armario.enLavado(laundry)}</p>
                  <p className="label-caps font-medium normal-case tracking-normal text-text-2">
                    {t.armario.enLavadoTexto}
                  </p>
                </div>
              </div>
            )}

            {visible.length === 0 ? (
              <p className="mt-10 text-center text-sm text-text-3">{t.armario.sinResultados}</p>
            ) : (
              <section className="mt-4 grid grid-cols-2 gap-3.5">
                {visible.map((g) => (
                  <article key={g.id} className="card flex flex-col p-2.5">
                    <div className="relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-card-2">
                      <img
                        src={mediaUrl(g.photo_front.thumb_url)}
                        alt={g.name}
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                      {g.in_laundry && (
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
                        {[g.brand, g.size && `Talla ${g.size}`].filter(Boolean).join(" · ") ||
                          catalog.seasons[g.season]}
                      </p>
                    </div>
                  </article>
                ))}
              </section>
            )}
          </>
        )}
      </Screen>

      {/* Botón flotante "+": solo en Armario, encima de la barra inferior. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 mx-auto max-w-md">
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
