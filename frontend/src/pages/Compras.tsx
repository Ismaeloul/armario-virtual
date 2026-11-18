import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PrimaryButton, Segmented, Switch } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, ApiError, mediaUrl, type ShopItem, type ShopNext, type ShopState, type ShopStore } from "../lib/api";

type View = "descubrir" | "gustados";

const POLL_MS = 4000; // cada cuánto se pregunta cómo va la consulta en marcha

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

  const load = useCallback(() => {
    setFailed(false);
    Promise.all([api.shopState(), api.shopNext()])
      .then(([s, n]) => {
        setState(s);
        setNext(n);
      })
      .catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);
  const closeStores = useCallback(() => setStoresOpen(false), []);

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
          if (!s.running || s.pending > 0) api.shopNext().then(setNext).catch(() => undefined);
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
  onState,
  onNext,
  onOpenStores,
}: {
  state: ShopState;
  next: ShopNext;
  onState: (s: ShopState) => void;
  onNext: (n: ShopNext) => void;
  onOpenStores: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Si guardar la decisión falla, la tarjeta que ya se fue volando tiene que volver.
  const [attempt, setAttempt] = useState(0);

  const enabled = state.stores.filter((s) => s.enabled);
  const item = next.item;

  const decide = (liked: boolean) => {
    if (!item || busy) return;
    setBusy(true);
    setError(null);
    (liked ? api.shopLike(item.id) : api.shopDislike(item.id))
      .then(onNext)
      .catch(() => {
        setError(t.compras.errorAccion);
        setAttempt((n) => n + 1);
      })
      .finally(() => setBusy(false));
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

  if (item) {
    return (
      <>
        <header className="flex flex-col gap-1">
          <span className="label-caps text-text-2">{t.compras.etiqueta}</span>
          <p className="text-xs text-text-3">
            {state.running ? t.compras.buscando.aviso : t.compras.quedan(next.remaining)}
          </p>
        </header>
        <SwipeCard key={`${item.id}-${attempt}`} item={item} busy={busy} onDecide={decide} />
        {alert}
        <section className="grid grid-cols-2 gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => decide(false)}
            className="flex h-14 items-center justify-center gap-2 rounded-xl border border-line bg-control font-display text-[15px] font-semibold active:scale-[0.98] disabled:opacity-40"
          >
            <Icon name="close" size={22} className="text-text-2" />
            {t.compras.no}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide(true)}
            className="flex h-14 items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
          >
            <Icon name="favorite_fill" size={22} />
            {t.compras.si}
          </button>
        </section>
        <p className="text-center text-[11px] text-text-3">{t.compras.desliza}</p>
      </>
    );
  }

  if (state.running) {
    return (
      <Notice icon="search" title={t.compras.buscando.titulo} text={t.compras.buscando.texto} pulse>
        <div className="h-1 w-full overflow-hidden rounded-full bg-control">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
        </div>
      </Notice>
    );
  }

  // Sin propuestas: o la última consulta falló, o ya se ha visto todo lo de esta semana.
  const broken = enabled.find((s) => s.status.state === "failed");
  if (broken) {
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

  const store = enabled[0];
  const last = enabled.map((s) => s.status.at).filter((at): at is string => !!at).sort().pop();
  const upcoming = enabled.map((s) => s.next_check).filter((d): d is string => !!d).sort()[0];
  return (
    <>
      <Notice
        icon="check_circle"
        title={t.compras.vacio.titulo}
        text={[
          last ? t.compras.vacio.ultima(dateTime(last)) : t.compras.vacio.nunca,
          upcoming ? t.compras.vacio.proxima(dayLabel(upcoming)) : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <PrimaryButton disabled={busy} onClick={() => search(store)}>
          <Icon name="search" size={20} />
          {t.compras.vacio.buscar}
        </PrimaryButton>
      </Notice>
      {alert}
    </>
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

const SWIPE_START = 10; // px que hay que mover para que cuente como arrastre y no como toque
const FLY_MS = 220;

/**
 * Una propuesta, tipo Tinder: deslizar a la derecha = me gusta, a la izquierda = no me gusta.
 * `touch-action: pan-y` deja el scroll vertical al navegador; el arrastre horizontal es nuestro.
 */
function SwipeCard({ item, busy, onDecide }: { item: ShopItem; busy: boolean; onDecide: (liked: boolean) => void }) {
  const drag = useRef<{ id: number; x: number; y: number; active: boolean } | null>(null);
  const moved = useRef(false); // para que soltar un arrastre no cuente como toque en la foto o el enlace
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState<-1 | 0 | 1>(0);
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

  const shift = leaving ? leaving * 520 : dx;
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
      className={`card relative flex flex-col overflow-hidden select-none ${busy && !leaving ? "opacity-50" : ""}`}
      style={{
        touchAction: "pan-y",
        transform: `translateX(${shift}px) rotate(${shift / 22}deg)`,
        transition: dragging ? "none" : `transform ${FLY_MS}ms ease-out, opacity ${FLY_MS}ms ease-out`,
        opacity: leaving ? 0 : undefined,
      }}
    >
      <button
        type="button"
        aria-label={photos.length > 1 ? t.compras.fotoN(photo + 1, photos.length) : undefined}
        disabled={photos.length < 2}
        onClick={() => setPhoto((n) => (n + 1) % photos.length)}
        className="relative block aspect-[4/5] w-full bg-card-2"
      >
        {photos[photo] && (
          <img
            src={mediaUrl(photos[photo].url)}
            alt={item.name}
            draggable={false}
            className="h-full w-full object-cover"
          />
        )}
        {photos.length > 1 && (
          <span className="absolute inset-x-0 bottom-3 flex justify-center gap-1.5">
            {photos.map((p, i) => (
              <span key={p.id} className={`h-1.5 rounded-full bg-text ${i === photo ? "w-4 opacity-80" : "w-1.5 opacity-30"}`} />
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

      <div className="flex flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="label-caps text-text-2">
              {item.store_name} · {cap(item.type)}
            </span>
            <h3 className="font-display text-lg leading-snug font-semibold tracking-tight">{item.name}</h3>
            {item.store_color && <p className="text-xs text-text-3">{item.store_color}</p>}
          </div>
          <span className="shrink-0 font-display text-xl font-semibold">{t.compras.precio(item.price_cents)}</span>
        </div>
        <Reasons item={item} />
        <StoreLink item={item} />
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
      <ul className="flex flex-col gap-3">
        {items.map((item) => {
          const available = item.sizes.filter((s) => s.in_stock);
          const open = buying === item.id;
          return (
            <li key={item.id} className="card flex flex-col gap-3 p-3.5">
              <div className="flex gap-3.5">
                {item.photos[0] && (
                  <img
                    src={mediaUrl(item.photos[0].thumb_url)}
                    alt=""
                    className="h-32 w-24 shrink-0 rounded-xl bg-card-2 object-cover"
                  />
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
                  <div className="mt-auto">
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
