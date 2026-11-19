import { useState } from "react";
import { t } from "../i18n/es";
import { ApiError, api, type ApishStatus, type Settings } from "../lib/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { inputClass } from "./Controls";
import { Icon } from "./Icon";

/**
 * La clave de API.SH (Ajustes). Petición del usuario: se pega una vez y NADIE la vuelve a ver. El campo es
 * de contraseña, se vacía al guardar y la API nunca la devuelve: después solo se ve «Clave guardada» con
 * «Cambiar» y «Borrar». Debajo, los créditos del mes (comunes a todas las tiendas de API.SH).
 */
export function ApishKey({ status, onSaved }: { status: ApishStatus; onSaved: (s: Settings) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const text = t.ajustes.apish;

  const close = () => {
    setValue("");
    setEditing(false);
    setError(null);
  };
  const save = () => {
    const key = value.trim();
    if (!key || busy) return;
    setBusy(true);
    setError(null);
    api
      .saveApishKey(key)
      .then((saved) => {
        onSaved(saved);
        close();
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 400 ? e.message : text.errorGuardar))
      .finally(() => setBusy(false));
  };
  const remove = () => {
    setBusy(true);
    setError(null);
    api
      .deleteApishKey()
      .then((saved) => {
        onSaved(saved);
        setConfirming(false);
      })
      .catch(() => setError(t.comun.errorRed))
      .finally(() => setBusy(false));
  };

  return (
    <>
      {status.from_env ? (
        <p className="flex items-center gap-2 text-xs text-text-2">
          <Icon name="check_circle" size={16} className="shrink-0 text-primary" />
          {text.delEntorno}
        </p>
      ) : editing ? (
        <form
          className="flex flex-col gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <label htmlFor="clave-apish" className="label-caps text-text-2">
            {text.etiqueta}
          </label>
          <div className="flex gap-2">
            <input
              id="clave-apish"
              type="password"
              autoComplete="off"
              autoFocus
              spellCheck={false}
              className={inputClass}
              placeholder={text.placeholder}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button
              type="submit"
              disabled={!value.trim() || busy}
              className="shrink-0 rounded-lg bg-primary px-4 text-xs font-semibold text-on-primary disabled:opacity-40"
            >
              {text.guardar}
            </button>
          </div>
          <button
            type="button"
            onClick={close}
            className="-ml-2 inline-flex min-h-11 items-center self-start px-2 text-[11px] text-text-2"
          >
            {text.cancelar}
          </button>
        </form>
      ) : status.has_key ? (
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-2 text-xs font-medium">
            <Icon name="check_circle" size={16} className="shrink-0 text-primary" />
            {text.guardada}
          </p>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="inline-flex min-h-11 items-center px-2 text-xs font-semibold text-primary"
            >
              {text.cambiar}
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setConfirming(true);
              }}
              className="inline-flex min-h-11 items-center px-2 text-xs font-semibold text-danger"
            >
              {text.borrar}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-2 text-xs text-text-2">
            <Icon name="error" size={16} className="shrink-0 text-text-3" />
            {text.falta}
          </p>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-chip px-4 py-2.5 font-display text-xs font-semibold text-on-chip active:scale-[0.99]"
          >
            {text.pegar}
          </button>
        </div>
      )}
      {error && !confirming && (
        <p role="alert" className="px-0.5 text-[11px] text-danger">
          {error}
        </p>
      )}
      <p className="px-0.5 text-[11px] text-text-3">{text.ayuda}</p>
      <div className="flex flex-col gap-0.5 border-t border-control pt-3">
        <p
          className={`text-xs font-medium ${status.credits_used >= status.credits_limit ? "text-danger" : "text-text"}`}
        >
          {text.creditos(status.credits_used, status.credits_limit)}
        </p>
        <p className="px-0.5 text-[11px] text-text-3">{text.creditosAyuda}</p>
      </div>
      <ConfirmDialog
        open={confirming}
        title={text.borrarTitulo}
        text={text.borrarTexto}
        confirmLabel={text.borrarBoton}
        busyLabel={text.borrando}
        busy={busy}
        error={confirming ? error : null}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
