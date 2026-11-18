import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { FadeImg, OutfitSkeleton, stagger } from "../components/Skeleton";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Catalog, type Today } from "../lib/api";

const WEATHER_ICONS: Record<string, IconName> = {
  sunny: "sunny",
  weather: "weather",
  cloud: "cloud",
  rain: "rain",
  snow: "snow",
};

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return t.hoy.noches;
  if (hour < 13) return t.hoy.dias;
  if (hour < 21) return t.hoy.tardes;
  return t.hoy.noches;
}

export default function Hoy() {
  const [today, setToday] = useState<Today | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(false);
  const loadedAt = useRef(0);

  const show = (data: Today) => {
    setToday(data);
    loadedAt.current = Date.now();
  };
  const load = () => {
    setFailed(false);
    api.today().then(show).catch(() => setFailed(true));
  };
  useEffect(() => {
    load();
    api.catalog().then(setCatalog).catch(() => undefined);
    // Una PWA puede seguir abierta de un día para otro: al volver a ella se refresca el outfit y el
    // tiempo si cambió el día o pasaron unos minutos. Si falla, se queda lo que había.
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      const sameDay = new Date(loadedAt.current).toDateString() === new Date().toDateString();
      if (sameDay && Date.now() - loadedAt.current < 10 * 60 * 1000) return;
      api.today().then(show).catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  /** Lanza una acción sobre el outfit y pinta el resultado. */
  const act = (request: () => Promise<Today>) => {
    setBusy(true);
    setActionError(false);
    request()
      .then(show)
      .catch(() => setActionError(true))
      .finally(() => setBusy(false));
  };

  // La fecha es la del outfit que se muestra (la del servidor), no la del reloj en este momento.
  const date = (today ? new Date(today.date + "T00:00:00") : new Date()).toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const outfit = today?.outfit;
  const chosen = outfit?.status === "elegido";

  return (
    <>
      <MainHeader title={t.app} brand />
      <Screen>
        <div className="flex flex-col gap-5">
          <header className="flex flex-col gap-2">
            <span className="label-caps text-text-2">{date}</span>
            <h2 className="font-display text-2xl font-semibold tracking-tight">{greeting()}</h2>

            {/* El tiempo de la ciudad de Ajustes */}
            {today && (
              <Link to="/ajustes" className="flex items-center gap-3 rounded-2xl border border-line bg-card-2 p-3.5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-control text-primary">
                  <Icon name={today.weather ? WEATHER_ICONS[today.weather.icon] ?? "weather" : "weather"} size={22} />
                </span>
                {today.weather ? (
                  <div className="min-w-0">
                    <p className="flex items-baseline gap-1.5">
                      <span className="font-display text-lg font-semibold">{today.weather.temp_now}°C</span>
                      <span className="truncate text-sm text-text-2">· {today.weather.description}</span>
                    </p>
                    <p className="truncate text-xs text-text-2">
                      {t.hoy.tiempoDetalle(
                        today.weather.city,
                        today.weather.temp_min,
                        today.weather.temp_max,
                        today.weather.rain_probability,
                      )}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-text-2">{t.hoy.sinTiempo(today.city)}</p>
                )}
              </Link>
            )}
          </header>

          {failed && (
            <div className="card flex flex-col items-center gap-3 p-6 text-center">
              <Icon name="error" className="text-danger" size={28} />
              <p className="text-sm text-text-2">{t.comun.errorRed}</p>
              <button type="button" onClick={load} className="text-sm font-semibold text-primary">
                {t.comun.reintentar}
              </button>
            </div>
          )}

          {!failed && !today && <OutfitSkeleton />}

          {/* Faltan prendas para poder proponer algo */}
          {today && !outfit && (
            <div className="card flex flex-col items-center gap-3 p-8 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-card-2 text-primary">
                <Icon name="checkroom" size={28} />
              </span>
              <h3 className="font-display text-xl font-semibold tracking-tight">{t.hoy.faltaTitulo}</h3>
              <p className="text-sm text-text-2">
                {today.missing.length > 0
                  ? t.hoy.faltaTexto(today.missing.map((m) => m.toLowerCase()))
                  : t.hoy.faltaGenerico}
              </p>
              {today.in_laundry > 0 && <p className="text-xs text-text-3">{t.hoy.enLavadora(today.in_laundry)}</p>}
              <Link
                to="/nueva"
                className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98]"
              >
                <Icon name="add_a_photo" size={20} />
                {t.armario.anadir}
              </Link>
            </div>
          )}

          {/* El outfit del día */}
          {today && outfit && (
            <>
              {/* La clave es la propuesta: al pedir otra, la tarjeta nueva vuelve a entrar animada. */}
              <section
                key={outfit.id}
                className={`card flex animate-enter flex-col p-5 transition-opacity duration-300 ${busy ? "opacity-50" : ""}`}
              >
                <div className="flex items-center justify-between gap-2 pb-4">
                  <div className="min-w-0">
                    <span className="label-caps text-text-2">{t.hoy.tipoDia[outfit.day_kind] ?? ""}</span>
                    <h3 className="font-display text-lg font-semibold">
                      {chosen ? t.hoy.elegidoTitulo : t.hoy.propuestaTitulo}
                    </h3>
                  </div>
                  <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-chip px-3 py-1 text-on-chip">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span className="label-caps">{t.hoy.afinidad(outfit.affinity)}</span>
                  </span>
                </div>

                <div className="flex flex-col gap-3">
                  {outfit.garments.map((g, i) => (
                    <Link
                      key={g.id}
                      to={`/prenda/${g.id}`}
                      style={stagger(i + 1, 70)}
                      className="flex animate-enter items-center gap-3.5 rounded-2xl border border-line bg-card-2 p-2.5 transition-transform active:scale-[0.98]"
                    >
                      <FadeImg
                        src={mediaUrl(g.photo_front.thumb_url)}
                        alt=""
                        className="h-24 w-20 shrink-0 rounded-xl object-cover"
                      />
                      <div className="min-w-0 flex-1">
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
                          <span className="rounded-full bg-control px-2 py-0.5 text-[11px] text-text-2">
                            {cap(g.type)}
                          </span>
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>

                {(today.notes.length > 0 || today.in_laundry > 0) && (
                  <div className="mt-4 flex flex-col gap-1 border-t border-control pt-3 text-xs text-text-2">
                    {today.notes.includes("sin_calzado") && <p>{t.hoy.sinCalzado}</p>}
                    {today.notes.includes("sin_capa") && <p>{t.hoy.sinCapa}</p>}
                    {today.notes.includes("sin_mas_combinaciones") && <p>{t.hoy.sinMasCombinaciones}</p>}
                    {today.in_laundry > 0 && <p>{t.hoy.enLavadora(today.in_laundry)}</p>}
                  </div>
                )}
              </section>

              {actionError && (
                <p role="alert" className="-mt-2 text-center text-sm text-danger">
                  {t.comun.errorRed}
                </p>
              )}

              {chosen ? (
                <section className="flex flex-col gap-2">
                  <p className="flex items-center justify-center gap-2 text-sm font-medium">
                    <Icon name="check_circle" size={18} className="text-primary" />
                    {t.hoy.elegidoTexto}
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => act(api.todayUnchoose)}
                    className="h-11 text-xs font-medium text-text-2 underline disabled:opacity-40"
                  >
                    {t.hoy.cambiarIdea}
                  </button>
                </section>
              ) : (
                <section className="flex flex-col gap-2">
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => act(() => api.todayNext("pasar"))}
                      className="flex h-12 items-center justify-center gap-2 rounded-xl border border-line bg-control font-display text-[15px] font-semibold active:scale-[0.98] disabled:opacity-40"
                    >
                      <Icon name="close" size={20} className="text-text-2" />
                      {t.hoy.pasar}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => act(api.todayChoose)}
                      className="flex h-12 items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
                    >
                      <Icon name="favorite_fill" size={20} />
                      {t.hoy.meGusta}
                    </button>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => act(() => api.todayNext("otra"))}
                    className="card flex h-12 w-full items-center justify-center gap-2 font-display text-[15px] font-semibold active:scale-[0.99] disabled:opacity-40"
                  >
                    <Icon name="auto_awesome" size={20} className="text-primary" />
                    {t.hoy.otra}
                  </button>
                </section>
              )}
            </>
          )}
        </div>
      </Screen>
      <BottomNav />
    </>
  );
}
