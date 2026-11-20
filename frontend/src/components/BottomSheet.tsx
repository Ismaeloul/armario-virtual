import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n/es";

const CLOSE_MS = 260; // lo que tarda en bajar al cerrarse
const DISMISS_PX = 110; // a partir de cuánto arrastre hacia abajo se cierra al soltar
const DISMISS_SPEED = 0.6; // px/ms: un tirón rápido cierra aunque sea corto

/**
 * Hoja que sube desde abajo, como las del iPhone: se cierra deslizándola hacia abajo (desde el asa o
 * desde el contenido cuando ya está arriba del todo), tocando fuera o con Escape. Al cerrarse baja y el
 * fondo se desvanece; `onClose` llega cuando ha terminado de bajar.
 *
 * `children` puede ser una función que recibe `close`, para que un botón de dentro (Cancelar, Guardar…)
 * cierre con la misma animación.
 */
export function BottomSheet({
  label,
  onClose,
  locked = false,
  header,
  footer,
  children,
}: {
  label: string;
  onClose: () => void;
  /** Mientras se guarda algo: no se deja cerrar. */
  locked?: boolean;
  header?: ReactNode;
  /** Fijo abajo, fuera del scroll (los botones de guardar). */
  footer?: ReactNode | ((close: () => void) => ReactNode);
  children: ReactNode | ((close: () => void) => ReactNode);
}) {
  const [closing, setClosing] = useState(false);
  // El fondo entra con una transición propia (ver abajo): se pinta primero sin velo y, un instante después,
  // con él.
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const wait = window.setTimeout(() => setShown(true), 16);
    return () => window.clearTimeout(wait);
  }, []);
  const [drag, setDrag] = useState(0); // px que se ha bajado con el dedo
  const [dragging, setDragging] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLDivElement>(null);
  const state = useRef({ locked, closing, onClose });
  state.current = { locked, closing, onClose };

  const close = useCallback(() => {
    if (state.current.locked || state.current.closing) return;
    setClosing(true);
    setDragging(false);
    window.setTimeout(() => state.current.onClose(), CLOSE_MS);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [close]);

  // Arrastrar para cerrar. Con oyentes nativos (no pasivos) para poder frenar el scroll de la página
  // mientras se baja la hoja.
  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    let startY = 0;
    let startAt = 0;
    let active = false; // el gesto puede acabar en arrastre (empezó en el asa o con el contenido arriba)
    let moving = false; // ya se está bajando la hoja
    let last = 0;
    let speed = 0; // px/ms en el último tramo del gesto
    let prevY = 0;
    let prevAt = 0;

    const begin = (y: number, target: EventTarget | null) => {
      const onHandle = !!handle.current && target instanceof Node && handle.current.contains(target);
      active = onHandle || (scroller.current?.scrollTop ?? 0) <= 0;
      moving = false;
      startY = y;
      startAt = performance.now();
      last = 0;
      speed = 0;
      prevY = y;
      prevAt = startAt;
    };
    const move = (y: number, event: Event) => {
      if (!active || state.current.locked || state.current.closing) return;
      const dy = y - startY;
      if (!moving && dy > 6) {
        moving = true;
        setDragging(true);
      }
      if (moving) {
        event.preventDefault();
        last = Math.max(0, dy);
        const now = performance.now();
        if (now - prevAt > 0) speed = speed * 0.4 + ((y - prevY) / (now - prevAt)) * 0.6;
        prevY = y;
        prevAt = now;
        setDrag(last);
      }
    };
    const end = () => {
      if (!moving) return;
      moving = false;
      setDragging(false);
      // Un tirón rápido hacia abajo cierra aunque sea corto; uno lento, solo si ha bajado bastante.
      if (last > DISMISS_PX || (last > 40 && speed > DISMISS_SPEED)) close();
      else setDrag(0); // vuelve a su sitio
    };

    const onTouchStart = (e: TouchEvent) => begin(e.touches[0].clientY, e.target);
    const onTouchMove = (e: TouchEvent) => move(e.touches[0].clientY, e);
    // Con ratón (el ordenador), solo desde el asa: en el contenido, arrastrar es seleccionar texto.
    const onMouseDown = (e: MouseEvent) => {
      if (!handle.current?.contains(e.target as Node)) return;
      begin(e.clientY, e.target);
      const onMouseMove = (ev: MouseEvent) => move(ev.clientY, ev);
      const onMouseUp = () => {
        end();
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
    el.addEventListener("mousedown", onMouseDown);
    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", end);
      el.removeEventListener("touchcancel", end);
      el.removeEventListener("mousedown", onMouseDown);
    };
  }, [close]);

  const ease = "cubic-bezier(0.22, 1, 0.36, 1)";
  const height = panel.current?.offsetHeight ?? 600;
  // Al arrastrar, el fondo se aclara a la vez que baja la hoja.
  const fade = closing || !shown ? 0 : Math.max(0.15, 1 - drag / Math.max(1, height));
  const still = dragging ? "none" : undefined;

  return createPortal(
    <div
      className="fixed inset-0 z-[55] flex items-end justify-center"
      style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 1.5rem)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      {/* El difuminado y el velo van en dos capas hermanas y sin opacidad en nada de lo que las contiene:
          en el iPhone, un `backdrop-filter` dentro de algo que se está desvaneciendo no se pinta hasta que
          acaba el fundido (el difuminado salía de golpe, tarde). Así el difuminado crece con su propia
          transición y el velo se desvanece aparte. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backdropFilter: `blur(${(12 * fade).toFixed(1)}px)`,
          WebkitBackdropFilter: `blur(${(12 * fade).toFixed(1)}px)`,
          transition: still ?? `backdrop-filter ${CLOSE_MS}ms ease-out, -webkit-backdrop-filter ${CLOSE_MS}ms ease-out`,
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-scrim"
        style={{ opacity: fade, transition: still ?? `opacity ${CLOSE_MS}ms ease-out` }}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="relative flex max-h-full w-full max-w-md animate-sheet flex-col rounded-t-3xl border border-line bg-bg shadow-[0_-8px_30px_rgb(0_0_0/0.12)]"
        style={{
          transform: closing ? "translateY(100%)" : drag ? `translateY(${drag}px)` : undefined,
          transition: dragging ? "none" : `transform ${CLOSE_MS}ms ${ease}`,
        }}
      >
        {/* El asa: de aquí se tira hacia abajo para cerrar. */}
        <div ref={handle} className="flex cursor-grab touch-none justify-center pt-2.5 pb-2 active:cursor-grabbing">
          <span className="h-1.5 w-11 rounded-full bg-control" />
        </div>
        {/* Para el lector de pantalla y el teclado, que no pueden arrastrar. */}
        <button type="button" onClick={close} className="sr-only">
          {t.comun.cerrar}
        </button>
        {header}
        <div
          ref={scroller}
          className="min-h-0 overflow-y-auto overscroll-contain"
          style={{ paddingBottom: footer ? "0.75rem" : "calc(env(safe-area-inset-bottom, 0px) + 1.25rem)" }}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
        {footer && (
          <div
            className="border-t border-line px-5 pt-3"
            style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1rem)" }}
          >
            {typeof footer === "function" ? footer(close) : footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
