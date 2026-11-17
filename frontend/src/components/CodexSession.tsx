import { useEffect, useState } from "react";
import { t } from "../i18n/es";
import { api, type AIStatus, type CodexLogin, type CodexUsage, type UsageWindow } from "../lib/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

function resetText(resetsAt: number | null): string {
  if (!resetsAt) return "";
  const date = new Date(resetsAt * 1000);
  const sameDay = date.toDateString() === new Date().toDateString();
  const time = date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  return sameDay
    ? t.codex.hoyA(time)
    : t.codex.elDiaA(date.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" }), time);
}

function UsageBar({ label, window }: { label: string; window: UsageWindow }) {
  const used = Math.round(window.used_percent ?? 0);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-text-2">{t.codex.usado(used)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-control">
        <div
          className={`h-full rounded-full ${used >= 90 ? "bg-danger" : "bg-primary"}`}
          style={{ width: `${Math.min(100, Math.max(2, used))}%` }}
        />
      </div>
      {window.resets_at && <span className="text-[11px] text-text-3">{t.codex.seRenueva(resetText(window.resets_at))}</span>}
    </div>
  );
}

/** Cuánto límite de la suscripción queda: ventana de 5 horas y semanal. */
function Usage() {
  const [usage, setUsage] = useState<CodexUsage | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setFailed(false);
    api
      .codexUsage()
      .then(setUsage)
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-line bg-card-2 p-3.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold">
          {t.codex.uso}
          {usage?.plan && <span className="ml-2 font-normal capitalize text-text-2">{t.codex.plan(usage.plan)}</span>}
        </span>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="-my-2 -mr-2 inline-flex min-h-11 items-center px-2 text-[11px] text-text-2 underline disabled:opacity-40"
        >
          {loading ? t.comun.cargando : t.codex.actualizar}
        </button>
      </div>
      {failed && <p className="text-[11px] text-danger">{t.codex.usoError}</p>}
      {usage?.primary && <UsageBar label={t.codex.ventana5h} window={usage.primary} />}
      {usage?.secondary && <UsageBar label={t.codex.ventanaSemana} window={usage.secondary} />}
      {usage && !usage.allowed && <p className="text-[11px] text-danger">{t.codex.agotado}</p>}
    </div>
  );
}

/** Iniciar y cerrar la sesión de Codex (suscripción de ChatGPT) sin pasar por la terminal. */
export function CodexSession({ ai, onChange }: { ai: AIStatus; onChange: () => void }) {
  const [login, setLogin] = useState<CodexLogin | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // Por si ya había un inicio de sesión en curso al abrir Ajustes.
  useEffect(() => {
    api.codexLoginStatus().then((s) => s.state === "pending" && setLogin(s)).catch(() => undefined);
  }, []);

  // Mientras se espera el código, se pregunta al servidor cada 3 segundos.
  useEffect(() => {
    if (login?.state !== "pending") return;
    const timer = setInterval(() => {
      api
        .codexLoginStatus()
        .then((s) => {
          if (s.state === "pending") return setLogin(s);
          setLogin(null);
          if (s.state === "failed") setError(s.error ?? t.codex.fallo);
          onChange();
        })
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [login?.state, onChange]);

  if (!ai.codex_installed) return null;

  const start = () => {
    setBusy(true);
    setError(null);
    api
      .codexLoginStart()
      .then(setLogin)
      .catch((e: Error) => setError(e.message || t.codex.fallo))
      .finally(() => setBusy(false));
  };

  const cancel = () => {
    setLogin(null);
    api.codexLoginCancel().catch(() => undefined);
  };

  const logout = () => {
    setBusy(true);
    setError(null);
    api
      .codexLogout()
      .then(() => {
        setConfirming(false);
        onChange();
      })
      .catch((e: Error) => setError(e.message || t.codex.fallo))
      .finally(() => setBusy(false));
  };

  const copy = (code: string) => {
    const done = () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    };
    // El portapapeles moderno solo existe en páginas seguras (https o localhost). En el Umbrel la
    // app se abre por http, así que ahí se copia a la antigua: con un campo de texto oculto.
    const legacy = () => {
      const field = document.createElement("textarea");
      field.value = code;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      field.setSelectionRange(0, code.length); // iOS no selecciona con select() a secas
      try {
        if (document.execCommand("copy")) done();
      } finally {
        field.remove();
      }
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(code).then(done).catch(legacy);
    } else {
      legacy();
    }
  };

  if (login?.state === "pending" && login.url && login.code) {
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-line bg-card-2 p-3.5">
        <p className="text-xs font-semibold">{t.codex.pasos}</p>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-text-2">{t.codex.paso1}</span>
          <a
            href={login.url}
            target="_blank"
            rel="noreferrer"
            className="flex h-10 items-center justify-center gap-1.5 rounded-lg bg-primary text-xs font-semibold text-on-primary"
          >
            {t.codex.abrir}
            <Icon name="chevron_right" size={16} />
          </a>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-text-2">{t.codex.paso2}</span>
          <button
            type="button"
            onClick={() => copy(login.code!)}
            className="rounded-lg border border-line bg-card px-3 py-2.5 text-center font-mono text-xl font-semibold tracking-[0.2em]"
          >
            {login.code}
          </button>
          <span className="text-center text-[11px] text-text-3">{copied ? t.codex.copiado : t.codex.tocaCopiar}</span>
        </div>
        <p className="flex items-center gap-2 text-[11px] text-text-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
          </span>
          {t.codex.esperando}
        </p>
        <button
          type="button"
          onClick={cancel}
          className="-ml-2 inline-flex min-h-11 items-center self-start px-2 text-[11px] text-text-2 underline"
        >
          {t.comun.cancelar}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {ai.codex_logged_in && <Usage />}
      {ai.codex_logged_in ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setError(null);
            setConfirming(true);
          }}
          className="flex h-11 items-center justify-center rounded-lg border border-line bg-control text-xs font-medium disabled:opacity-40"
        >
          {t.codex.cerrar}
        </button>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={start}
          className="flex h-10 items-center justify-center rounded-lg bg-primary text-xs font-semibold text-on-primary disabled:opacity-40"
        >
          {busy ? t.codex.pidiendo : t.codex.iniciar}
        </button>
      )}
      {error && !confirming && <p className="text-[11px] text-danger">{error}</p>}
      <ConfirmDialog
        open={confirming}
        title={t.codex.confirmarTitulo}
        text={t.codex.confirmarCerrar}
        confirmLabel={t.codex.cerrarBoton}
        busy={busy}
        error={error}
        onConfirm={logout}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
