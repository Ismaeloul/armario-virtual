import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n/es";

/**
 * Diálogo de confirmación propio (en vez de window.confirm, que en la PWA o en Capacitor puede no
 * mostrarse). Se cierra con Escape o tocando fuera, salvo mientras la acción está en curso.
 */
export function ConfirmDialog({
  open,
  title,
  text,
  confirmLabel,
  busyLabel,
  busy = false,
  error,
  destructive = true,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  text?: string;
  confirmLabel: string;
  /** Texto del botón mientras se hace la acción («Eliminando…»). */
  busyLabel?: string;
  busy?: boolean;
  error?: string | null;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const textId = useId();
  // Se guarda en una ref para no rehacer el efecto en cada render del padre.
  const state = useRef({ busy, onCancel });
  state.current = { busy, onCancel };

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    cancelButton.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (!state.current.busy) state.current.onCancel();
        return;
      }
      if (e.key !== "Tab" || !panel.current) return;
      // Foco atrapado dentro del diálogo.
      const items = panel.current.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim backdrop-blur-[2px]"
      style={{
        paddingTop: "calc(env(safe-area-inset-top, 0px) + 1.25rem)",
        paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 1.25rem)",
        paddingLeft: "calc(env(safe-area-inset-left, 0px) + 1.25rem)",
        paddingRight: "calc(env(safe-area-inset-right, 0px) + 1.25rem)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={text ? textId : undefined}
        className="card flex w-full max-w-sm flex-col gap-4 p-5"
      >
        <div className="flex flex-col gap-1.5">
          <h2 id={titleId} className="font-display text-lg font-semibold leading-snug tracking-tight">
            {title}
          </h2>
          {text && (
            <p id={textId} className="text-sm text-text-2">
              {text}
            </p>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className={`flex h-12 items-center justify-center rounded-xl font-display text-[15px] font-semibold transition-transform active:scale-[0.98] disabled:opacity-60 ${
              destructive ? "bg-danger text-bg" : "bg-primary text-on-primary"
            }`}
          >
            {busy && busyLabel ? busyLabel : confirmLabel}
          </button>
          <button
            ref={cancelButton}
            type="button"
            disabled={busy}
            onClick={onCancel}
            className="flex h-12 items-center justify-center rounded-xl border border-line bg-control text-sm font-medium text-text transition-transform active:scale-[0.98] disabled:opacity-40"
          >
            {t.comun.cancelar}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
