import { useEffect, useState } from "react";
import { t } from "../i18n/es";
import { api } from "../lib/api";
import { Icon } from "./Icon";

/**
 * Borrar todo lo que el algoritmo ha aprendido de los gustos.
 * Está escondido tras «Opciones avanzadas» y pide dos toques, para no darle sin querer.
 */
export function ForgetTaste() {
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // Si no se confirma en unos segundos, el botón vuelve a su estado normal.
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(timer);
  }, [armed]);

  const press = () => {
    if (!armed) {
      setArmed(true);
      setDone(false);
      setFailed(false);
      return;
    }
    setBusy(true);
    api
      .tasteForget()
      .then(() => setDone(true))
      .catch(() => setFailed(true))
      .finally(() => {
        setArmed(false);
        setBusy(false);
      });
  };

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex min-h-11 items-center px-2 text-[11px] text-text-3 underline"
      >
        {t.ajustes.avanzadas}
      </button>
      {open && (
        <div className="flex w-full flex-col gap-2 rounded-2xl border border-line bg-card-2 p-4">
          <p className="text-xs text-text-2">{t.ajustes.olvidarTexto}</p>
          <button
            type="button"
            disabled={busy}
            onClick={press}
            className={`flex h-11 items-center justify-center gap-2 rounded-xl border text-xs font-semibold disabled:opacity-60 ${
              armed ? "border-danger bg-danger text-bg" : "border-line bg-control text-danger"
            }`}
          >
            <Icon name="delete_icon" size={18} />
            {armed ? t.ajustes.olvidarConfirmar : t.ajustes.olvidar}
          </button>
          {done && <p className="text-center text-[11px] text-text-2">{t.ajustes.olvidado}</p>}
          {failed && <p className="text-center text-[11px] text-danger">{t.comun.errorRed}</p>}
        </div>
      )}
    </div>
  );
}
