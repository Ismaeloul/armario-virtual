import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";

const MAX = 6;
const DOUBLE_TAP = 2.5;

/**
 * Una foto a pantalla completa para mirarla de cerca: pellizco para ampliar, arrastrar para moverse,
 * doble toque para acercar o volver, y rueda del ratón en el ordenador. Con varias fotos (la tuya y
 * la de Codex) se cambia de una a otra SIN perder el zoom ni el sitio, para comparar el mismo detalle.
 * Se cierra con la X o con Escape; lo que hay debajo (el formulario) no se toca.
 */
export function ZoomViewer({
  photos,
  start = 0,
  closeLabel,
  onClose,
}: {
  photos: { label: string; url: string }[];
  start?: number;
  closeLabel: string;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(Math.min(start, photos.length - 1));
  // Lo que se pinta: escala y desplazamiento respecto al centro. `smooth` anima los cambios que no
  // vienen de un dedo en movimiento (doble toque, volver a 1).
  const [view, setView] = useState({ scale: 1, x: 0, y: 0, smooth: false });
  const box = useRef<HTMLDivElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; scale: number } | null>(null);
  const lastTap = useRef<{ time: number; x: number; y: number } | null>(null);
  const moved = useRef(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  /** Dentro de los bordes: ampliada no se puede sacar la foto de la pantalla; a tamaño normal, centrada. */
  const clamp = (scale: number, x: number, y: number) => {
    const rect = box.current?.getBoundingClientRect();
    const maxX = rect ? ((scale - 1) * rect.width) / 2 : 0;
    const maxY = rect ? ((scale - 1) * rect.height) / 2 : 0;
    return { x: Math.max(-maxX, Math.min(maxX, x)), y: Math.max(-maxY, Math.min(maxY, y)) };
  };

  /** Un punto de la pantalla, medido desde el centro del visor. */
  const fromCenter = (clientX: number, clientY: number) => {
    const rect = box.current!.getBoundingClientRect();
    return { x: clientX - rect.left - rect.width / 2, y: clientY - rect.top - rect.height / 2 };
  };

  /** Cambia la escala dejando quieto lo que hay bajo `point` (el dedo, el cursor). */
  const zoomAt = (point: { x: number; y: number }, target: number | ((now: number) => number), smooth: boolean) =>
    setView((now) => {
      // Con una función, la escala nueva sale de la que haya en ese momento: varios pasos de rueda
      // seguidos se suman en vez de pisarse.
      const wanted = typeof target === "function" ? target(now.scale) : target;
      const scale = Math.max(1, Math.min(MAX, wanted));
      const ratio = scale / now.scale;
      const moved = clamp(scale, point.x - (point.x - now.x) * ratio, point.y - (point.y - now.y) * ratio);
      return { scale, ...(scale === 1 ? { x: 0, y: 0 } : moved), smooth };
    });

  const distance = () => {
    const [a, b] = [...pointers.current.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  const middle = () => {
    const [a, b] = [...pointers.current.values()];
    return fromCenter((a.x + b.x) / 2, (a.y + b.y) / 2);
  };

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved.current = false;
    if (pointers.current.size === 2) pinch.current = { distance: distance(), scale: view.scale };
  };

  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const before = pointers.current.get(e.pointerId);
    if (!before) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2 && pinch.current) {
      moved.current = true;
      zoomAt(middle(), pinch.current.scale * (distance() / pinch.current.distance), false);
    } else if (pointers.current.size === 1) {
      const dx = e.clientX - before.x;
      const dy = e.clientY - before.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved.current = true;
      setView((now) => (now.scale === 1 ? now : { ...now, ...clamp(now.scale, now.x + dx, now.y + dy), smooth: false }));
    }
  };

  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    if (pointers.current.size > 0 || moved.current) return;
    // Un toque sin moverse: si es el segundo seguido en el mismo sitio, acerca (o vuelve).
    const now = Date.now();
    const tap = lastTap.current;
    if (tap && now - tap.time < 320 && Math.hypot(tap.x - e.clientX, tap.y - e.clientY) < 30) {
      lastTap.current = null;
      zoomAt(fromCenter(e.clientX, e.clientY), view.scale > 1 ? 1 : DOUBLE_TAP, true);
    } else {
      lastTap.current = { time: now, x: e.clientX, y: e.clientY };
    }
  };

  const photo = photos[index];

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={photo.label}
      className="fixed inset-0 z-[60] flex animate-fade flex-col bg-bg"
    >
      <div
        ref={box}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onWheel={(e) => zoomAt(fromCenter(e.clientX, e.clientY), (now) => now * (e.deltaY < 0 ? 1.15 : 1 / 1.15), false)}
        className="relative min-h-0 flex-1 touch-none overflow-hidden select-none"
        style={{ cursor: view.scale > 1 ? "grab" : "zoom-in" }}
      >
        <div className="h-full w-full animate-pop">
          <img
            src={photo.url}
            alt={photo.label}
            draggable={false}
            className="h-full w-full object-contain"
            style={{
              transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`,
              transition: view.smooth ? "transform 0.25s cubic-bezier(0.22, 1, 0.36, 1)" : "none",
              willChange: "transform",
            }}
          />
        </div>
      </div>

      <button
        type="button"
        aria-label={closeLabel}
        onClick={onClose}
        className="absolute right-3 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-control text-text active:scale-90"
        style={{ top: "calc(env(safe-area-inset-top, 0px) + 0.75rem)" }}
      >
        <Icon name="close" size={22} />
      </button>

      {/* Cambiar de foto sin mover el zoom: el mismo detalle en la tuya y en la de Codex. */}
      {photos.length > 1 && (
        <div
          className="flex justify-center px-4 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 0.75rem)" }}
        >
          <div className="flex gap-1 rounded-full border border-line bg-control p-1">
            {photos.map((p, i) => (
              <button
                key={p.url}
                type="button"
                aria-pressed={i === index}
                onClick={() => setIndex(i)}
                className={`min-h-10 rounded-full px-4 text-xs font-medium transition-colors duration-200 ${
                  i === index ? "bg-card text-text shadow-sm" : "text-text-2"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
