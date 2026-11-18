import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { inputClass, PrimaryButton, SecondaryButton, Segmented, Switch } from "../components/Controls";
import { externalHref, photoAfterTap } from "../lib/links";
import { CopyRow } from "../components/CopyButton";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { CardSkeleton, ListSkeleton, stagger } from "../components/Skeleton";
import { cap, t } from "../i18n/es";
import {
  api,
  ApiError,
  mediaUrl,
  type ShopColor,
  type ShopCrawl,
  type ShopDiscardReason,
  type ShopFilter,
  type ShopItem,
  type ShopLookupItem,
  type ShopMatches,
  type ShopNext,
  type ShopState,
  type ShopStore,
} from "../lib/api";

type View = "descubrir" | "gustados";

const POLL_MS = 4000; // cada cuánto se pregunta cómo va la consulta (o el «Ver más») en marcha
const PHOTO_POLL_MS = 20_000; // cada cuánto se mira si ha llegado la foto que faltaba (se baja en segundo plano)
const REASON_DONE_MS = 1500;
// «Es caro» no se ofrece: el usuario no quiere que el precio sea un motivo.
const REASONS: ShopDiscardReason[] = ["estilo", "color", "ya_tengo"];
const NO_FILTER: ShopFilter = { store: null, category: null };
const topButton =
  "relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-line bg-control text-text active:scale-[0.98] disabled:opacity-40";

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

/**
 * Mientras alguno de `items` espera su foto (`photo_pending`: se está bajando en segundo plano), pregunta de vez
 * en cuando por ESOS items y pasa a `onArrived` los que ya la tienen. No recarga la lista entera, y con la
 * pestaña del navegador escondida no pregunta.
 */
function usePendingPhotos(items: ShopItem[] | null, onArrived: (fresh: ShopLookupItem[]) => void) {
  const ids = (items ?? []).filter((item) => item.photo_pending).map((item) => item.id).join(",");
  const arrived = useRef(onArrived);
  arrived.current = onArrived;
  useEffect(() => {
    if (!ids) return;
    const wanted = ids.split(",").map(Number);
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      api
        .shopItems(wanted)
        .then((fresh) => {
          const ready = fresh.filter((item) => !item.photo_pending);
          if (ready.length > 0) arrived.current(ready);
        })
        .catch(() => {}); // sin red: se vuelve a mirar en la siguiente vuelta
    }, PHOTO_POLL_MS);
    return () => window.clearInterval(timer);
  }, [ids]);
}

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
  // El buscador por referencia. Si en él se guarda o se compra algo, al cerrarlo se pone todo al día.
  const [searchOpen, setSearchOpen] = useState(false);
  const searchChanged = useRef(false);
  const [likedVersion, setLikedVersion] = useState(0);
  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    if (!searchChanged.current) return;
    searchChanged.current = false;
    setLikedVersion((n) => n + 1);
    load();
  }, [load]);

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

  // Mientras hay una consulta, un «Ver más» o una reposición en marcha se sondea el estado (y el
  // avance); al terminar, o en cuanto hay propuestas, se piden.
  const running = (state?.running ?? false) || Boolean(state?.refilling) || Boolean(next?.refilling);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      // Si un sondeo falla no pasa nada: el siguiente lo vuelve a intentar.
      api
        .shopState()
        .then((s) => {
          setState(s);
          // Si ya se está viendo una tarjeta, no se toca (la pila se pone al día al decidir).
          if (!s.running || s.pending > 0)
            api
              .shopNext(filterRef.current)
              .then((n) =>
                setNext((now) => keepShown(now, n)),
              )
              .catch(() => undefined);
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
                  { value: "descubrir", label: t.compras.descubrirN(state?.pending ?? 0) },
                  { value: "gustados", label: t.compras.meGustanN(state?.liked ?? 0) },
                ]}
                value={view}
                onChange={setView}
              />
            </div>
            {/* Solo icono: con el texto, la fila no cabe en un móvil de 375 px. */}
            <button
              type="button"
              aria-label={t.compras.buscador.abrir}
              title={t.compras.buscador.abrir}
              onClick={() => setSearchOpen(true)}
              className={topButton}
            >
              <Icon name="search" size={20} />
            </button>
            <button
              type="button"
              aria-label={t.compras.tiendas}
              title={t.compras.tiendas}
              onClick={() => setStoresOpen(true)}
              disabled={!state}
              className={topButton}
            >
              <Icon name="store" size={20} />
              {state?.stores.some((s) => s.enabled && s.status.state === "failed") && (
                <span className="absolute top-2 right-2 h-2 w-2 rounded-full bg-danger" />
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
          {!failed && (!state || !next) && (view === "gustados" ? <ListSkeleton /> : <DiscoverSkeleton />)}

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
              // Otro color de la misma prenda (o sus colores recién sabidos): cambia la tarjeta, no la cola.
              onItem={(from, item) => setNext((n) => (n && n.item?.id === from ? { ...n, item } : n))}
              onOpenStores={() => setStoresOpen(true)}
            />
          )}
          {!failed && state && next && view === "gustados" && (
            <Liked key={likedVersion} onChanged={() => api.shopState().then(setState).catch(() => undefined)} />
          )}
        </div>
      </Screen>
      <BottomNav />
      {storesOpen && state && <StoresPanel state={state} onState={setState} onClose={closeStores} />}
      {searchOpen && <SearchPanel onChanged={() => (searchChanged.current = true)} onClose={closeSearch} />}
    </>
  );
}

// ---------- Descubrir

/** El hueco de Descubrir mientras carga, con el mismo alto que la vista real (ver `useFitHeight`). */
function DiscoverSkeleton() {
  const fit = useFitHeight(true);
  return <CardSkeleton boxRef={fit.ref} style={fit.style} />;
}

/** Lo que dice el servidor, sin mover lo que ya se ve. El servidor ordena por nota, y al llegar
 *  propuestas nuevas (una consulta en marcha, una reposición) la lista se reordena: las dos tarjetas
 *  que hay en pantalla, la de arriba y la de debajo, se quedan donde están y lo nuevo entra detrás.
 *  `skip` son las que se están decidiendo: no vuelven aunque la respuesta aún las traiga. */
function keepShown(shown: ShopNext | null, answer: ShopNext, skip?: Set<number>): ShopNext {
  const fresh = [answer.item, ...answer.queue].filter(
    (other): other is ShopItem => other !== null && !skip?.has(other.id),
  );
  // Si el servidor ya no tiene nada pendiente, manda él.
  const visible = fresh.length
    ? [shown?.item, shown?.queue[0]].filter((other): other is ShopItem => other != null && !skip?.has(other.id))
    : [];
  const all = [...visible, ...fresh.filter((other) => !visible.some((seen) => seen.id === other.id))];
  return { ...answer, item: all[0] ?? null, queue: all.slice(1, 3) };
}

function Discover({
  state,
  next,
  filter,
  onFilter,
  onState,
  onNext,
  onItem,
  onOpenStores,
}: {
  state: ShopState;
  next: ShopNext;
  filter: ShopFilter;
  onFilter: (f: ShopFilter) => void;
  onState: (s: ShopState) => void;
  onNext: (n: ShopNext) => void;
  onItem: (from: number, item: ShopItem) => void;
  onOpenStores: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fit = useFitHeight(Boolean(next.item));
  const [viewing, setViewing] = useState<ShopItem | null>(null);
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

  // La pila: las decisiones se enseñan al momento (la de debajo pasa arriba sin esperar al servidor) y
  // se guardan en orden, una detrás de otra. `deciding` son las que aún no ha confirmado el servidor:
  // no deben volver a salir aunque una respuesta anterior aún las traiga.
  const latest = useRef(next);
  latest.current = next;
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const deciding = useRef(new Set<number>());

  const ask = (value: { id: number; done: boolean } | null, ms = 0) => {
    window.clearTimeout(askTimer.current);
    setAsking(value);
    if (value) askTimer.current = window.setTimeout(() => setAsking(null), ms);
  };

  const enabled = state.stores.filter((s) => s.enabled);
  const item = next.item;
  const behind = next.queue[0] ?? null;

  // Precarga: la primera foto de la actual, de la siguiente y de la que va detrás (la segunda de la
  // actual la precarga la propia tarjeta).
  useEffect(() => {
    for (const shopItem of [item, ...next.queue]) {
      if (shopItem?.photos[0]) preloadPhoto(mediaUrl(shopItem.photos[0].url));
    }
  }, [item, next.queue]);

  // La tarjeta de debajo crece según se aparta la de arriba.
  const backCard = useRef<HTMLDivElement>(null);
  const growBehind = useCallback((shift: number) => {
    const el = backCard.current;
    if (!el) return;
    const p = Math.min(1, Math.abs(shift) / 160);
    el.style.transform = `translateY(${(1 - p) * 8}px) scale(${0.955 + 0.045 * p})`;
  }, []);
  useLayoutEffect(() => growBehind(0), [item?.id, growBehind]);

  // Al elegir otro color cambia el item, pero la tarjeta es la misma: no debe entrar de nuevo ni
  // perder su sitio. Aquí se apunta a qué tarjeta pertenece cada color.
  const cards = useRef(new Map<number, number>());
  const colors = useColors(item, (found, from) => {
    if (found.id !== from.id) cards.current.set(found.id, cards.current.get(from.id) ?? from.id);
    onItem(from.id, found);
  });

  /** Lo que dice el servidor, sin deshacer lo que ya se ve: la tarjeta de arriba se queda si sigue pendiente. */
  const merge = (answer: ShopNext): ShopNext => ({
    ...keepShown(latest.current, answer, deciding.current),
    remaining: Math.max(0, answer.remaining - deciding.current.size),
  });

  const decide = (liked: boolean) => {
    if (!item || colors.pending) return;
    const id = item.id;
    sides.current.set(id, liked ? 1 : -1);
    setError(null);
    setFly(0);
    setBack(null);
    ask(null);
    deciding.current.add(id);
    // Optimista: la de debajo pasa arriba ya.
    const now = latest.current;
    onNext({
      ...now,
      item: now.queue[0] ?? null,
      queue: now.queue.slice(1),
      remaining: Math.max(0, now.remaining - 1),
      can_undo: true,
    });
    chain.current = chain.current
      .then(() => (liked ? api.shopLike(id, filter) : api.shopDislike(id, filter)))
      .then((answer) => {
        deciding.current.delete(id);
        onNext(merge(answer));
      })
      .catch(() => {
        // No se guardó: la tarjeta vuelve (el servidor la sigue teniendo pendiente).
        deciding.current.delete(id);
        setError(t.compras.errorAccion);
        setAttempt((n) => n + 1);
        return api.shopNext(filter).then((answer) => onNext(keepShown(null, answer, deciding.current))).catch(() => undefined);
      });
  };

  /** Botón de la X o del corazón: la tarjeta sale volando hacia su lado y luego se guarda la decisión. */
  const press = (liked: boolean) => {
    if (!item || busy || fly || colors.pending) return;
    setFly(liked ? 1 : -1);
    flyTimer.current = window.setTimeout(() => decide(liked), FLY_MS);
  };

  /** «Volver»: deshace la última decisión y vuelve a enseñar esa tarjeta, encima de la pila. */
  const undo = () => {
    if (busy || !next.can_undo) return;
    setBusy(true);
    setError(null);
    ask(null);
    chain.current = chain.current
      .then(() => api.shopUndo(filter))
      .then((n) => {
        if (n.item) setBack({ id: n.item.id, side: sides.current.get(n.item.id) ?? -1 });
        onNext({ ...n, queue: n.queue.filter((other) => !deciding.current.has(other.id)) });
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

  const alert = (error || colors.error) && (
    <p role="alert" className="text-center text-sm text-danger">
      {error || colors.error}
    </p>
  );

  // Ninguna tienda activada: se explica qué es esto y se ofrece activarla.
  if (enabled.length === 0) {
    const [store, ...others] = state.stores;
    if (!store) return null;
    return (
      <>
        <Notice
          icon="cart"
          title={t.compras.desactivada.titulo}
          text={t.compras.desactivada.texto(state.stores.map((s) => s.name))}
        >
          <PrimaryButton disabled={busy} onClick={() => search(store)}>
            {busy ? t.compras.desactivada.activando : t.compras.desactivada.activar(store.name)}
          </PrimaryButton>
          {others.map((other) => (
            <SecondaryButton key={other.key} onClick={() => !busy && search(other)}>
              {t.compras.desactivada.activar(other.name)}
            </SecondaryButton>
          ))}
        </Notice>
        {alert}
      </>
    );
  }

  // Dos filas de filtros con scroll horizontal: la tienda (solo si hay más de una) y el tipo de prenda.
  // Se ven siempre: también mientras se consulta y cuando el filtro se queda sin propuestas.
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
    "flex items-center justify-center rounded-full transition-transform active:scale-95 disabled:[&>*]:opacity-40";
  // La sombra va aparte: la suave de siempre se pierde alrededor de un botón oscuro, así que el
  // corazón lleva la de los botones flotantes (más marcada), para que los tres floten igual.
  const soft = "shadow-[0_3px_10px_rgb(0_0_0/0.16)]";
  const undoButton = (
    <button
      type="button"
      aria-label={t.compras.volverAria}
      disabled={busy || !next.can_undo}
      onClick={undo}
      className={`${round} ${soft} h-11 w-11 border border-line bg-card text-text-2`}
    >
      <Icon name="undo" size={20} />
    </button>
  );

  // Qué está pasando de verdad (para la línea de arriba y los avisos): qué se trae y de dónde.
  const store = enabled.find((s) => s.key === filter.store) ?? enabled[0];
  const filtered = filter.category !== null || filter.store !== null;
  const what = filter.category
    ? (t.compras.filtros.categorias[filter.category] ?? "").toLowerCase()
    : filter.store
      ? t.compras.ocupado.deTienda(store.name)
      : t.compras.ocupado.cosas;
  const status = activity(state, next, filter, what);

  if (item) {
    return (
      <>
        {viewing && (
          <PhotoViewer
            item={viewing}
            onClose={() => {
              setViewing(null);
              api.shopNext(filter).then((n) => onNext(merge(n))).catch(() => undefined);
            }}
          />
        )}
        {/* Todo en una pantalla: la foto se queda con el alto que sobra, para no tener que bajar a los botones. */}
        <div ref={fit.ref} style={fit.style} className="relative -mt-2 flex min-h-[25rem] flex-col gap-2.5">
        {filters}
        {(status || state.last_more?.low) && (
          <button
            type="button"
            onClick={status?.crawl ? onOpenStores : undefined}
            className="-my-1 truncate py-1 text-left text-xs text-text-3"
          >
            {status ? status.text : t.compras.mas.encajaMenos}
          </button>
        )}
        {/* La pila: la de debajo ya pintada (con su foto) y sin sumar alto; la tercera solo se precarga. */}
        <div className="relative flex min-h-0 flex-1 flex-col">
          {behind && (
            <div
              ref={backCard}
              className="pointer-events-none absolute inset-0 flex flex-col transition-transform duration-150 ease-out"
              style={{ transform: "translateY(8px) scale(0.955)" }}
            >
              <SwipeCard
                key={behind.id}
                still
                item={behind}
                busy
                pending={null}
                onColor={() => undefined}
                fly={0}
                enterFrom={0}
                onDecide={() => undefined}
                onOpen={() => undefined}
              />
            </div>
          )}
          <SwipeCard
            key={`${cards.current.get(item.id) ?? item.id}-${attempt}`}
            item={item}
            busy={busy || colors.pending !== null}
            pending={colors.pending}
            onColor={colors.pick}
            fly={fly}
            enterFrom={back?.id === item.id ? back.side : 0}
            onDecide={decide}
            onOpen={() => setViewing(item)}
            onShift={growBehind}
          />
        </div>
        {alert}
        <section className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex h-16 items-center justify-center gap-6">
          <span className="pointer-events-auto absolute left-3">{undoButton}</span>
          <button
            type="button"
            aria-label={t.compras.no}
            disabled={busy || colors.pending !== null}
            onClick={() => press(false)}
            className={`${round} ${soft} pointer-events-auto h-16 w-16 border border-line bg-card text-danger`}
          >
            <Icon name="close" size={30} />
          </button>
          <button
            type="button"
            aria-label={t.compras.si}
            disabled={busy || colors.pending !== null}
            onClick={() => press(true)}
            className={`${round} ${soft} pointer-events-auto h-16 w-16 border border-line bg-card text-primary`}
          >
            <Icon name="favorite_fill" size={30} />
          </button>
        </section>
        </div>
        {reasonBar}
      </>
    );
  }

  // De verdad no hay nada que enseñar en ningún filtro y se está leyendo el catálogo (la primera
  // consulta): la tarjeta grande, con el avance real.
  if (state.crawl && state.pending === 0 && !next.can_undo) {
    return (
      <>
        {filters}
        <Notice icon="search" title={t.compras.buscando.titulo} text={t.compras.buscando.texto}>
          <CrawlProgress crawl={state.crawl} />
          <button type="button" onClick={onOpenStores} className="min-h-11 text-xs font-medium text-text-2 underline">
            {t.compras.ocupado.tiendas}
          </button>
        </Notice>
        {alert}
      </>
    );
  }

  // El filtro se ha quedado vacío mientras se trae más (la consulta, un «Ver más» o la reposición de
  // ese tipo): se dice qué pasa, sin bloquear. Se puede quitar el filtro o volver atrás.
  if (status) {
    return (
      <>
        {filters}
        <section className="card flex flex-col gap-3 p-4">
          <p className="text-sm text-text">
            {filtered ? `${t.compras.ocupado.vacioFiltro(what)} ` : ""}
            {status.text}
            {filtered && state.pending > 0 ? ` ${t.compras.ocupado.mientras}` : ""}
          </p>
          {status.crawl && state.crawl && <CrawlProgress crawl={state.crawl} />}
          <div className={`grid gap-2 ${filtered && state.pending > 0 && next.can_undo ? "grid-cols-2" : ""}`}>
            {filtered && state.pending > 0 && (
              <SecondaryButton onClick={() => onFilter({ store: null, category: null })}>
                {t.compras.ocupado.verTodo}
              </SecondaryButton>
            )}
            {next.can_undo && (
              <SecondaryButton onClick={undo}>
                <Icon name="undo" size={18} />
                {t.compras.volver}
              </SecondaryButton>
            )}
          </div>
          {status.crawl && (
            <button type="button" onClick={onOpenStores} className="-my-2 min-h-11 self-start text-xs font-medium text-text-2 underline">
              {t.compras.ocupado.tiendas}
            </button>
          )}
        </section>
        {alert}
      </>
    );
  }

  // Sin propuestas y sin nada más que traer: puede que la última consulta fallara.
  const broken = enabled.find((s) => s.status.state === "failed");
  if (broken && next.more === 0 && !next.can_undo) {
    return (
      <>
        {filters}
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
  // guardado; si ya no queda, se dice tal cual y cuándo llegará más.
  const last = enabled.map((s) => s.status.at).filter((at): at is string => !!at).sort().pop();
  // Con el filtro de una tienda, lo que importa es cuándo le toca a esa.
  const upcoming = nextConsult(filter.store ? [store] : enabled);
  const filterLabel = filter.category
    ? t.compras.filtros.categorias[filter.category]
    : filter.store
      ? store.name
      : null;
  const when = [
    last ? t.compras.vacio.ultima(dateTime(last)) : t.compras.vacio.nunca,
    upcoming ? t.compras.vacio.proxima(upcoming) : "",
  ];
  const text =
    next.more > 0
      ? filterLabel
        ? t.compras.mas.quedanFiltro(filterLabel)
        : t.compras.mas.quedan
      : filter.store && !filter.category
        ? t.compras.mas.sinMasTienda(store.name)
        : filterLabel
        ? upcoming
          ? t.compras.ocupado.sinMas(what, upcoming)
          : t.compras.ocupado.sinMasNunca(what)
        : [last ? t.compras.mas.agotado : "", ...when].filter(Boolean).join(" ");
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
            {busy ? t.compras.mas.trayendo : filter.store ? t.compras.mas.verDe(store.name) : t.compras.mas.ver}
          </PrimaryButton>
        ) : filter.store ? (
          // De esa tienda no queda nada guardado: lo único que trae más es volver a consultarla.
          <>
            <PrimaryButton disabled={busy} onClick={() => search(store)}>
              <Icon name="search" size={20} />
              {t.compras.mas.consultar(store.name)}
            </PrimaryButton>
            {state.pending > 0 && (
              <SecondaryButton onClick={() => onFilter({ store: null, category: null })}>
                {t.compras.ocupado.verTodo}
              </SecondaryButton>
            )}
          </>
        ) : filtered && state.pending > 0 ? (
          <PrimaryButton onClick={() => onFilter({ store: null, category: null })}>{t.compras.ocupado.verTodo}</PrimaryButton>
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

/**
 * Qué se está haciendo ahora que afecte a lo que se ve en Descubrir, en claro: traer más de lo que se
 * está mirando («Trayendo más chaquetas y abrigos…») o consultar una tienda («Ahora mismo estoy
 * consultando Bershka (sección 4 de 11)…»). null si no hay nada en marcha.
 */
function activity(
  state: ShopState,
  next: ShopNext,
  filter: ShopFilter,
  what: string,
): { text: string; crawl: boolean } | null {
  const mine =
    state.refilling && state.refilling.store === filter.store && state.refilling.category === filter.category;
  if (next.refilling || mine || state.job === "mas") return { text: t.compras.ocupado.trayendo(what), crawl: false };
  const crawl = state.crawl;
  if (!crawl || !crawl.store_name) return null;
  const section = Math.min(crawl.sections_total, crawl.sections_done + 1) || 1;
  const total = Math.max(crawl.sections_total, 1);
  const filtered = filter.category !== null || filter.store !== null;
  // Solo se promete «traeré más …» si la tienda que se consulta trae eso: ni chaquetas de una tienda de
  // zapatillas, ni cosas de Zara mientras se consulta Courir.
  const crawling = state.stores.find((s) => s.key === crawl.store);
  const brings =
    (filter.store === null || filter.store === crawl.store) &&
    (filter.category === null || (crawling?.kinds ?? []).includes(filter.category));
  return {
    text:
      filtered && brings
        ? t.compras.ocupado.consultando(crawl.store_name, section, total, what)
        : t.compras.ocupado.consultandoSinFiltro(crawl.store_name, section, total),
    crawl: true,
  };
}

/** «el lunes, Pull&Bear»: cuándo es la próxima consulta automática de las tiendas activadas, y de cuál. */
function nextConsult(stores: ShopStore[]): string | null {
  const soonest = stores
    .filter((s) => s.next_check_at)
    .sort((a, b) => (a.next_check_at ?? "").localeCompare(b.next_check_at ?? ""))[0];
  if (!soonest?.next_check_at) return null;
  const day = dayLabel(soonest.next_check_at.slice(0, 10));
  return `${day}, ${soonest.name}`;
}

/**
 * La barra de avance de la consulta, de verdad: el porcentaje (que nunca retrocede) y debajo por dónde
 * va y cuánto queda. Si aún no se puede saber el total, una barra que se mueve de lado a lado.
 */
function CrawlProgress({ crawl }: { crawl: ShopCrawl }) {
  // Por si acaso, tampoco retrocede aquí: el total se va ajustando y la barra espera a alcanzarlo.
  const best = useRef<{ key: string; value: number }>({ key: "", value: 0 });
  const key = `${crawl.started_at}-${crawl.store}`;
  if (best.current.key !== key) best.current = { key, value: 0 };
  best.current.value = Math.max(best.current.value, crawl.percent);
  const percent = Math.round(best.current.value);
  const p = t.compras.progreso;
  const parts = [
    crawl.stores_total > 1
      ? `${crawl.store_name} (${p.tienda(crawl.store_index, crawl.stores_total)})`
      : crawl.store_name,
    crawl.phase === "catalogo" ? crawl.section : p.fase[crawl.phase],
    crawl.phase === "catalogo" && crawl.section && crawl.section_page > 0
      ? p.pagina(crawl.section_page, crawl.section_pages)
      : null,
    crawl.cancelling ? p.cancelando : crawl.eta_seconds !== null ? p.quedan(crawl.eta_seconds) : p.calculando,
  ].filter(Boolean);
  return (
    <div className="flex w-full flex-col gap-1.5">
      <div
        role="progressbar"
        aria-label={p.aria(crawl.store_name ?? "")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={crawl.known ? percent : undefined}
        aria-valuetext={parts.join(" · ")}
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-control"
      >
        {crawl.known ? (
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
            style={{ width: `${Math.max(2, percent)}%` }}
          />
        ) : (
          <div className="absolute inset-y-0 left-0 w-1/3 animate-indeterminate rounded-full bg-primary" />
        )}
      </div>
      <div className="flex items-baseline justify-between gap-2 text-left text-[11px] text-text-2">
        <span className="min-w-0 truncate">{parts.join(" · ")}</span>
        {crawl.known && <span className="shrink-0 font-semibold tabular-nums text-text">{percent} %</span>}
      </div>
      <span className="text-left text-[11px] text-text-3">
        {p.productos(crawl.products)} · {p.paginas(crawl.pages)}
      </span>
    </div>
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
    // Compacta: con las dos filas de filtros encima tiene que caber sin scroll en un móvil de 700 px.
    <div className="card flex flex-col items-center gap-3 px-6 py-5 text-center">
      <span
        className={`flex h-12 w-12 items-center justify-center rounded-full bg-card-2 ${
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
      href={externalHref(item.url)}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-h-11 items-center gap-1.5 text-xs font-semibold text-primary underline-offset-2 active:opacity-60"
    >
      {t.compras.verEn(item.store_name)}
      <Icon name="open_in_new" size={16} />
    </a>
  );
}

/**
 * La talla cuando la tienda no dice cuáles quedan (H&M, COS, Uniqlo, Mango, Nike): «Sin talla» o escrita a
 * mano. `value`: "" = sin talla; cualquier otro texto, la escrita.
 */
function FreeSize({ value, onChange }: { value: string; onChange: (size: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        aria-pressed={value === ""}
        onClick={() => onChange("")}
        className={`min-h-11 min-w-11 rounded-xl border px-3 text-sm font-medium ${
          value === "" ? "border-primary bg-primary text-on-primary" : "border-line bg-card-2 text-text-2"
        }`}
      >
        {t.compras.buscador.sinTalla}
      </button>
      <input
        type="text"
        value={value}
        maxLength={20}
        onChange={(e) => onChange(e.target.value.trimStart())}
        placeholder={t.compras.tallaEscrita}
        aria-label={t.compras.tallaEscrita}
        className={`${inputClass} h-11 min-w-0 flex-1`}
      />
    </div>
  );
}

/** Los items de los que ya se han pedido los colores en esta sesión: a la tienda no se le insiste. */
const colorsAsked = new Set<number>();

/**
 * Los colores de una prenda de tienda. Cada color es un item aparte: elegir uno devuelve ese item
 * (`onItem`), que el servidor trae de la tienda si aún no lo tenía (unos segundos; `pending` dice cuál
 * se está trayendo). `known` permite dar al momento los que ya están cargados (el buscador los trae todos).
 * De paso, si el item se guardó antes de que se apuntaran sus colores (`colors: null`), los pide una vez.
 */
function useColors(
  item: ShopItem | null,
  onItem: (found: ShopLookupItem, from: ShopItem) => void,
  known?: (productRef: string) => ShopLookupItem | undefined,
) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = useRef(item);
  current.current = item;
  const deliver = useRef(onItem);
  deliver.current = onItem;

  const id = item?.id ?? null;
  const unknown = item !== null && item.colors === null;
  useEffect(() => {
    if (id === null || !unknown || colorsAsked.has(id)) return;
    colorsAsked.add(id);
    api
      .shopColors(id)
      .then((filled) => {
        const now = current.current;
        if (now && now.id === filled.id && filled.colors) deliver.current(filled, now);
      })
      .catch(() => undefined); // sin colores no pasa nada: la prenda se ve igual
  }, [id, unknown]);
  useEffect(() => setError(null), [id]);

  const pick = (productRef: string) => {
    const from = current.current;
    if (!from || pending) return;
    setError(null);
    const have = known?.(productRef);
    if (have) {
      deliver.current(have, from);
      return;
    }
    setPending(productRef);
    api
      .shopColor(from.id, productRef)
      .then((found) => {
        // Si mientras tanto se ha pasado a otra prenda, este color ya no viene a cuento.
        if (current.current?.id === from.id) deliver.current(found, from);
      })
      .catch((e) => {
        setError(e instanceof ApiError && [404, 503].includes(e.status) && e.message ? e.message : t.compras.colores.error);
        // Ese color ya no existe: el servidor lo ha quitado de la familia, y su circulito se va con él.
        if (e instanceof ApiError && e.status === 404)
          api
            .shopColors(from.id)
            .then((fresh) => {
              if (current.current?.id === from.id) deliver.current(fresh, from);
            })
            .catch(() => undefined);
      })
      .finally(() => setPending(null));
  };
  return { pending, error, pick };
}

/**
 * Los colores en los que existe la prenda, como circulitos del color. Tocar uno enseña la prenda en
 * ese color. Mientras llega, el circulito elegido late y lo demás se queda como está: sin parpadeo.
 */
function ColorDots({
  colors,
  pending,
  disabled = false,
  onPick,
  className = "",
}: {
  colors: ShopColor[] | null;
  pending: string | null;
  disabled?: boolean;
  onPick: (productRef: string) => void;
  className?: string;
}) {
  const row = useRef<HTMLDivElement>(null);
  const mouse = useRef<{ id: number; x: number; left: number; moved: boolean } | null>(null);
  const [more, setMore] = useState(false); // quedan colores a la derecha: se insinúan con un degradado
  // Tocar un color apagado (aún sin descargar): un aviso pequeño, con su enlace, que se va solo.
  const [hint, setHint] = useState<string | null>(null);
  const hintTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(hintTimer.current), []);
  const showHint = (url: string) => {
    window.clearTimeout(hintTimer.current);
    setHint(url);
    hintTimer.current = window.setTimeout(() => setHint(null), 4000);
  };
  const chosenRef = pending ?? colors?.find((c) => c.current)?.product_ref ?? null;

  const measure = () => {
    const el = row.current;
    if (el) setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  };
  useLayoutEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [colors]);

  // Con ratón: la rueda (vertical u horizontal) desliza la fila. Va con `passive: false` para que la
  // página no se mueva a la vez; si la fila cabe entera, la rueda es de la página.
  useEffect(() => {
    const el = row.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth) return;
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (!delta) return;
      e.preventDefault();
      el.scrollLeft += delta;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [colors]);

  // El color elegido (o el que se está trayendo), siempre a la vista. Sin `scrollIntoView`: ese mueve
  // también la página, y aquí solo se quiere mover la fila.
  useEffect(() => {
    const el = row.current;
    const dot = el?.querySelector<HTMLElement>(`[data-ref="${CSS.escape(chosenRef ?? "")}"]`);
    if (!el || !dot) return;
    const start = dot.offsetLeft - el.offsetLeft;
    const end = start + dot.offsetWidth;
    if (start < el.scrollLeft) el.scrollTo({ left: start - 8, behavior: "smooth" });
    else if (end > el.scrollLeft + el.clientWidth) el.scrollTo({ left: end - el.clientWidth + 8, behavior: "smooth" });
  }, [chosenRef]);

  if (!colors || colors.length < 2) return null;
  return (
    <div className={`relative flex max-w-full min-w-0 ${className}`}>
      {hint && (
        // Encima de la fila y fuera del flujo: no suma alto (Descubrir cabe en una pantalla).
        <p
          role="status"
          className="pointer-events-auto absolute bottom-full left-1/2 z-10 mb-1.5 w-max max-w-[16rem] -translate-x-1/2 rounded-xl border border-line bg-card px-3 py-1.5 text-center text-[11px] leading-snug text-text-2 shadow-[0_2px_8px_rgb(0_0_0/0.12)]"
        >
          {t.compras.colores.aunNo}{" "}
          <a href={externalHref(hint)} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary underline">
            {t.compras.colores.verlo}
          </a>
        </p>
      )}
      <div className="relative flex max-w-full min-w-0 overflow-hidden rounded-[inherit]">
      <div
        ref={row}
        role="group"
        aria-label={t.compras.colores.titulo}
        // Un gesto que empieza en la fila es de la fila: ni arrastra la tarjeta ni cuenta como toque en la
        // foto. Con el dedo desliza el navegador (`pan-x`); con el ratón, arrastrando o con la rueda.
        onPointerDown={(e) => {
          e.stopPropagation();
          if (e.pointerType === "mouse" && e.button === 0)
            mouse.current = { id: e.pointerId, x: e.clientX, left: e.currentTarget.scrollLeft, moved: false };
        }}
        onPointerMove={(e) => {
          e.stopPropagation();
          const m = mouse.current;
          if (!m || m.id !== e.pointerId) return;
          const dx = e.clientX - m.x;
          if (!m.moved && Math.abs(dx) < 4) return;
          if (!m.moved) e.currentTarget.setPointerCapture(e.pointerId);
          m.moved = true;
          e.currentTarget.scrollLeft = m.left - dx;
        }}
        onPointerUp={(e) => {
          e.stopPropagation();
          if (mouse.current?.id === e.pointerId && !mouse.current.moved) mouse.current = null;
        }}
        onPointerCancel={() => (mouse.current = null)}
        onClickCapture={(e) => {
          // Soltar un arrastre con el ratón no elige el color que quedó debajo.
          if (mouse.current?.moved) {
            e.preventDefault();
            e.stopPropagation();
          }
          mouse.current = null;
        }}
        onClick={(e) => e.stopPropagation()}
        onScroll={measure}
        className="flex min-w-0 items-center overflow-x-auto overscroll-x-contain"
        style={{ touchAction: "pan-x", scrollbarWidth: "none" }}
      >
        {colors.map((c) => {
          const chosen = pending ? pending === c.product_ref : c.current;
          // Apagado: aún sin descargar (JD Sports). Se ve gris y con el aro a trazos; tocarlo solo avisa.
          const off = c.available === false;
          return (
            <button
              key={c.product_ref}
              data-ref={c.product_ref}
              type="button"
              aria-label={off ? t.compras.colores.noDisponible(c.name) : t.compras.colores.color(c.name)}
              title={off ? t.compras.colores.noDisponible(c.name) : c.name}
              aria-pressed={chosen}
              aria-disabled={off || undefined}
              aria-busy={pending === c.product_ref || undefined}
              disabled={!off && (disabled || pending !== null)}
              onClick={() => (off ? showHint(c.url) : !c.current && onPick(c.product_ref))}
              className="flex h-10 w-9 shrink-0 items-center justify-center rounded-full"
            >
              <span
                className={`h-6 w-6 rounded-full border transition-shadow duration-200 ${
                  off
                    ? "border-dashed border-text/50 opacity-35 grayscale"
                    : // Los muy claros (blanco, crudo) se pierden en la pastilla: borde más marcado.
                      isLightHex(c.hex)
                      ? "border-text/45"
                      : "border-text/20"
                } ${chosen ? "ring-2 ring-primary ring-offset-2 ring-offset-card" : ""} ${
                  pending === c.product_ref ? "animate-pulse" : ""
                }`}
                style={{ backgroundColor: c.hex }}
              />
            </button>
          );
        })}
      </div>
      {more && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 w-7 rounded-r-full bg-linear-to-l from-card to-transparent"
        />
      )}
      </div>
    </div>
  );
}

/** ¿Es un tono muy claro («#f5f0e6»)? Para darle al circulito un borde que se vea. */
function isLightHex(hex: string): boolean {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? "");
  if (!m) return false;
  const [r, g, b] = m.slice(1).map((x) => parseInt(x, 16));
  return 0.299 * r + 0.587 * g + 0.114 * b > 215;
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
 * Fotos ya cargadas en memoria (dirección -> color de su esquina, o null si no se pudo leer). La pila
 * de Descubrir precarga la primera foto de la actual y de las dos siguientes, y la segunda de la
 * actual: así la tarjeta que entra sale ya con su foto y su fondo.
 */
const photoCache = new Map<string, string | null>();
const photoLoading = new Set<string>();

function preloadPhoto(url: string) {
  if (photoCache.has(url) || photoLoading.has(url)) return;
  photoLoading.add(url);
  const img = new Image();
  img.decoding = "async";
  img.onload = () => {
    photoLoading.delete(url);
    photoCache.set(url, cornerColor(img));
  };
  img.onerror = () => photoLoading.delete(url);
  img.src = url;
}

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
  pending,
  onColor,
  fly,
  enterFrom,
  onDecide,
  onOpen,
  still = false,
  onShift,
}: {
  item: ShopItem;
  busy: boolean;
  pending: string | null; // el color que se está trayendo, si se ha elegido otro
  onColor: (productRef: string) => void;
  fly: -1 | 0 | 1; // un botón manda que salga volando hacia ese lado
  enterFrom: -1 | 0 | 1; // tras «Volver», el lado por el que se fue y por el que vuelve
  onDecide: (liked: boolean) => void;
  onOpen: () => void; // tocar el nombre: los datos de la prenda y con qué combina
  /** La tarjeta de debajo de la pila: solo se pinta (ni se toca ni se lee). */
  still?: boolean;
  /** Cuánto se ha movido (px): la de debajo crece según se aparta la de arriba. */
  onShift?: (shift: number) => void;
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
  // Si la primera foto ya está precargada (la pila lo hace), sale ya con su fondo y sin fundido. Si no,
  // se empieza con el fondo de la foto anterior (los de una tienda se parecen) y la foto entra con un
  // fundido cuando ya está cargada y se sabe su color: así no hay salto de bandas ni parpadeo.
  const first = item.photos[0];
  const ready = first ? photoCache.has(mediaUrl(first.url)) : false;
  const [backdrop, setBackdrop] = useState<string | null>(
    (first && photoCache.get(mediaUrl(first.url))) || lastBackdrop,
  );
  const [loaded, setLoaded] = useState<string | null>(ready && first ? first.url : null);
  // La foto que se ve, apuntada con su item: al cambiar de color se empieza otra vez por la primera.
  const [at, setAt] = useState({ id: item.id, index: 0 });
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

  const shift = still ? 0 : leaving ? leaving * 520 : entering ? entering * 520 : dx;
  const strength = Math.min(1, Math.abs(shift) / 90);
  const photos = item.photos;
  const photo = at.id === item.id && at.index < photos.length ? at.index : 0;
  const shiftRef = useRef(onShift);
  shiftRef.current = onShift;
  useEffect(() => {
    shiftRef.current?.(shift);
  }, [shift]);
  // La segunda foto de la que se ve, también precargada: tocar «siguiente foto» es inmediato.
  useEffect(() => {
    if (!still && photos[1]) preloadPhoto(mediaUrl(photos[1].url));
  }, [still, photos]);

  return (
    <div
      aria-hidden={still || undefined}
      // @ts-expect-error: `inert` aún no está en los tipos de React 18; el navegador lo entiende.
      inert={still ? "" : undefined}
      onPointerDown={still ? undefined : onPointerDown}
      onPointerMove={still ? undefined : onPointerMove}
      onPointerUp={still ? undefined : onPointerEnd}
      onPointerCancel={still ? undefined : onPointerEnd}
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
        zIndex: still ? undefined : 1,
      }}
    >
      <div className="relative min-h-0 w-full flex-1">
        <button
          type="button"
          aria-label={photos.length > 1 ? t.compras.fotoN(photo + 1, photos.length) : undefined}
          disabled={photos.length < 2}
          onClick={(e) =>
            setAt({
              id: item.id,
              index: photoAfterTap(e.clientX, e.currentTarget.getBoundingClientRect(), photo, photos.length),
            })
          }
          className="absolute inset-0 block h-full w-full overflow-hidden bg-card-2 transition-colors duration-300"
          style={backdrop ? { backgroundColor: backdrop } : undefined}
        >
          {photos[photo] && (
            <img
              src={mediaUrl(photos[photo].url)}
              alt={item.name}
              draggable={false}
              onLoad={(e) => {
                const color = cornerColor(e.currentTarget);
                photoCache.set(mediaUrl(photos[photo].url), color);
                if (color) {
                  lastBackdrop = color;
                  setBackdrop(color);
                }
                setLoaded(photos[photo].url);
              }}
              // Mientras llega otro color, la foto se queda, algo apagada; la nueva entra con el fundido de siempre.
              className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-300 ${
                loaded === photos[photo].url ? (pending ? "opacity-60" : "opacity-100") : "opacity-0"
              }`}
            />
          )}
          {photos.length > 1 && (
            <span className="absolute inset-x-0 top-3 flex justify-center gap-1.5">
              {photos.map((p, i) => (
                <span key={p.id} className={`h-1.5 rounded-full transition-all duration-300 ease-out ${isDark(backdrop) ? "bg-white" : "bg-black"} ${
                    i === photo ? "w-4 opacity-70" : "w-1.5 opacity-30"
                  }`} />
              ))}
            </span>
          )}
        </button>
        {/* Los colores van sobre la foto, abajo: así no piden sitio y todo sigue cabiendo en una pantalla. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center px-3">
          <ColorDots
            colors={still ? null : item.colors}
            pending={pending}
            disabled={busy && !pending}
            onPick={onColor}
            className="pointer-events-auto rounded-full border border-line bg-card/85 px-0.5 shadow-[0_2px_8px_rgb(0_0_0/0.12)] backdrop-blur-md"
          />
        </div>
      </div>

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
            {[item.store_name, item.brand, cap(item.type), item.store_color].filter(Boolean).join(" · ")}
          </span>
          <Price item={item} />
        </div>
        <button
          type="button"
          onClick={onOpen}
          aria-label={t.compras.verDatos(item.name)}
          className="-my-1 flex min-w-0 items-center gap-1 py-1 text-left active:opacity-60"
        >
          <h3 className="truncate font-display text-base leading-snug font-semibold tracking-tight">{item.name}</h3>
          <Icon name="chevron_right" size={16} className="shrink-0 text-text-3" />
        </button>
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

type Priced = Pick<ShopItem, "price_cents" | "old_price_cents">;

/** La rebaja de un producto, si la tienda dice que lo está: el precio de antes y el porcentaje. */
function saleOf(item: Priced): { old: number; off: number } | null {
  const old = item.old_price_cents;
  if (!old || old <= item.price_cents) return null;
  return { old, off: Math.round((1 - item.price_cents / old) * 100) };
}

/**
 * El precio de un producto de tienda, el mismo en Descubrir, Me gustan, el buscador y el visor. Si la tienda
 * dice que está rebajado: el descuento en una etiqueta discreta, el precio de antes tachado (gris y pequeño) y
 * el de ahora en rojo. Siempre en una línea. `size`: el tamaño del precio de ahora.
 */
function Price({ item, size = "text-lg", className = "" }: { item: Priced; size?: string; className?: string }) {
  const sale = saleOf(item);
  const now = t.compras.precio(item.price_cents);
  if (!sale) return <span className={`shrink-0 font-display font-semibold ${size} ${className}`}>{now}</span>;
  return (
    <span className={`inline-flex shrink-0 items-baseline gap-1.5 whitespace-nowrap ${className}`}>
      <span className="sr-only">{t.compras.oferta.aria(t.compras.precio(sale.old), now, sale.off)}</span>
      {sale.off > 0 && (
        <span
          aria-hidden="true"
          className="self-center rounded-full bg-danger/10 px-1.5 py-0.5 text-[10px] leading-none font-semibold text-danger"
        >
          {t.compras.oferta.descuento(sale.off)}
        </span>
      )}
      <s aria-hidden="true" className="text-xs text-text-3">
        {t.compras.precio(sale.old)}
      </s>
      <span aria-hidden="true" className={`font-display font-semibold text-danger ${size}`}>
        {now}
      </span>
    </span>
  );
}

/** El precio en texto, para copiarlo: «19,95 € (antes 29,95 €, −33 %)» si está rebajado. */
function priceText(item: Priced): string {
  const sale = saleOf(item);
  const now = t.compras.precio(item.price_cents);
  return sale ? t.compras.oferta.texto(now, t.compras.precio(sale.old), sale.off) : now;
}

/** Las tallas en texto, para copiarlas: «S, M, L (agotadas: XL)». */
function sizesText(item: ShopItem): string {
  const left = item.sizes.filter((s) => s.in_stock).map((s) => s.name);
  const gone = item.sizes.filter((s) => !s.in_stock).map((s) => s.name);
  if (gone.length === 0) return left.join(", ");
  const out = t.compras.visor.agotadas(gone.join(", "));
  return left.length > 0 ? `${left.join(", ")} (${out})` : out;
}

/**
 * Una prenda de tienda en grande. Arriba, la foto (tocarla pasa a la siguiente). Deslizando hacia
 * arriba, en el mismo cuadro, su ficha: los datos de la tienda, cada uno con su botón de copiar, y
 * las prendas del armario con las que combina. Si existe en más colores, aquí se elige cuál se ve.
 */
function PhotoViewer({
  item: opened,
  onClose,
  onChange,
  onSaved,
  known,
}: {
  item: ShopItem;
  onClose: () => void;
  /** Lo que se ve ha cambiado: otro color, o el mismo ya guardado. */
  onChange?: (item: ShopLookupItem) => void;
  /** Se ha guardado en Me gustan desde aquí. */
  onSaved?: () => void;
  /** Los colores que ya están cargados (los trae el buscador), para enseñarlos al momento. */
  known?: (productRef: string) => ShopLookupItem | undefined;
}) {
  const navigate = useNavigate();
  const [item, setItem] = useState<ShopItem>(opened);
  // La foto que se ve, apuntada con su item: al cambiar de color se empieza otra vez por la primera.
  const [at, setAt] = useState({ id: opened.id, index: 0 });
  const [backdrop, setBackdrop] = useState<string | null>(lastBackdrop);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false); // ya se ha deslizado hasta la ficha: la pista sobra
  const [matches, setMatches] = useState<ShopMatches | "error" | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const press = useRef<{ x: number; y: number } | null>(null);
  const swiped = useRef(false); // para que un deslizamiento sobre la foto no cuente como toque
  const notify = useRef(onChange);
  notify.current = onChange;
  const colors = useColors(
    item,
    (found) => {
      setItem(found);
      notify.current?.(found);
    },
    known,
  );
  const photos = item.photos;
  const photo = at.id === item.id && at.index < photos.length ? at.index : 0;

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

  // Con qué combina: se mira en el armario (no en la tienda), así que se pide nada más abrir.
  useEffect(() => {
    let alive = true;
    setMatches(null);
    api
      .shopMatches(item.id)
      .then((found) => alive && setMatches(found))
      .catch(() => alive && setMatches("error"));
    return () => {
      alive = false;
    };
  }, [item.id]);

  const toData = () => {
    const box = scroller.current;
    box?.scrollTo({ top: box.clientHeight, behavior: "smooth" });
  };

  const save = () => {
    setSaving(true);
    setSaveError(false);
    api
      .shopLike(item.id)
      .then(() => {
        const saved: ShopLookupItem = { ...item, status: "gustado", saved: "gustado", garment_id: null };
        setItem(saved);
        notify.current?.(saved);
        onSaved?.();
      })
      .catch(() => setSaveError(true))
      .finally(() => setSaving(false));
  };

  // Los datos, en el orden en que se enseñan y se copian. Lo que la tienda no da, no sale.
  const sizes = sizesText(item);
  const facts: { key: string; label: string; value: string }[] = [
    { key: "referencia", label: t.compras.visor.referencia, value: item.reference ?? "" },
    { key: "tienda", label: t.compras.visor.tienda, value: item.store_name },
    { key: "marca", label: t.compras.visor.marca, value: item.brand ?? "" },
    { key: "nombre", label: t.compras.visor.nombre, value: item.name },
    // El de la tienda, si el nombre está traducido: sirve para buscarlo en su web.
    { key: "original", label: t.compras.visor.nombreOriginal, value: item.name_original ?? "" },
    { key: "color", label: t.compras.visor.color, value: item.store_color },
    { key: "precio", label: t.compras.visor.precio, value: priceText(item) },
    // Si la tienda no dice qué tallas quedan (H&M, COS, Uniqlo, Mango, Nike), se dice dónde mirarlas.
    { key: "tallas", label: t.compras.visor.tallas, value: sizes || t.compras.visor.tallasEnTienda },
    { key: "composicion", label: t.compras.visor.composicion, value: item.composition ?? "" },
    { key: "enlace", label: t.compras.visor.enlace, value: item.url },
    // La misma zapatilla en otras tiendas: «Snipes 119,99 € · Foot Locker 120,00 €», cada una con su enlace.
    {
      key: "tambien",
      label: t.compras.visor.tambienEn,
      value: (item.also_in ?? []).map((other) => `${other.store_name} ${t.compras.precio(other.price_cents)}`).join(" · "),
    },
  ].filter((fact) => fact.value);
  const canSave = item.status === "buscado" || item.status === "variante";

  // En el body, como los demás paneles: dentro de la pantalla quedaría bajo la cabecera y la barra
  // inferior mientras la pantalla está entrando (su fundido la hace contexto de apilamiento).
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={item.name}
      onClick={onClose}
      className="fixed inset-0 z-50 flex animate-fade items-center justify-center bg-scrim px-4 backdrop-blur-[2px]"
      style={{
        paddingTop: "calc(env(safe-area-inset-top, 0px) + 1rem)",
        paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1rem)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card relative h-full max-h-[46rem] w-full max-w-md animate-pop overflow-hidden"
      >
        {/* Un solo cuadro con dos alturas: la foto y, debajo, la ficha. Se pasa de una a otra deslizando. */}
        <div
          ref={scroller}
          onScroll={(e) => e.currentTarget.scrollTop > 24 && setScrolled(true)}
          // Scroll libre, sin imanes: si se baja un poco, se queda ahí (antes saltaba de vuelta a la foto).
          className="h-full overflow-y-auto overscroll-contain"
        >
          <section className="flex h-full flex-col">
            <div className="relative min-h-0 w-full flex-1">
              <button
                type="button"
                aria-label={photos.length > 1 ? t.compras.fotoN(photo + 1, photos.length) : item.name}
                onPointerDown={(e) => {
                  press.current = { x: e.clientX, y: e.clientY };
                  swiped.current = false;
                }}
                onPointerUp={(e) => {
                  const from = press.current;
                  press.current = null;
                  if (!from) return;
                  const dy = e.clientY - from.y;
                  if (Math.abs(dy) > SWIPE_START || Math.abs(e.clientX - from.x) > SWIPE_START) swiped.current = true;
                  // Con el dedo, deslizar ya mueve el cuadro. Con ratón no: arrastrar hacia arriba lleva a la ficha.
                  if (e.pointerType === "mouse" && dy < -40) toData();
                }}
                onClick={(e) => {
                  if (swiped.current) {
                    swiped.current = false;
                    return;
                  }
                  setAt({
                    id: item.id,
                    index: photoAfterTap(e.clientX, e.currentTarget.getBoundingClientRect(), photo, photos.length),
                  });
                }}
                className="absolute inset-0 block h-full w-full overflow-hidden bg-card-2 transition-colors duration-300"
                style={backdrop ? { backgroundColor: backdrop } : undefined}
              >
                {photos[photo] && (
                  <img
                    src={mediaUrl(photos[photo].url)}
                    alt={item.name}
                    draggable={false}
                    onLoad={(e) => {
                      const color = cornerColor(e.currentTarget);
                      if (color) setBackdrop(color);
                      setLoaded(photos[photo].url);
                    }}
                    className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-300 ${
                      loaded === photos[photo].url ? (colors.pending ? "opacity-60" : "opacity-100") : "opacity-0"
                    }`}
                  />
                )}
                {photos.length > 1 && (
                  <span className="absolute inset-x-0 top-3 flex justify-center gap-1.5">
                    {photos.map((p, i) => (
                      <span
                        key={p.id}
                        className={`h-1.5 rounded-full transition-all duration-300 ease-out ${isDark(backdrop) ? "bg-white" : "bg-black"} ${
                          i === photo ? "w-4 opacity-70" : "w-1.5 opacity-30"
                        }`}
                      />
                    ))}
                  </span>
                )}
              </button>
              {/* La pista de que debajo hay más. Se va en cuanto se desliza (o se toca: también baja). */}
              <button
                type="button"
                tabIndex={scrolled ? -1 : 0}
                aria-hidden={scrolled}
                onClick={toData}
                className={`absolute bottom-2.5 left-1/2 flex h-9 -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-card/85 pr-3.5 pl-2.5 text-[11px] font-medium whitespace-nowrap text-text-2 shadow-[0_2px_8px_rgb(0_0_0/0.12)] backdrop-blur-md transition-opacity duration-300 ${
                  scrolled ? "pointer-events-none opacity-0" : "opacity-100"
                }`}
              >
                <Icon name="expand_less" size={16} />
                {t.compras.visor.pista}
              </button>
            </div>
            <div className="flex shrink-0 flex-col gap-1 px-4 pt-3 pb-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="label-caps min-w-0 truncate text-text-2">
                  {[item.store_name, item.brand, cap(item.type), item.store_color].filter(Boolean).join(" · ")}
                </span>
                <Price item={item} />
              </div>
              <h3 className="font-display text-base leading-snug font-semibold tracking-tight">{item.name}</h3>
              {item.name_original && <p className="-mt-0.5 text-[11px] text-text-3">{item.name_original}</p>}
              <div className="flex items-center justify-between gap-2">
                <div className="shrink-0">
                  <StoreLink item={item} />
                </div>
                <ColorDots colors={item.colors} pending={colors.pending} onPick={colors.pick} className="-mr-1.5" />
              </div>
              {colors.error && (
                <p role="alert" className="text-xs text-danger">
                  {colors.error}
                </p>
              )}
              {/* Un color que no está guardado (se ha elegido aquí, o viene del buscador) se puede guardar. */}
              {canSave && (
                <button
                  type="button"
                  disabled={saving || colors.pending !== null}
                  onClick={save}
                  className="mb-1 flex h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-line bg-control text-xs font-semibold text-text active:scale-[0.98] disabled:opacity-40"
                >
                  <Icon name="favorite" size={18} />
                  {saving ? t.compras.visor.guardando : t.compras.visor.guardar}
                </button>
              )}
              {saveError && (
                <p role="alert" className="text-xs text-danger">
                  {t.compras.errorAccion}
                </p>
              )}
              {item.status === "gustado" && (item.id !== opened.id || opened.status !== "gustado") && (
                <p className="flex items-center gap-1.5 pb-1 text-xs font-medium text-ok">
                  <Icon name="favorite_fill" size={15} />
                  {t.compras.buscador.enMeGustan}
                </p>
              )}
            </div>
          </section>

          <section className="flex flex-col gap-2 px-4 pt-4 pb-5">
            {/* El hueco de la derecha es para la X, que flota sobre el cuadro. */}
            <h4 className="flex min-h-11 items-center pr-12 font-display text-lg font-semibold tracking-tight">
              {t.compras.visor.datos}
            </h4>
            {facts.map((fact) =>
              fact.key === "tallas" && item.sizes.length === 0 ? (
                // Como las demás filas, pero sin copiar: lo que hay es un enlace a la tienda.
                <div key={fact.key} className="flex flex-col gap-0.5 rounded-lg border border-line bg-card-2 py-2 pr-1 pl-3">
                  <span className="label-caps text-text-2">{fact.label}</span>
                  <a
                    href={externalHref(item.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex min-h-9 w-fit items-center gap-1.5 text-sm font-medium text-primary underline underline-offset-2 active:opacity-60"
                  >
                    {fact.value}
                    <Icon name="open_in_new" size={15} />
                  </a>
                </div>
              ) : fact.key === "tallas" ? (
                <CopyRow key={fact.key} label={fact.label} value={fact.value}>
                  <ul className="flex flex-wrap gap-1.5 pt-0.5">
                    {item.sizes.map((s) => (
                      <li
                        key={s.name}
                        aria-label={s.in_stock ? undefined : t.compras.visor.agotada(s.name)}
                        className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                          s.in_stock ? "border-line bg-control text-text" : "border-line text-text-3 line-through"
                        }`}
                      >
                        {s.name}
                      </li>
                    ))}
                  </ul>
                </CopyRow>
              ) : fact.key === "enlace" ? (
                <CopyRow
                  key={fact.key}
                  label={fact.label}
                  value={fact.value}
                >
                  <a
                    href={externalHref(item.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={t.compras.visor.abrir}
                    className="block truncate py-1 text-sm font-medium text-primary underline underline-offset-2 active:opacity-60"
                  >
                    {item.url.replace(/^https?:\/\/(www\.)?/, "")}
                  </a>
                </CopyRow>
              ) : fact.key === "tambien" ? (
                <CopyRow key={fact.key} label={fact.label} value={fact.value}>
                  <span className="flex flex-wrap gap-x-1 text-sm text-text">
                    {(item.also_in ?? []).map((other, index) => (
                      <span key={other.store}>
                        {index > 0 ? "· " : ""}
                        <a
                          href={externalHref(other.url)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t.compras.visor.tambienEnTienda(other.store_name)}
                          className="font-medium text-primary underline underline-offset-2 active:opacity-60"
                        >
                          {other.store_name} {t.compras.precio(other.price_cents)}
                        </a>
                      </span>
                    ))}
                  </span>
                </CopyRow>
              ) : (
                <CopyRow key={fact.key} label={fact.label} value={fact.value} />
              ),
            )}

            <h4 className="mt-3 font-display text-lg font-semibold tracking-tight">{t.compras.combina.titulo}</h4>
            {matches === null ? (
              <p className="text-sm text-text-3">{t.compras.combina.cargando}</p>
            ) : matches === "error" ? (
              <p role="alert" className="text-sm text-danger">
                {t.compras.combina.error}
              </p>
            ) : matches.groups.length === 0 ? (
              <p className="text-sm text-text-2">
                {matches.wardrobe === 0 ? t.compras.combina.armarioVacio : t.compras.combina.nada}
              </p>
            ) : (
              matches.groups.map((group) => (
                <div key={group.category} className="flex flex-col gap-1.5 pb-1">
                  <span className="label-caps text-text-2">
                    {t.compras.filtros.categorias[group.category] ?? group.category}
                  </span>
                  <ul className="grid grid-cols-3 gap-2">
                    {group.garments.map((garment) => (
                      <li key={garment.id} className="min-w-0">
                        <button
                          type="button"
                          aria-label={t.compras.combina.ver(garment.name)}
                          onClick={() => navigate(`/prenda/${garment.id}`)}
                          className="flex w-full flex-col gap-1 text-left active:opacity-70"
                        >
                          <img
                            src={mediaUrl(garment.photo.thumb_url)}
                            alt=""
                            className="aspect-[3/4] w-full rounded-xl bg-card-2 object-cover"
                          />
                          <span className="line-clamp-2 text-xs leading-snug text-text">{garment.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </section>
        </div>
        <button
          type="button"
          aria-label={t.compras.panel.cerrar}
          onClick={onClose}
          className="absolute top-3 right-3 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-card text-text shadow-[0_3px_10px_rgb(0_0_0/0.16)] active:scale-95"
        >
          <Icon name="close" size={20} />
        </button>
      </div>
    </div>,
    document.body,
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
  // Lo guardado desde el buscador sin foto: en cuanto llega, se cambia esa tarjeta (sin recargar la lista).
  usePendingPhotos(items, (fresh) =>
    setItems(
      (list) =>
        list?.map((item) => {
          const now = fresh.find((other) => other.id === item.id);
          return now && now.status === "gustado" ? now : item;
        }) ?? null,
    ),
  );

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
    // Sin tallas que elegir, va marcada «sin talla» (se puede escribir); con una sola, esa.
    setSize(available.length === 0 ? "" : available.length === 1 ? available[0].name : null);
    setBuyError(null);
  };

  // `ordered`: la ha pedido y aún no ha llegado (entra en el armario como «Pedida»).
  const buy = (item: ShopItem, ordered: boolean) => {
    setBuyBusy(true);
    setBuyError(null);
    api
      .shopBought(item.id, size?.trim() || null, ordered)
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
  if (!items) return <ListSkeleton />;
  if (items.length === 0) {
    return <Notice icon="favorite" title={t.compras.gustados.vacioTitulo} text={t.compras.gustados.vacioTexto} />;
  }

  return (
    <>
      {viewing && (
        <PhotoViewer
          item={viewing}
          onClose={() => setViewing(null)}
          // Desde el visor se puede guardar otro color: la lista se pone al día por detrás.
          onSaved={() => {
            load();
            onChanged();
          }}
        />
      )}
      <ul className="flex flex-col gap-3">
        {items.map((item, index) => {
          const available = item.sizes.filter((s) => s.in_stock);
          const open = buying === item.id;
          return (
            <li key={item.id} style={stagger(index)} className="card flex animate-enter flex-col gap-3 p-3.5">
              {/* Tocar la tarjeta (no los botones ni el enlace) abre la foto en grande. */}
              <div
                className={`flex gap-3.5 ${item.photos[0] ? "cursor-pointer" : ""}`}
                onClick={() => item.photos[0] && setViewing(item)}
              >
                {item.photos[0] ? (
                  <button
                    type="button"
                    aria-label={t.compras.gustados.verFoto(item.name)}
                    className="h-32 w-24 shrink-0 animate-fade overflow-hidden rounded-xl bg-card-2 active:opacity-80"
                  >
                    <img src={mediaUrl(item.photos[0].thumb_url)} alt="" className="h-full w-full object-cover" />
                  </button>
                ) : (
                  // Guardado desde el buscador sin foto: el hueco de la foto dice que está de camino.
                  <div className="flex h-32 w-24 shrink-0 flex-col items-center justify-center gap-1.5 rounded-xl bg-card-2 px-2 text-center text-text-3">
                    <Icon name="schedule" size={22} />
                    <span className="text-[11px] leading-tight">{t.compras.gustados.sinFoto}</span>
                  </div>
                )}
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="label-caps text-text-2">
                    {[item.store_name, item.brand, cap(item.type)].filter(Boolean).join(" · ")}
                  </span>
                  <h3 className="text-base leading-snug font-medium">{item.name}</h3>
                  <Price item={item} className="self-start" />
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
              {item.photo_pending && (
                <p className="-mt-1 flex items-start gap-1.5 text-xs text-text-2">
                  <Icon name="schedule" size={15} className="mt-px shrink-0" />
                  {t.compras.gustados.fotoPendiente}
                </p>
              )}

              {open ? (
                <div className="flex animate-enter flex-col gap-3 border-t border-control pt-3">
                  {buyBusy ? (
                    <p className="shimmer-text text-xs text-text-2">{t.compras.gustados.analizandoTexto}</p>
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
                    <>
                      <span className="label-caps text-text-2">{t.compras.gustados.talla}</span>
                      <p className="-mt-1.5 text-xs text-text-2">{t.compras.gustados.sinTallas}</p>
                      <FreeSize value={size ?? ""} onChange={setSize} />
                    </>
                  )}
                  {buyError && (
                    <p role="alert" className="text-sm text-danger">
                      {buyError}
                    </p>
                  )}
                  {!buyBusy && <p className="text-xs text-text-2">{t.compras.gustados.pedidaTexto}</p>}
                  <PrimaryButton
                    disabled={buyBusy || (available.length > 0 && !size)}
                    onClick={() => buy(item, true)}
                  >
                    {!buyBusy && <Icon name="package_box" size={18} />}
                    {buyBusy ? (
                      <span className="shimmer-text">{t.compras.gustados.analizando}</span>
                    ) : (
                      t.compras.gustados.pedida
                    )}
                  </PrimaryButton>
                  {!buyBusy && (
                    <SecondaryButton disabled={available.length > 0 && !size} onClick={() => buy(item, false)}>
                      <Icon name="check_circle" size={18} />
                      {t.compras.gustados.recibida}
                    </SecondaryButton>
                  )}
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
                    // Sin foto no se puede pasar al armario: espera a que llegue.
                    disabled={buyBusy || !!item.photo_pending}
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

// ---------- Buscador por referencia

/** Lo que se le dice a la tienda cuando el buscador falla y el servidor ya ha escrito el porqué. */
const lookupMessage = (e: unknown) =>
  e instanceof ApiError && [404, 409, 503].includes(e.status) && e.message ? e.message : t.compras.buscador.error;

/**
 * Panel «Buscar una prenda»: una referencia de Zara (o el enlace del producto) trae la prenda con las
 * fotos de la tienda, para guardarla en Me gustan o meterla en el armario sin fotografiarla.
 */
function SearchPanel({ onChanged, onClose }: { onChanged: () => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Una tarjeta por producto. Si la búsqueda trae el mismo en varios colores, se enseña uno y los
  // demás quedan a mano (`loaded`) para cambiar de color al momento, sin volver a la tienda.
  const [results, setResults] = useState<ShopLookupItem[] | null>(null);
  const loaded = useRef(new Map<string, ShopLookupItem>());
  const known = useCallback((productRef: string) => loaded.current.get(productRef), []);
  const [viewing, setViewing] = useState<number | null>(null); // qué tarjeta se ve en grande
  const viewingRef = useRef(false);
  viewingRef.current = viewing !== null;
  const input = useRef<HTMLInputElement>(null);
  // Leer el portapapeles solo existe en https (o en localhost): por http a secas, el botón no sale.

  useEffect(() => {
    input.current?.focus();
    // Con la foto en grande abierta, Escape cierra la foto (lo hace ella), no el panel.
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !viewingRef.current && onClose();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const search = (text: string) => {
    const wanted = text.trim();
    if (!wanted || busy) return;
    setBusy(true);
    setError(null);
    setResults(null);
    api
      .shopLookup(wanted)
      .then((found) => {
        const cards: ShopLookupItem[] = [];
        loaded.current = new Map(found.map((item) => [item.product_ref, item]));
        for (const item of found) {
          // Otro color de algo que ya tiene tarjeta: no se enseña aparte, se elige en ella.
          const repeated = cards.some((card) => card.colors?.some((c) => c.product_ref === item.product_ref));
          if (!repeated) cards.push(item);
        }
        setResults(cards);
      })
      .catch((e) => setError(lookupMessage(e)))
      .finally(() => setBusy(false));
  };

  /** Lo que enseña una tarjeta ha cambiado: otro color, o el mismo ya guardado o comprado (`saved`). */
  const update = (card: number, item: ShopLookupItem, saved = true) => {
    loaded.current.set(item.product_ref, item);
    setResults((list) => list?.map((other, i) => (i === card ? item : other)) ?? null);
    if (saved) onChanged();
  };
  // Lo que salió sin foto (se baja en segundo plano): en cuanto llega, se cambia esa tarjeta sola.
  usePendingPhotos(results, (fresh) => {
    for (const item of fresh) loaded.current.set(item.product_ref, item);
    setResults((list) => list?.map((card) => fresh.find((item) => item.id === card.id) ?? card) ?? null);
    if (fresh.some((item) => item.status === "gustado")) onChanged();
  });

  return createPortal(
    <div
      // Arriba y del alto de su contenido: en el móvil el teclado no tapa el campo, y en pantallas
      // grandes no queda una hoja medio vacía pegada abajo.
      className="fixed inset-0 z-50 flex animate-fade items-start justify-center bg-scrim px-4 backdrop-blur-[2px]"
      style={{
        paddingTop: "calc(env(safe-area-inset-top, 0px) + 4.5rem)",
        paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1rem)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.compras.buscador.titulo}
        className="flex max-h-full w-full max-w-md animate-enter flex-col rounded-3xl border border-line bg-bg shadow-[0_10px_30px_rgb(0_0_0/0.18)]"
      >
        <div className="flex items-center justify-between gap-2 py-3 pr-2 pl-5">
          <h2 className="font-display text-lg font-semibold tracking-tight">{t.compras.buscador.titulo}</h2>
          <button
            type="button"
            aria-label={t.compras.panel.cerrar}
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center active:opacity-60"
          >
            <Icon name="close" size={22} />
          </button>
        </div>
        <div
          // El pt-1 es para el aro de foco del campo: sin él, el borde de arriba se recorta al hacer scroll.
          className="-mt-1 flex flex-col gap-4 overflow-y-auto px-5 pt-1 pb-5"
        >
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              search(query);
            }}
          >
            <input
              ref={input}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.compras.buscador.placeholder}
              aria-label={t.compras.buscador.placeholder}
              maxLength={600}
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
              className={`${inputClass} h-12 min-w-0 flex-1`}
            />
            <button
              type="submit"
              aria-label={t.compras.buscador.buscar}
              title={t.compras.buscador.buscar}
              disabled={busy || !query.trim()}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary text-on-primary active:scale-[0.98] disabled:opacity-40"
            >
              <Icon name="search" size={20} />
            </button>
          </form>
          <p className="text-xs text-text-2">{t.compras.buscador.ayuda}</p>

          {busy && (
            // El mismo destello que los demás textos de «en marcha» («Analizando…»), en vez de un parpadeo.
            <p role="status" className="flex items-center justify-center gap-2 py-6 text-sm text-text-2">
              <Icon name="search" size={18} />
              <span className="shimmer-text">{t.compras.buscador.buscando}</span>
            </p>
          )}
          {error && (
            <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger/10 px-3.5 py-3 text-sm text-danger">
              <Icon name="error" size={18} className="mt-0.5" />
              {error}
            </p>
          )}
          {results && (
            <>
              <p className="label-caps text-text-2">{t.compras.buscador.resultados(results.length)}</p>
              <ul className="flex flex-col gap-3">
                {results.map((item, card) => (
                  <SearchResult
                    key={card}
                    item={item}
                    known={known}
                    onUpdate={(updated) => update(card, updated)}
                    onColor={(updated) => update(card, updated, false)}
                    onView={() => setViewing(card)}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      {viewing !== null && results?.[viewing] && (
        <PhotoViewer
          key={viewing}
          item={results[viewing]}
          known={known}
          onClose={() => setViewing(null)}
          onChange={(updated) => update(viewing, updated, false)}
          onSaved={onChanged}
        />
      )}
    </div>,
    document.body,
  );
}

/** Un resultado del buscador: foto, nombre, color, precio y qué hacer con él. */
function SearchResult({
  item,
  known,
  onUpdate,
  onColor,
  onView,
}: {
  item: ShopLookupItem;
  known: (productRef: string) => ShopLookupItem | undefined;
  onUpdate: (item: ShopLookupItem) => void;
  /** Se ha elegido otro color: la tarjeta pasa a enseñar ese. */
  onColor: (item: ShopLookupItem) => void;
  onView: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<"gusta" | "tengo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // «Ya la tengo»: se está eligiendo talla. "" = sin talla.
  const [choosing, setChoosing] = useState(false);
  const [size, setSize] = useState<string | null>(null);
  const colors = useColors(item, onColor, known);
  // Otro color es otra prenda: la talla que se estuviera eligiendo ya no vale.
  useEffect(() => {
    setChoosing(false);
    setSize(null);
    setError(null);
  }, [item.id]);
  // Lo que ya tiene en casa puede estar agotado en la tienda: de un resultado nuevo vale cualquier talla.
  const sizes = item.sizes.filter((s) => s.in_stock || item.status === "buscado").map((s) => s.name);

  const like = () => {
    setBusy("gusta");
    setError(null);
    api
      .shopLike(item.id)
      .then(() => onUpdate({ ...item, status: "gustado", saved: "gustado" }))
      .catch(() => setError(t.compras.errorAccion))
      .finally(() => setBusy(null));
  };

  const have = () => {
    setBusy("tengo");
    setError(null);
    api
      .shopBought(item.id, size?.trim() || null)
      .then((result) => {
        setChoosing(false);
        onUpdate({ ...item, status: "comprado", saved: "comprado", garment_id: result.garment_id });
      })
      .catch((e) => setError(e instanceof ApiError && e.status < 500 ? e.message : t.compras.gustados.errorComprar))
      .finally(() => setBusy(null));
  };

  const chip = (selected: boolean) =>
    `min-h-11 min-w-11 rounded-xl border px-3 text-sm font-medium ${
      selected ? "border-primary bg-primary text-on-primary" : "border-line bg-card-2 text-text-2"
    }`;

  return (
    <li className="card flex flex-col gap-3 p-3.5">
      <div className="flex gap-3.5">
        {item.photos[0] && (
          <button
            type="button"
            aria-label={t.compras.gustados.verFoto(item.name)}
            onClick={onView}
            className="h-28 w-20 shrink-0 overflow-hidden rounded-xl bg-card-2 active:opacity-80"
          >
            <img src={mediaUrl(item.photos[0].thumb_url)} alt="" className="h-full w-full object-cover" />
          </button>
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="label-caps truncate text-text-2">
            {[item.store_name, item.brand, item.store_color].filter(Boolean).join(" · ")}
          </span>
          <h3 className="text-[15px] leading-snug font-medium">{item.name}</h3>
          <Price item={item} size="text-base" className="self-start" />
          <div className="mt-auto w-fit">
            <StoreLink item={item} />
          </div>
        </div>
      </div>

      <ColorDots
        colors={item.colors}
        pending={colors.pending}
        disabled={busy !== null}
        onPick={colors.pick}
        className="-mx-1.5 -my-1.5"
      />

      {(error || colors.error) && (
        <p role="alert" className="text-sm text-danger">
          {error || colors.error}
        </p>
      )}
      {item.photo_pending && (
        <p className="flex items-center gap-1.5 text-xs text-text-2">
          <Icon name="search" size={15} />
          {t.compras.buscador.fotoPendiente}
        </p>
      )}

      {item.saved === "comprado" ? (
        <div className="flex flex-col gap-2 border-t border-control pt-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ok">
            <Icon name="check_circle" size={16} />
            {t.compras.buscador.enArmario}
          </p>
          {item.garment_id !== null && (
            <SecondaryButton onClick={() => navigate(`/prenda/${item.garment_id}`)}>
              {t.compras.buscador.verFicha}
              <Icon name="chevron_right" size={18} />
            </SecondaryButton>
          )}
        </div>
      ) : choosing ? (
        <div className="flex flex-col gap-3 border-t border-control pt-3">
          {busy === "tengo" ? (
            <p role="status" className="shimmer-text text-xs text-text-2">
              {t.compras.gustados.analizandoTexto}
            </p>
          ) : (
            <>
              <span className="label-caps text-text-2">{t.compras.buscador.talla}</span>
              {sizes.length === 0 ? (
                <FreeSize value={size ?? ""} onChange={setSize} />
              ) : (
              <div className="flex flex-wrap gap-1.5">
                {sizes.map((name) => (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={size === name}
                    onClick={() => setSize(name)}
                    className={chip(size === name)}
                  >
                    {name}
                  </button>
                ))}
                <button type="button" aria-pressed={size === ""} onClick={() => setSize("")} className={chip(size === "")}>
                  {t.compras.buscador.sinTalla}
                </button>
              </div>
              )}
            </>
          )}
          <PrimaryButton disabled={busy !== null || size === null} onClick={have}>
            {busy === "tengo" ? (
              <span className="shimmer-text">{t.compras.gustados.analizando}</span>
            ) : (
              t.compras.gustados.confirmar
            )}
          </PrimaryButton>
          {busy === null && (
            <button type="button" onClick={() => setChoosing(false)} className="h-11 text-xs font-medium text-text-2 underline">
              {t.comun.cancelar}
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {item.saved === "gustado" && (
            <p className="flex items-center gap-1.5 text-xs font-medium text-ok">
              <Icon name="favorite_fill" size={15} />
              {t.compras.buscador.enMeGustan}
            </p>
          )}
          <div className={`grid gap-2 ${item.saved === "gustado" || item.photo_pending ? "" : "grid-cols-2"}`}>
            {item.saved !== "gustado" && (
              <button
                type="button"
                disabled={busy !== null}
                onClick={like}
                className="flex h-11 items-center justify-center gap-1.5 rounded-xl border border-line bg-control px-3 text-xs font-semibold text-text active:scale-[0.98] disabled:opacity-40"
              >
                <Icon name="favorite" size={18} />
                {busy === "gusta" ? t.compras.buscador.guardando : t.compras.si}
              </button>
            )}
            {!item.photo_pending && (
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                setError(null);
                // Sin tallas que elegir, va marcada «sin talla»; con una sola, esa.
                setSize(sizes.length === 0 ? "" : sizes.length === 1 ? sizes[0] : null);
                setChoosing(true);
              }}
              className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-3 text-xs font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
            >
              <Icon name="check_circle" size={18} />
              {t.compras.buscador.yaLaTengo}
            </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

// ---------- Tiendas

/**
 * El reparto de la semana: qué tiendas se consultan cada noche. Las activadas, en su color de texto; las
 * desactivadas, apagadas. Debajo, el tope por noche (las que no caben pasan a la noche siguiente).
 */
function WeekPlan({ state }: { state: ShopState }) {
  const names = new Map(state.stores.map((store) => [store.key, store]));
  return (
    <section className="card flex flex-col gap-2 p-4" aria-label={t.compras.panel.semana}>
      <span className="font-display text-base font-semibold">{t.compras.panel.semana}</span>
      <ul className="flex flex-col gap-1 text-xs">
        {state.week.map((keys, day) => (
          <li key={day} className="flex gap-3">
            <span className="w-8 shrink-0 font-semibold text-text-2">{t.compras.diasCortos[day]}</span>
            <span className="min-w-0">
              {keys.length === 0 ? (
                <span className="text-text-3">{t.compras.panel.libre}</span>
              ) : (
                keys.map((key, index) => {
                  const store = names.get(key);
                  return (
                    <span key={key} className={store?.enabled ? "text-text" : "text-text-3"}>
                      {index > 0 ? " · " : ""}
                      {store?.name ?? key}
                      {store?.heavy && (
                        <sup aria-label={t.compras.panel.pesada} title={t.compras.panel.pesada}>
                          •
                        </sup>
                      )}
                    </span>
                  );
                })
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-text-2">
        {t.compras.panel.repartoTexto(
          state.per_night,
          state.heavy_per_night,
          state.stores
            .filter((store) => store.heavy)
            .map((store) => store.name)
            .join(", "),
        )}
      </p>
    </section>
  );
}

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
  // Con diez (y luego veinte) tiendas, cada una es una fila que se despliega al tocarla. Las activadas van
  // primero; el orden se fija al abrir el panel para que una tienda no salte de sitio al activarla.
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) =>
    setExpanded((before) => {
      const next = new Set(before);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const [order] = useState(() =>
    [...state.stores].sort((a, b) => Number(b.enabled) - Number(a.enabled)).map((store) => store.key),
  );
  const ordered = [
    ...order.map((key) => state.stores.find((store) => store.key === key)).filter((store): store is ShopStore => !!store),
    ...state.stores.filter((store) => !order.includes(store.key)),
  ];

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

  const [night, setNight] = useState(state.night_time);
  useEffect(() => setNight(state.night_time), [state.night_time]);
  const saveNight = (value: string) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value) || value === state.night_time) return;
    act(api.shopNight(value), t.compras.panel.nocheError);
  };

  const toggleCategory = (store: ShopStore, slug: string) => {
    const chosen = store.categories.filter((c) => (c.slug === slug ? !c.enabled : c.enabled)).map((c) => c.slug);
    act(api.shopSettings({ store: store.key, categories: chosen }), t.compras.panel.errorGuardar);
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
        aria-label={t.compras.panel.titulo}
        className="flex max-h-full w-full max-w-md animate-sheet flex-col rounded-t-3xl border border-line bg-bg"
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
          // El pt-1 es para el aro de foco del campo: sin él, el borde de arriba se recorta al hacer scroll.
          className="-mt-1 flex flex-col gap-4 overflow-y-auto px-5 pt-1 pb-5"
        >
          <p className="text-sm text-text-2">{t.compras.panel.intro}</p>
          <section className="card flex flex-col gap-2 p-4">
            <label className="flex items-center justify-between gap-3">
              <span className="font-display text-base font-semibold">{t.compras.panel.noche}</span>
              <input
                type="time"
                value={night}
                onChange={(e) => setNight(e.target.value)}
                onBlur={(e) => saveNight(e.target.value)}
                disabled={busy}
                className={`${inputClass} h-11 w-32 text-center`}
              />
            </label>
            <p className="text-xs text-text-2">{t.compras.panel.nocheTexto}</p>
          </section>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <WeekPlan state={state} />
          {ordered.map((store) => {
            const status = store.status;
            const crawl = state.crawl?.store === store.key ? state.crawl : null;
            const hour = store.next_check_at ? store.next_check_at.slice(11, 16).replace(/^0/, "") : null;
            const open = expanded.has(store.key);
            return (
              <section key={store.key} className="card flex flex-col p-1">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`tienda-${store.key}`}
                    onClick={() => toggle(store.key)}
                    className="flex min-h-14 min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 text-left active:opacity-60"
                  >
                    <Icon
                      name="expand_less"
                      size={18}
                      className={`shrink-0 text-text-2 transition-transform ${open ? "" : "rotate-180"}`}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-display text-base font-semibold">{store.name}</span>
                      <span className={`flex items-center gap-1.5 text-xs font-semibold ${STATUS_TEXT[status.state]}`}>
                        <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status.state]}`} />
                        <span className="truncate">
                          {crawl
                            ? t.compras.panel.leyendo
                            : [
                                t.compras.panel.estado[status.state],
                                store.unavailable ? t.compras.panel.noDisponible : null,
                                t.compras.diasCortos[store.weekday] ?? "",
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                        </span>
                      </span>
                    </span>
                  </button>
                  <div className="shrink-0 pr-3">
                    <Switch
                      checked={store.enabled}
                      label={t.compras.panel.activada(store.name)}
                      onChange={() =>
                        !busy &&
                        act(api.shopSettings({ store: store.key, enabled: !store.enabled }), t.compras.panel.errorGuardar)
                      }
                    />
                  </div>
                </div>
                {crawl && !open && (
                  <div className="px-3 pb-3">
                    <CrawlProgress crawl={crawl} />
                  </div>
                )}
                {open && (
                  <div id={`tienda-${store.key}`} className="flex flex-col gap-3.5 px-3 pt-1 pb-3">
                    {crawl && (
                      <div className="flex flex-col gap-2 rounded-xl bg-card-2 p-3">
                        <span className="label-caps text-text-2">{t.compras.panel.leyendo}</span>
                        <CrawlProgress crawl={crawl} />
                        <SecondaryButton
                          onClick={() => !crawl.cancelling && act(api.shopCancel(), t.compras.panel.errorGuardar)}
                        >
                          <Icon name="close" size={18} />
                          {crawl.cancelling ? t.compras.panel.cancelando : t.compras.panel.cancelar}
                        </SecondaryButton>
                      </div>
                    )}

                    <div className="flex flex-col gap-1 text-xs text-text-2">
                      {status.at && (
                        <>
                          <p>{t.compras.panel.ultima(dateTime(status.at))}</p>
                          <p>
                            {t.compras.panel.trajo(status.found, status.added)}
                            {status.pages > 0 ? ` · ${t.compras.panel.recorrido(status.pages, status.seconds)}` : ""}
                          </p>
                          {status.cancelled && <p>{t.compras.panel.cancelada}</p>}
                          {status.resume && !crawl && (
                            <p className="text-text">{t.compras.panel.incompleta(status.sections, status.sections_total)}</p>
                          )}
                          <p className={status.failed > 0 ? "text-danger" : ""}>
                            {status.failed > 0 ? t.compras.panel.fallaron(status.failed) : t.compras.panel.sinFallos}
                          </p>
                        </>
                      )}
                      {store.unavailable && <p className="font-semibold text-danger">{store.unavailable}</p>}
                      {status.error && (
                        <p className="rounded-lg bg-card-2 px-3 py-2 font-mono text-[11px] break-words text-text">
                          <span className="font-sans font-semibold">{t.compras.panel.error}: </span>
                          {status.error}
                        </p>
                      )}
                      <p>
                        {store.weekday_after_release
                          ? t.compras.panel.dia(t.compras.dias[store.weekday] ?? "")
                          : t.compras.panel.diaSinDato(t.compras.dias[store.weekday] ?? "")}
                      </p>
                      {store.browser && <p className="text-text-3">{t.compras.panel.conNavegador}</p>}
                      <p>
                        {store.enabled && store.next_check
                          ? t.compras.panel.proxima(
                              [dayLabel(store.next_check), hour ? t.compras.panel.a(hour) : ""].filter(Boolean).join(" "),
                            )
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
                      disabled={busy || state.running || !store.enabled || store.unavailable !== null}
                      onClick={() => act(api.shopRefresh(store.key), t.compras.panel.errorConsultar)}
                    >
                      <Icon name="refresh" size={20} />
                      {state.running ? t.compras.panel.consultando : t.compras.panel.consultar}
                    </PrimaryButton>
                    <p className="-mt-1.5 text-center text-[11px] text-text-3">{t.compras.panel.consultarAviso}</p>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
