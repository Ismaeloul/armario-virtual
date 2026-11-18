import { useCallback, useState, type CSSProperties, type ImgHTMLAttributes } from "react";

/** Bloque gris con un destello que lo recorre: ocupa el sitio de lo que está cargando. */
export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div aria-hidden className={`skeleton ${className}`} style={style} />;
}

/** Retraso para que los elementos de una lista entren uno detrás de otro (los primeros; el resto, a la vez). */
export const stagger = (index: number, step = 45): CSSProperties => ({
  animationDelay: `${Math.min(index, 8) * step}ms`,
});

/** Una foto que aparece suavemente cuando termina de cargar, en vez de pintarse de golpe. */
export function FadeImg({ className = "", ...props }: ImgHTMLAttributes<HTMLImageElement>) {
  const [loaded, setLoaded] = useState(false);
  // Si ya estaba en la caché del navegador no llega el evento: se mira al montar.
  const ref = useCallback((img: HTMLImageElement | null) => {
    if (img?.complete) setLoaded(true);
  }, []);
  return (
    <img
      {...props}
      ref={ref}
      onLoad={() => setLoaded(true)}
      onError={() => setLoaded(true)}
      className={`${className} transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
    />
  );
}

/** El catálogo mientras carga: la misma rejilla de dos columnas del Armario. */
export function GridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div role="status" aria-busy="true" className="animate-fade">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="mt-2 h-9 w-48" />
      <Skeleton className="mt-2 h-4 w-40" />
      <Skeleton className="mt-4 h-11 w-full" />
      <div className="mt-4 flex gap-1.5 overflow-hidden">
        {[16, 28, 28, 24].map((w, i) => (
          <Skeleton key={i} className="h-9 shrink-0 rounded-full" style={{ width: `${w * 4}px` }} />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3.5">
        {Array.from({ length: cards }, (_, i) => (
          <div key={i} className="card flex flex-col p-2.5">
            <Skeleton className="aspect-[3/4] w-full" />
            <Skeleton className="mt-3 h-2.5 w-20" />
            <Skeleton className="mt-2 h-5 w-28" />
            <Skeleton className="mt-2 mb-1 h-3 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Una combinación (Hoy y Gustos) mientras carga: la tarjeta con sus prendas en fila. */
export function OutfitSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-busy="true" className="flex animate-fade flex-col gap-5">
      <div className="card flex flex-col p-5">
        <div className="flex items-center justify-between gap-2 pb-4">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </div>
        <div className="flex flex-col gap-3">
          {Array.from({ length: rows }, (_, i) => (
            <div key={i} className="flex items-center gap-3.5 rounded-2xl border border-line bg-card-2 p-2.5">
              <Skeleton className="h-24 w-20 shrink-0" />
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton className="h-2.5 w-24" />
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    </div>
  );
}

/** La ficha de una prenda mientras carga. */
export function DetailSkeleton() {
  return (
    <div role="status" aria-busy="true" className="flex animate-fade flex-col gap-4">
      <Skeleton className="aspect-[3/4] w-full" />
      <div>
        <Skeleton className="h-2.5 w-32" />
        <Skeleton className="mt-2 h-7 w-56" />
        <Skeleton className="mt-2 h-4 w-full" />
      </div>
      <Skeleton className="h-[72px] w-full" />
      <Skeleton className="h-5 w-48" />
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

/** Una lista de tarjetas con foto a la izquierda (Me gustan). */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-busy="true" className="flex animate-fade flex-col gap-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="card flex flex-col gap-3 p-3.5">
          <div className="flex gap-3.5">
            <Skeleton className="h-32 w-24 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-16" />
            </div>
          </div>
          <Skeleton className="h-11 w-full" />
        </div>
      ))}
    </div>
  );
}

/** La tarjeta grande de Descubrir mientras carga. */
export function CardSkeleton() {
  return (
    <div role="status" aria-busy="true" className="flex animate-fade flex-col gap-4">
      <div className="flex gap-1.5">
        <Skeleton className="h-9 w-24 rounded-full" />
        <Skeleton className="h-9 w-28 rounded-full" />
      </div>
      <Skeleton className="h-[58vh] w-full rounded-3xl" />
    </div>
  );
}
