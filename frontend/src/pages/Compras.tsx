import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PrimaryButton, SecondaryButton, Segmented, Switch } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import {
  api,
  ApiError,
  mediaUrl,
  type ShopDiscardReason,
  type ShopFilter,
  type ShopItem,
  type ShopNext,
  type ShopState,
  type ShopStore,
} from "../lib/api";

type View = "descubrir" | "gustados";

const POLL_MS = 4000; // cada cuánto se pregunta cómo va la consulta (o el «Ver más») en marcha
const REASON_DONE_MS = 1500;
// «Es caro» no se ofrece: el usuario no quiere que el precio sea un motivo.
const REASONS: ShopDiscardReason[] = ["estilo", "color", "ya_tengo"];
const NO_FILTER: ShopFilter = { store: null, category: null };

/** «viernes, 20 de noviembre, 9:41» a partir de una fecha con hora. */
const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("es-ES", { weekday: "long", day: "numeric", month: "long", hour: "numeric", minute: "2-digit" });

/** «hoy», «mañana» o «el viernes 20 de noviembre» a partir de un día (AAAA-MM-DD). */
function dayLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((date.getTime() - today.getTime()) / 86_400_000);
  if (diff <= 0) return t.compras.hoy;
  if (diff === 1) return t.compras.manana;
  return `el ${date.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}`;
}

const dayMonth = (iso: string) => new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "long" });

/** Pestaña Compras: novedades de las tiendas puntuadas contra el armario. Solo enlaza; nunca compra. */
export default function Compras() {
  const [view, setView] = useState<View>("descubrir");
  const [state, setState] = useState<ShopState | null>(null);
  const [next, setNext] = useState<ShopNext | null>(null);
  const [failed, setFailed] = useState(false);
  const [storesOpen, setStoresOpen] = useState(false);
  // El filtro de Descubrir. La referencia es para el sondeo, que no debe reiniciarse al cambiarlo.
  const [filter, setFilter] = useState<ShopFilter>(NO_FILTER);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  const load = useCallback(() => {
    setFailed(false);
    Promise.all([api.shopState(), api.shopNext(filterRef.current)])
      .then(([s, n]) => {
        setState(s);
        setNext(n);
      })
      .catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);
  const closeStores = useCallback(() => setStoresOpen(false), []);

  const changeFilter = useCallback((value: ShopFilter) => {
    setFilter(value);
    api
      .shopNext(value)
      // Si mientras tanto se ha vuelto a cambiar, esta respuesta ya no vale.
      .then((n) => filterRef.current === value && setNext(n))
      .catch(() => setFailed(true));
  }, []);

  // Si se desactiva la tienda por la que se estaba filtrando, el filtro de tienda se quita.
  const filteredStore = state?.stores.find((s) => s.key === filter.store);
  useEffect(() => {
    if (filter.store && filteredStore && !filteredStore.enabled) changeFilter({ ...filter, store: null });
  }, [filter, filteredStore, changeFilter]);

  // Mientras hay una consulta en marcha se sondea el estado; al terminar se piden las propuestas.
  const running = state?.running ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      // Si un sondeo falla no pasa nada: el siguiente lo vuelve a intentar.
      api
        .shopState()
        .then((s) => {
          setState(s);
          if (!s.running || s.pending > 0) api.shopNext(filterRef.current).then(setNext).catch(() => undefined);
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  return (
    <>
      <MainHeader title={t.compras.titulo} />
      <Screen>
        <div className="flex flex-col gap-5">
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <Segmented<View>
                options={[
                  { value: "descubrir", label: t.compras.descubrir },
                  { value: "gustados", label: t.compras.meGustanN(state?.liked ?? 0) },
                ]}
                value={view}
                onChange={setView}
              />
            </div>
            <button
              type="button"
              onClick={() => setStoresOpen(true)}
              disabled={!state}
              className="flex h-12 shrink-0 items-center gap-1.5 rounded-xl border border-line bg-control px-3.5 text-xs font-medium text-text active:scale-[0.98] disabled:opacity-40"
            >
              <Icon name="store" size={18} />
              {t.compras.tiendas}
              {state?.stores.some((s) => s.enabled && s.status.state === "failed") && (
                <span className="h-2 w-2 rounded-full bg-danger" />
              )}
            </button>
          </div>

          {failed && (
            <div className="card flex flex-col items-center gap-3 p-6 text-center">
              <Icon name="error" className="text-danger" size={28} />
              <p className="text-sm text-text-2">{t.comun.errorRed}</p>
              <button type="button" onClick={load} className="min-h-11 px-3 text-sm font-semibold text-primary">
                {t.comun.reintentar}
              </button>
            </div>
          )}
          {!failed && (!state || !next) && <p className="mt-6 text-center text-sm text-text-3">{t.comun.cargando}</p>}

          {!failed && state && next && view === "descubrir" && (
            <Discover
              state={state}
              next={next}
              filter={filter}
              onFilter={changeFilter}
              onState={setState}
              onNext={(n) => {
                setNext(n);
                // Los contadores (pendientes, me gustan) cambian con cada decisión.
                api.shopState().then(setState).catch(() => undefined);
              }}
              onOpenStores={() => setStoresOpen(true)}
            />
          )}
          {!failed && state && next && view === "gustados" && (
            <Liked onChanged={() => api.shopState().then(setState).catch(() => undefined)} />
          )}
        </div>
      </Screen>
      <BottomNav />
      {storesOpen && state && <StoresPanel state={state} onState={setState} onClose={closeStores} />}
    </>
  );
}

// ---------- Descubrir

function Discover({
  state,
  next,
  filter,
  onFilter,
  onState,
  onNext,
  onOpenStores,
}: {
  state: ShopState;
  next: ShopNext;
  filter: ShopFilter;
  onFilter: (f: ShopFilter) => void;
  onState: (s: ShopState) => void;
  onNext: (n: ShopNext) => void;
  onOpenStores: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fit = useFitHeight(Boolean(next.item));
  // Los botones mueven la tarjeta igual que el dedo: sale volando hacia su lado antes de decidir.
  const [fly, setFly] = useState<-1 | 0 | 1>(0);
  // Por qué lado se fue cada tarjeta, para que «Volver» la traiga de vuelta por ahí.
  const sides = useRef(new Map<number, -1 | 1>());
  const [back, setBack] = useState<{ id: number; side: -1 | 1 } | null>(null);
  const flyTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(flyTimer.current), []);
  // Si guardar la decisión falla, la tarjeta que ya se fue volando tiene que volver.
  const [attempt, setAttempt] = useState(0);
  // Tras un «no me gusta», de qué producto se puede decir el motivo (y si ya se ha dicho).
  const [asking, setAsking] = useState<{ id: number; done: boolean } | null>(null);
  const askTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(askTimer.current), []);

  const ask = (value: { id: number; done: boolean } | null, ms = 0) => {
    window.clearTimeout(askTimer.current);
    setAsking(value);
    if (value) askTimer.current = window.setTimeout(() => setAsking(null), ms);
  };

  const enabled = state.stores.filter((s) => s.enabled);
  const item = next.item;

  const decide = (liked: boolean) => {
    if (!item || busy) return;
    const id = item.id;
    sides.current.set(id, liked ? 1 : -1);
    setBusy(true);
    setError(null);
    (liked ? api.shopLike(id, filter) : api.shopDislike(id, filter))
      .then((n) => {
        setFly(0);
        setBack(null);
        onNext(n);
        // La pregunta del motivo no frena nada: sale aparte, se puede ignorar y se va sola.
        // Ya no se pregunta el motivo al descartar (decisión del usuario): descartar una prenda no
        // siempre tiene un motivo que se pueda decir, y no debe sentirse como una encuesta.
        ask(null);
      })
      .catch(() => {
        setFly(0);
        setError(t.compras.errorAccion);
        setAttempt((n) => n + 1);
      })
      .finally(() => setBusy(false));
  };

  /** Botón de la X o del corazón: la tarjeta sale volando hacia su lado y luego se guarda la decisión. */
  const press = (liked: boolean) => {
    if (!item || busy || fly) return;
    setFly(liked ? 1 : -1);
    flyTimer.current = window.setTimeout(() => decide(liked), FLY_MS);
  };

  /** «Volver»: deshace la última decisión y vuelve a enseñar esa tarjeta. */
  const undo = () => {
    if (busy || !next.can_undo) return;
    setBusy(true);
    setError(null);
    ask(null);
    api
      .shopUndo(filter)
      .then((n) => {
        if (n.item) setBack({ id: n.item.id, side: sides.current.get(n.item.id) ?? -1 });
        onNext(n);
      })
      .catch(() => setError(t.compras.errorVolver))
      .finally(() => setBusy(false));
  };

  const giveReason = (reason: ShopDiscardReason) => {
    if (!asking || asking.done) return;
    ask({ id: asking.id, done: true }, REASON_DONE_MS);
    // Si no se guarda no pasa nada grave: el descarte ya cuenta, solo que sin motivo.
    api.shopReason(asking.id, reason).catch(() => undefined);
  };

  /** Activa la tienda (si hace falta) y lanza la consulta en segundo plano. */
  const search = (store: ShopStore) => {
    setBusy(true);
    setError(null);
    (store.enabled ? Promise.resolve() : api.shopSettings({ store: store.key, enabled: true }))
      .then(() => api.shopRefresh(store.key))
      .then(onState)
      .catch((e) => setError(e instanceof ApiError && e.status < 500 ? e.message : t.comun.errorRed))
      .finally(() => setBusy(false));
  };

  /** «Ver más»: la siguiente tanda del catálogo ya guardado, con el filtro que haya puesto. */
  const more = () => {
    setBusy(true);
    setError(null);
    ask(null);
    api
      .shopMore(filter)
      .then((s) => {
        onState(s);
        // Si ya ha terminado (no quedaba nada que traer), el sondeo no arranca: se pregunta ahora.
        if (!s.running) return api.shopNext(filter).then(onNext);
      })
      .catch((e) => setError(e instanceof ApiError && e.status < 500 ? e.message : t.comun.errorRed))
      .finally(() => setBusy(false));
  };

  const alert = error && (
    <p role="alert" className="text-center text-sm text-danger">
      {error}
    </p>
  );

  // Ninguna tienda activada: se explica qué es esto y se ofrece activarla.
  if (enabled.length === 0) {
    const store = state.stores[0];
    if (!store) return null;
    return (
      <>
        <Notice icon="cart" title={t.compras.desactivada.titulo} text={t.compras.desactivada.texto(store.name)}>
          <PrimaryButton disabled={busy} onClick={() => search(store)}>
            {busy ? t.compras.desactivada.activando : t.compras.desactivada.activar(store.name)}
          </PrimaryButton>
        </Notice>
        {alert}
      </>
    );
  }

  // Dos filas de filtros con scroll horizontal: la tienda (solo si hay más de una) y el tipo de prenda.
  const filters = (
    <div className="flex flex-col gap-2">
      {enabled.length > 1 && (
        <Chips
          label={t.compras.filtros.tienda}
          options={[
            { value: null, label: t.compras.filtros.todas },
            ...enabled.map((s) => ({ value: s.key, label: s.name })),
          ]}
          value={filter.store}
          onChange={(store) => onFilter({ ...filter, store })}
        />
      )}
      <Chips
        label={t.compras.filtros.tipo}
        options={[
          { value: null, label: t.compras.filtros.todo },
          ...Object.entries(t.compras.filtros.categorias).map(([value, label]) => ({ value, label })),
        ]}
        value={filter.category}
        onChange={(category) => onFilter({ ...filter, category })}
      />
    </div>
  );

  const reasonBar = asking && (
    <ReasonBar done={asking.done} onReason={giveReason} onClose={() => ask(null)} />
  );

  const round =
    "flex items-center justify-center rounded-full shadow-[0_3px_10px_rgb(0_0_0/0.16)] transition-transform active:scale-95 disabled:[&>*]:opacity-40";
  const undoButton = (
    <button
      type="button"
      aria-label={t.compras.volverAria}
      disabled={busy || !next.can_undo}
      onClick={undo}
      className={`${round} h-11 w-11 border border-line bg-card text-text-2`}
    >
      <Icon name="undo" size={20} />
    </button>
  );

  if (item) {
    return (
      <>
        {/* Todo en una pantalla: la foto se queda con el alto que sobra, para no tener que bajar a los botones. */}
        <div ref={fit.ref} style={fit.style} className="relative -mt-2 flex min-h-[25rem] flex-col gap-2.5">
        {filters}
        <p className="truncate text-xs text-text-3">
          {state.running
            ? state.job === "mas"
              ? t.compras.mas.aviso
              : t.compras.buscando.aviso
            : state.last_more?.low
              ? t.compras.mas.encajaMenos
              : t.compras.quedan(next.remaining)}
        </p>
        <SwipeCard
          key={`${item.id}-${attempt}`}
          item={item}
          busy={busy}
          fly={fly}
          enterFrom={back?.id === item.id ? back.side : 0}
          onDecide={decide}
        />
        {alert}
        <section className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex h-16 items-center justify-center gap-6">
          <span className="pointer-events-auto absolute left-3">{undoButton}</span>
          <button
            type="button"
            aria-label={t.compras.no}
            disabled={busy}
            onClick={() => press(false)}
            className={`${round} pointer-events-auto h-16 w-16 border border-line bg-card text-danger`}
          >
            <Icon name="close" size={30} />
          </button>
          <button
            type="button"
            aria-label={t.compras.si}
            disabled={busy}
            onClick={() => press(true)}
            className={`${round} pointer-events-auto h-16 w-16 bg-primary text-on-primary`}
          >
            <Icon name="favorite_fill" size={30} />
          </button>
        </section>
        </div>
        {reasonBar}
      </>
    );
  }

  if (state.running) {
    const bringing = state.job === "mas";
    return (
      <Notice
        icon="search"
        title={bringing ? t.compras.mas.titulo : t.compras.buscando.titulo}
        text={bringing ? t.compras.mas.texto : t.compras.buscando.texto}
        pulse
      >
        <div className="h-1 w-full overflow-hidden rounded-full bg-control">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
        </div>
      </Notice>
    );
  }

  // Sin propuestas y sin nada más que traer: puede que la última consulta fallara.
  const broken = enabled.find((s) => s.status.state === "failed");
  if (broken && next.more === 0 && !next.can_undo) {
    return (
      <>
        <Notice icon="error" danger title={t.compras.fallo.titulo(broken.name)} text={t.compras.fallo.texto}>
          {broken.status.error && (
            <p className="w-full rounded-lg bg-card-2 px-3 py-2 text-left font-mono text-[11px] break-words text-text-2">
              {broken.status.error}
            </p>
          )}
          <PrimaryButton disabled={busy} onClick={() => search(broken)}>
            <Icon name="refresh" size={20} />
            {t.comun.reintentar}
          </PrimaryButton>
          <button type="button" onClick={onOpenStores} className="min-h-11 text-xs font-medium text-text-2 underline">
            {t.compras.fallo.detalle}
          </button>
        </Notice>
        {alert}
      </>
    );
  }

  // Se han visto todas las de la tanda (o las del filtro): «Ver más» trae la siguiente del catálogo
  // guardado; si ya no queda, se dice y se ofrece consultar la tienda.
  const store = enabled.find((s) => s.key === filter.store) ?? enabled[0];
  const last = enabled.map((s) => s.status.at).filter((at): at is string => !!at).sort().pop();
  const upcoming = enabled.map((s) => s.next_check).filter((d): d is string => !!d).sort()[0];
  const filterLabel = filter.category
    ? t.compras.filtros.categorias[filter.category]
    : filter.store
      ? store.name
      : null;
  const when = [
    last ? t.compras.vacio.ultima(dateTime(last)) : t.compras.vacio.nunca,
    upcoming ? t.compras.vacio.proxima(dayLabel(upcoming)) : "",
  ];
  const text =
    next.more > 0
      ? filterLabel
        ? t.compras.mas.quedanFiltro(filterLabel)
        : t.compras.mas.quedan
      : [filterLabel ? t.compras.mas.agotadoFiltro(filterLabel) : last ? t.compras.mas.agotado : "", ...when]
          .filter(Boolean)
          .join(" ");
  return (
    <>
      {filters}
      <Notice
        icon="check_circle"
        title={filterLabel ? t.compras.vacio.tituloFiltro(filterLabel) : t.compras.vacio.titulo}
        text={text}
      >
        {state.last_more?.error && state.last_more.added === 0 && (
          <p role="alert" className="text-sm text-danger">
            {t.compras.mas.error}
          </p>
        )}
        {next.more > 0 ? (
          <PrimaryButton disabled={busy} onClick={more}>
            <Icon name="add" size={20} />
            {busy ? t.compras.mas.trayendo : t.compras.mas.ver}
          </PrimaryButton>
        ) : (
          <PrimaryButton disabled={busy} onClick={() => search(store)}>
            <Icon name="search" size={20} />
            {t.compras.vacio.buscar}
          </PrimaryButton>
        )}
        {next.can_undo && (
          <SecondaryButton onClick={undo}>
            <Icon name="undo" size={18} />
            {t.compras.volver}
          </SecondaryButton>
        )}
      </Notice>
      {alert}
      {reasonBar}
    </>
  );
}

/** Una fila de chips con scroll horizontal para elegir un filtro (null = sin filtro). */
function Chips({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string | null; label: string }[];
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <div role="group" aria-label={label} className="-mx-5 flex gap-1.5 overflow-x-auto px-5">
      {options.map((o) => (
        <button
          key={o.value ?? ""}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`flex h-9 shrink-0 items-center rounded-full border border-line px-3.5 text-xs font-medium whitespace-nowrap ${
            value === o.value ? "bg-primary text-on-primary" : "bg-card-2 text-text-2"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/**
 * La pregunta opcional tras un «no me gusta». Flota bajo la cabecera, sin tapar la tarjeta ni los
 * botones, y no bloquea nada: se puede seguir deslizando y se va sola a los pocos segundos.
 */
function ReasonBar({
  done,
  onReason,
  onClose,
}: {
  done: boolean;
  onReason: (reason: ShopDiscardReason) => void;
  onClose: () => void;
}) {
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 top-0 z-40 mx-auto max-w-md">
      <div
        role="status"
        className="pointer-events-auto absolute inset-x-3 rounded-2xl border border-line bg-card px-3.5 py-2.5 shadow-float"
        style={{ top: "calc(env(safe-area-inset-top, 0px) + 4rem)" }}
      >
        {done ? (
          <p className="py-1.5 text-center text-xs text-text-2">{t.compras.motivo.anotado}</p>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="label-caps text-text-2">{t.compras.motivo.pregunta}</span>
              <button
                type="button"
                aria-label={t.compras.motivo.cerrar}
                onClick={onClose}
                className="-my-2 -mr-2.5 flex h-10 w-10 items-center justify-center text-text-2 active:opacity-60"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <div className="-mx-3.5 mt-1.5 flex gap-1.5 overflow-x-auto px-3.5">
              {REASONS.map((reason) => (
                <button
                  key={reason}
                  type="button"
                  onClick={() => onReason(reason)}
                  className="flex h-9 shrink-0 items-center rounded-full border border-line bg-card-2 px-3.5 text-xs font-medium whitespace-nowrap text-text active:scale-[0.98]"
                >
                  {t.compras.motivo.opciones[reason]}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Tarjeta de aviso centrada: icono, título, texto y lo que haga falta debajo. */
function Notice({
  icon,
  title,
  text,
  danger = false,
  pulse = false,
  children,
}: {
  icon: "cart" | "search" | "error" | "check_circle" | "favorite";
  title: string;
  text: string;
  danger?: boolean;
  pulse?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center gap-3 p-8 text-center">
      <span
        className={`flex h-14 w-14 items-center justify-center rounded-full bg-card-2 ${
          danger ? "text-danger" : "text-primary"
        } ${pulse ? "animate-pulse" : ""}`}
      >
        <Icon name={icon} size={28} />
      </span>
      <h3 className="font-display text-xl font-semibold tracking-tight">{title}</h3>
      <p className="text-sm text-text-2">{text}</p>
      {children && <div className="mt-2 flex w-full flex-col items-center gap-2">{children}</div>}
    </div>
  );
}

function Reasons({ item }: { item: ShopItem }) {
  if (item.reasons.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {item.reasons.map((r) => (
        <li
          key={r.text}
          className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
            r.kind === "contra" ? "bg-danger/10 text-danger" : "bg-chip text-on-chip"
          }`}
        >
          {r.text}
        </li>
      ))}
    </ul>
  );
}

function StoreLink({ item }: { item: ShopItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-h-11 items-center gap-1.5 text-xs font-semibold text-primary underline-offset-2 active:opacity-60"
    >
      {t.compras.verEn(item.store_name)}
      <Icon name="open_in_new" size={16} />
    </a>
  );
}

/** Alto que queda desde donde empieza el elemento hasta la barra inferior, para encajar la vista en una pantalla. */
function useFitHeight(shown: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<{ height: number; marginBottom: number }>();
  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current;
      if (!el) return;
      const gap = 18; // aire entre la vista y la barra inferior: lo justo para que la sombra de los botones no la pise
      const nav = document.querySelector("nav")?.getBoundingClientRect().height ?? 64;
      const top = el.getBoundingClientRect().top + window.scrollY;
      // La pantalla reserva bajo el contenido más hueco del que ocupa la barra. Ese sobrante se
      // descuenta con un margen negativo: si no, la página mide más que la pantalla y se puede desplazar.
      const main = el.closest("main");
      const reserved = main ? parseFloat(getComputedStyle(main).paddingBottom) || 0 : 0;
      setStyle({
        // Hacia abajo y con un píxel de margen: redondeando al alza la página medía uno de más y se movía.
        height: Math.floor(window.innerHeight - top - nav - gap) - 1,
        marginBottom: Math.min(0, Math.floor(nav + gap - reserved)),
      });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [shown]);
  return { ref, style };
}

/**
 * El color de la esquina de la foto. Las fotos de tienda tienen un fondo liso; pintando con él los
 * lados que la foto no cubre, parece que llena la tarjeta. Si no se puede leer, se queda el de la app.
 */
let lastBackdrop: string | null = null;

/**
 * ¿Es oscuro el fondo de la foto? Los puntos que indican cuántas fotos hay van encima de la foto, no
 * del tema de la app: tienen que contrastar con ella (negros sobre fondo claro, blancos sobre oscuro).
 * Sin dato se supone claro, que es lo normal en una foto de tienda.
 */
function isDark(color: string | null): boolean {
  const parts = color?.match(/\d+/g)?.map(Number);
  if (!parts || parts.length < 3) return false;
  const [r, g, b] = parts;
  return 0.299 * r + 0.587 * g + 0.114 * b < 128;
}

function cornerColor(img: HTMLImageElement): string | null {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(img, 2, 2, 6, 6, 0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return `rgb(${r} ${g} ${b})`;
  } catch {
    return null; // foto de otro origen: el lienzo no deja leerla
  }
}

const SWIPE_START = 10; // px que hay que mover para que cuente como arrastre y no como toque
const FLY_MS = 220;

/**
 * Una propuesta, tipo Tinder: deslizar a la derecha = me gusta, a la izquierda = no me gusta.
 * `touch-action: pan-y` deja el scroll vertical al navegador; el arrastre horizontal es nuestro.
 */
function SwipeCard({
  item,
  busy,
  fly,
  enterFrom,
  onDecide,
}: {
  item: ShopItem;
  busy: boolean;
  fly: -1 | 0 | 1; // un botón manda que salga volando hacia ese lado
  enterFrom: -1 | 0 | 1; // tras «Volver», el lado por el que se fue y por el que vuelve
  onDecide: (liked: boolean) => void;
}) {
  const drag = useRef<{ id: number; x: number; y: number; active: boolean } | null>(null);
  const moved = useRef(false); // para que soltar un arrastre no cuente como toque en la foto o el enlace
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState<-1 | 0 | 1>(0);
  const [entering, setEntering] = useState<-1 | 0 | 1>(enterFrom);
  useEffect(() => {
    if (fly) setLeaving(fly);
  }, [fly]);
  // Se pinta primero fuera de la pantalla y, en el siguiente fotograma, se la deja volver a su sitio.
  useEffect(() => {
    if (!entering) return;
    // Con un temporizador y no con requestAnimationFrame: si la pestaña está en segundo plano los
    // fotogramas no llegan y la tarjeta se quedaría fuera de la pantalla.
    const wait = window.setTimeout(() => setEntering(0), 30);
    return () => window.clearTimeout(wait);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Se empieza con el fondo de la foto anterior (los de una tienda se parecen) y la foto entra con un
  // fundido cuando ya está cargada y se sabe su color: así no hay salto de bandas ni parpadeo.
  const [backdrop, setBackdrop] = useState<string | null>(lastBackdrop);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [photo, setPhoto] = useState(0);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (busy || leaving || (e.pointerType === "mouse" && e.button !== 0)) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, active: false };
    moved.current = false;
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const mx = e.clientX - d.x;
    const my = e.clientY - d.y;
    if (!d.active) {
      if (Math.abs(mx) < SWIPE_START && Math.abs(my) < SWIPE_START) return;
      if (Math.abs(mx) <= Math.abs(my)) {
        drag.current = null; // es un scroll vertical: no es cosa nuestra
        return;
      }
      d.active = true;
      moved.current = true;
      setDragging(true);
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    setDx(mx);
  };

  const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    if (!d.active) return;
    setDragging(false);
    const threshold = Math.min(120, e.currentTarget.offsetWidth * 0.3);
    if (e.type === "pointerup" && Math.abs(dx) > threshold) {
      const liked = dx > 0;
      setLeaving(liked ? 1 : -1);
      timer.current = window.setTimeout(() => onDecide(liked), FLY_MS);
    } else {
      setDx(0);
    }
  };

  const shift = leaving ? leaving * 520 : entering ? entering * 520 : dx;
  const strength = Math.min(1, Math.abs(shift) / 90);
  const photos = item.photos;

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onClickCapture={(e) => {
        if (moved.current) {
          e.preventDefault();
          e.stopPropagation();
          moved.current = false;
        }
      }}
      className="card relative mb-7 flex min-h-0 flex-1 flex-col overflow-hidden select-none"
      style={{
        touchAction: "pan-y",
        transform: `translateX(${shift}px) rotate(${shift / 22}deg)`,
        transition: dragging ? "none" : `transform ${FLY_MS}ms ease-out, opacity ${FLY_MS}ms ease-out`,
        opacity: leaving || entering ? 0 : undefined,
      }}
    >
      <button
        type="button"
        aria-label={photos.length > 1 ? t.compras.fotoN(photo + 1, photos.length) : undefined}
        disabled={photos.length < 2}
        onClick={() => setPhoto((n) => (n + 1) % photos.length)}
        className="relative block min-h-0 w-full flex-1 overflow-hidden bg-card-2 transition-colors duration-300"
        style={backdrop ? { backgroundColor: backdrop } : undefined}
      >
        {photos[photo] && (
          <img
            src={mediaUrl(photos[photo].url)}
            alt={item.name}
            draggable={false}
            onLoad={(e) => {
              const color = cornerColor(e.currentTarget);
              if (color) {
                lastBackdrop = color;
                setBackdrop(color);
              }
              setLoaded(photos[photo].url);
            }}
            className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-300 ${
              loaded === photos[photo].url ? "opacity-100" : "opacity-0"
            }`}
          />
        )}
        {photos.length > 1 && (
          <span className="absolute inset-x-0 top-3 flex justify-center gap-1.5">
            {photos.map((p, i) => (
              <span key={p.id} className={`h-1.5 rounded-full ${isDark(backdrop) ? "bg-white" : "bg-black"} ${
                  i === photo ? "w-4 opacity-70" : "w-1.5 opacity-30"
                }`} />
            ))}
          </span>
        )}
      </button>

      {/* Sellos que aparecen al arrastrar */}
      <span
        aria-hidden="true"
        className="label-caps pointer-events-none absolute top-4 left-4 -rotate-12 rounded-lg border-2 border-ok bg-card px-2.5 py-1.5 text-ok"
        style={{ opacity: shift > 0 ? strength : 0 }}
      >
        {t.compras.selloSi}
      </span>
      <span
        aria-hidden="true"
        className="label-caps pointer-events-none absolute top-4 right-4 rotate-12 rounded-lg border-2 border-danger bg-card px-2.5 py-1.5 text-danger"
        style={{ opacity: shift < 0 ? strength : 0 }}
      >
        {t.compras.selloNo}
      </span>

      {/* La ficha. El hueco de abajo es para los botones flotantes, que pisan el borde de la tarjeta. */}
      <div className="flex shrink-0 flex-col gap-1 px-4 pt-3 pb-10">
        <div className="flex items-baseline justify-between gap-3">
          <span className="label-caps min-w-0 truncate text-text-2">
            {[item.store_name, cap(item.type), item.store_color].filter(Boolean).join(" · ")}
          </span>
          <span className="shrink-0 font-display text-lg font-semibold">{t.compras.precio(item.price_cents)}</span>
        </div>
        <h3 className="truncate font-display text-base leading-snug font-semibold tracking-tight">{item.name}</h3>
        <div className="flex items-center justify-between gap-2">
          <div className="max-h-[1.75rem] min-w-0 overflow-hidden">
            <Reasons item={item} />
          </div>
          <div className="shrink-0">
            <StoreLink item={item} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** La foto de una prenda guardada, en grande: solo la foto, el nombre, el precio y el enlace. */
function PhotoViewer({ item, onClose }: { item: ShopItem; onClose: () => void }) {
  const [photo, setPhoto] = useState(0);
  const [backdrop, setBackdrop] = useState<string | null>(lastBackdrop);
  const [loaded, setLoaded] = useState<string | null>(null);
  const photos = item.photos;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // que no se mueva la lista de debajo
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={item.name}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim px-4 backdrop-blur-[2px]"
      style={{
        paddingTop: "calc(env(safe-area-inset-top, 0px) + 1rem)",
        paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1rem)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card relative flex h-full max-h-[46rem] w-full max-w-md flex-col overflow-hidden"
      >
        <button
          type="button"
          aria-label={photos.length > 1 ? t.compras.fotoN(photo + 1, photos.length) : undefined}
          disabled={photos.length < 2}
          onClick={() => setPhoto((n) => (n + 1) % photos.length)}
          className="relative block min-h-0 w-full flex-1 overflow-hidden bg-card-2 transition-colors duration-300"
          style={backdrop ? { backgroundColor: backdrop } : undefined}
        >
          {photos[photo] && (
            <img
              key={photos[photo].id}
              src={mediaUrl(photos[photo].url)}
              alt={item.name}
              draggable={false}
              onLoad={(e) => {
                const color = cornerColor(e.currentTarget);
                if (color) setBackdrop(color);
                setLoaded(photos[photo].url);
              }}
              className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-300 ${
                loaded === photos[photo].url ? "opacity-100" : "opacity-0"
              }`}
            />
          )}
          {photos.length > 1 && (
            <span className="absolute inset-x-0 top-3 flex justify-center gap-1.5">
              {photos.map((p, i) => (
                <span
                  key={p.id}
                  className={`h-1.5 rounded-full ${isDark(backdrop) ? "bg-white" : "bg-black"} ${
                    i === photo ? "w-4 opacity-70" : "w-1.5 opacity-30"
                  }`}
                />
              ))}
            </span>
          )}
        </button>
        <button
          type="button"
          aria-label={t.compras.panel.cerrar}
          onClick={onClose}
          className="absolute top-3 right-3 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-card text-text shadow-[0_3px_10px_rgb(0_0_0/0.16)] active:scale-95"
        >
          <Icon name="close" size={20} />
        </button>
        <div className="flex shrink-0 flex-col gap-1 px-4 pt-3 pb-2">
          <div className="flex items-baseline justify-between gap-3">
            <span className="label-caps min-w-0 truncate text-text-2">
              {[item.store_name, cap(item.type), item.store_color].filter(Boolean).join(" · ")}
            </span>
            <span className="shrink-0 font-display text-lg font-semibold">{t.compras.precio(item.price_cents)}</span>
          </div>
          <h3 className="font-display text-base leading-snug font-semibold tracking-tight">{item.name}</h3>
          <StoreLink item={item} />
        </div>
      </div>
    </div>
  );
}

// ---------- Me gustan

function Liked({ onChanged }: { onChanged: () => void }) {
  const navigate = useNavigate();
  const [items, setItems] = useState<ShopItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [removing, setRemoving] = useState<ShopItem | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  // «La he comprado»: de qué producto se está eligiendo talla.
  const [buying, setBuying] = useState<number | null>(null);
  const [viewing, setViewing] = useState<ShopItem | null>(null);
  const [size, setSize] = useState<string | null>(null);
  const [buyBusy, setBuyBusy] = useState(false);
  const [buyError, setBuyError] = useState<string | null>(null);

  const load = useCallback(() => {
    setFailed(false);
    api.shopLiked().then(setItems).catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);

  const remove = () => {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    api
      .shopRemove(removing.id)
      .then(() => {
        setItems((list) => list?.filter((i) => i.id !== removing.id) ?? null);
        setRemoving(null);
        onChanged();
      })
      .catch(() => setRemoveError(t.compras.gustados.errorQuitar))
      .finally(() => setRemoveBusy(false));
  };

  const startBuying = (item: ShopItem) => {
    const available = item.sizes.filter((s) => s.in_stock);
    setBuying(item.id);
    setSize(available.length === 1 ? available[0].name : null);
    setBuyError(null);
  };

  const buy = (item: ShopItem) => {
    setBuyBusy(true);
    setBuyError(null);
    api
      .shopBought(item.id, size)
      .then((result) => navigate(`/prenda/${result.garment_id}`))
      .catch((e) => {
        setBuyError(e instanceof ApiError && e.status < 500 ? e.message : t.compras.gustados.errorComprar);
        setBuyBusy(false);
      });
  };

  if (failed) {
    return (
      <div className="card flex flex-col items-center gap-3 p-6 text-center">
        <Icon name="error" className="text-danger" size={28} />
        <p className="text-sm text-text-2">{t.comun.errorRed}</p>
        <button type="button" onClick={load} className="min-h-11 px-3 text-sm font-semibold text-primary">
          {t.comun.reintentar}
        </button>
      </div>
    );
  }
  if (!items) return <p className="mt-6 text-center text-sm text-text-3">{t.comun.cargando}</p>;
  if (items.length === 0) {
    return <Notice icon="favorite" title={t.compras.gustados.vacioTitulo} text={t.compras.gustados.vacioTexto} />;
  }

  return (
    <>
      {viewing && <PhotoViewer item={viewing} onClose={() => setViewing(null)} />}
      <ul className="flex flex-col gap-3">
        {items.map((item) => {
          const available = item.sizes.filter((s) => s.in_stock);
          const open = buying === item.id;
          return (
            <li key={item.id} className="card flex flex-col gap-3 p-3.5">
              {/* Tocar la tarjeta (no los botones ni el enlace) abre la foto en grande. */}
              <div className="flex cursor-pointer gap-3.5" onClick={() => setViewing(item)}>
                {item.photos[0] && (
                  <button
                    type="button"
                    aria-label={t.compras.gustados.verFoto(item.name)}
                    className="h-32 w-24 shrink-0 overflow-hidden rounded-xl bg-card-2 active:opacity-80"
                  >
                    <img src={mediaUrl(item.photos[0].thumb_url)} alt="" className="h-full w-full object-cover" />
                  </button>
                )}
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="label-caps text-text-2">
                    {item.store_name} · {cap(item.type)}
                  </span>
                  <h3 className="text-base leading-snug font-medium">{item.name}</h3>
                  <span className="font-display text-lg font-semibold">{t.compras.precio(item.price_cents)}</span>
                  {item.expires_soon && (
                    <span className="flex w-fit items-center gap-1 rounded-full bg-danger/10 px-2 py-0.5 text-[11px] font-medium text-danger">
                      <Icon name="schedule" size={13} />
                      {t.compras.gustados.caducaPronto}
                      {item.expires_at && ` · ${t.compras.gustados.caducaEl(dayMonth(item.expires_at))}`}
                    </span>
                  )}
                  <div className="mt-auto w-fit" onClick={(e) => e.stopPropagation()}>
                    <StoreLink item={item} />
                  </div>
                </div>
              </div>

              {open ? (
                <div className="flex flex-col gap-3 border-t border-control pt-3">
                  {buyBusy ? (
                    <p className="text-xs text-text-2">{t.compras.gustados.analizandoTexto}</p>
                  ) : available.length > 0 ? (
                    <>
                      <span className="label-caps text-text-2">{t.compras.gustados.talla}</span>
                      <div className="flex flex-wrap gap-1.5">
                        {available.map((s) => (
                          <button
                            key={s.name}
                            type="button"
                            aria-pressed={size === s.name}
                            onClick={() => setSize(s.name)}
                            className={`min-h-11 min-w-11 rounded-xl border px-3 text-sm font-medium ${
                              size === s.name
                                ? "border-primary bg-primary text-on-primary"
                                : "border-line bg-card-2 text-text-2"
                            }`}
                          >
                            {s.name}
                          </button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-text-2">{t.compras.gustados.sinTallas}</p>
                  )}
                  {buyError && (
                    <p role="alert" className="text-sm text-danger">
                      {buyError}
                    </p>
                  )}
                  <PrimaryButton disabled={buyBusy || (available.length > 0 && !size)} onClick={() => buy(item)}>
                    {buyBusy ? t.compras.gustados.analizando : t.compras.gustados.confirmar}
                  </PrimaryButton>
                  {!buyBusy && (
                    <button
                      type="button"
                      onClick={() => setBuying(null)}
                      className="h-11 text-xs font-medium text-text-2 underline"
                    >
                      {t.comun.cancelar}
                    </button>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-[1fr_auto] gap-2">
                  <button
                    type="button"
                    disabled={buyBusy}
                    onClick={() => startBuying(item)}
                    className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-3 text-xs font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
                  >
                    <Icon name="check_circle" size={18} />
                    {t.compras.gustados.comprada}
                  </button>
                  <button
                    type="button"
                    disabled={buyBusy}
                    onClick={() => {
                      setRemoveError(null);
                      setRemoving(item);
                    }}
                    className="flex h-11 items-center justify-center gap-1.5 rounded-xl border border-line bg-control px-4 text-xs font-medium text-text active:scale-[0.98] disabled:opacity-40"
                  >
                    <Icon name="delete_icon" size={18} />
                    {t.compras.gustados.quitar}
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={removing !== null}
        title={t.compras.gustados.quitarTitulo}
        text={removing ? `${removing.name}. ${t.compras.gustados.quitarTexto}` : undefined}
        confirmLabel={t.compras.gustados.quitar}
        busyLabel={t.compras.gustados.quitando}
        busy={removeBusy}
        error={removeError}
        onConfirm={remove}
        onCancel={() => setRemoving(null)}
      />
    </>
  );
}

// ---------- Tiendas

const STATUS_DOT: Record<string, string> = { ok: "bg-ok", failed: "bg-danger", never: "bg-text-3" };
const STATUS_TEXT: Record<string, string> = { ok: "text-ok", failed: "text-danger", never: "text-text-2" };

/** Panel «Tiendas»: qué tiendas se consultan, qué categorías interesan y cómo fue la última consulta. */
function StoresPanel({
  state,
  onState,
  onClose,
}: {
  state: ShopState;
  onState: (s: ShopState) => void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const act = (request: Promise<ShopState>, message: string) => {
    setBusy(true);
    setError(null);
    request
      .then(onState)
      .catch((e) => setError(e instanceof ApiError && e.status < 500 ? e.message : message))
      .finally(() => setBusy(false));
  };

  const toggleCategory = (store: ShopStore, slug: string) => {
    const chosen = store.categories.filter((c) => (c.slug === slug ? !c.enabled : c.enabled)).map((c) => c.slug);
    act(api.shopSettings({ store: store.key, categories: chosen }), t.compras.panel.errorGuardar);
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-scrim backdrop-blur-[2px]"
      style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 2.5rem)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.compras.panel.titulo}
        className="flex max-h-full w-full max-w-md flex-col rounded-t-3xl border border-line bg-bg"
      >
        <div className="flex items-center justify-between gap-2 py-3 pr-2 pl-5">
          <h2 className="font-display text-lg font-semibold tracking-tight">{t.compras.panel.titulo}</h2>
          <button
            ref={closeButton}
            type="button"
            aria-label={t.compras.panel.cerrar}
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center active:opacity-60"
          >
            <Icon name="close" size={22} />
          </button>
        </div>
        <div
          className="flex flex-col gap-4 overflow-y-auto px-5"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1.5rem)" }}
        >
          <p className="text-sm text-text-2">{t.compras.panel.intro}</p>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          {state.stores.map((store) => {
            const status = store.status;
            return (
              <section key={store.key} className="card flex flex-col gap-3.5 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-display text-base font-semibold">{store.name}</h3>
                    <p className={`flex items-center gap-1.5 text-xs font-semibold ${STATUS_TEXT[status.state]}`}>
                      <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status.state]}`} />
                      {t.compras.panel.estado[status.state]}
                    </p>
                  </div>
                  <Switch
                    checked={store.enabled}
                    label={t.compras.panel.activada(store.name)}
                    onChange={() =>
                      !busy &&
                      act(api.shopSettings({ store: store.key, enabled: !store.enabled }), t.compras.panel.errorGuardar)
                    }
                  />
                </div>

                <div className="flex flex-col gap-1 text-xs text-text-2">
                  {status.at && (
                    <>
                      <p>{t.compras.panel.ultima(dateTime(status.at))}</p>
                      <p>{t.compras.panel.trajo(status.found, status.added)}</p>
                      <p className={status.failed > 0 ? "text-danger" : ""}>
                        {status.failed > 0 ? t.compras.panel.fallaron(status.failed) : t.compras.panel.sinFallos}
                      </p>
                    </>
                  )}
                  {status.error && (
                    <p className="rounded-lg bg-card-2 px-3 py-2 font-mono text-[11px] break-words text-text">
                      <span className="font-sans font-semibold">{t.compras.panel.error}: </span>
                      {status.error}
                    </p>
                  )}
                  <p>{t.compras.panel.dia(t.compras.dias[store.weekday] ?? "")}</p>
                  <p>
                    {store.enabled && store.next_check
                      ? t.compras.panel.proxima(dayLabel(store.next_check))
                      : t.compras.panel.desactivadaTexto}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <span className="label-caps text-text-2">{t.compras.panel.categorias}</span>
                  <div className="flex flex-wrap gap-1.5">
                    {store.categories.map((c) => (
                      <button
                        key={c.slug}
                        type="button"
                        aria-pressed={c.enabled}
                        disabled={busy}
                        onClick={() => toggleCategory(store, c.slug)}
                        className={`min-h-11 rounded-full border px-3 py-2 text-xs font-medium ${
                          c.enabled ? "border-primary bg-primary text-on-primary" : "border-line bg-card-2 text-text-2"
                        }`}
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>
                </div>

                <PrimaryButton
                  disabled={busy || state.running || !store.enabled}
                  onClick={() => act(api.shopRefresh(store.key), t.compras.panel.errorConsultar)}
                >
                  <Icon name="refresh" size={20} />
                  {state.running ? t.compras.panel.consultando : t.compras.panel.consultar}
                </PrimaryButton>
              </section>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
