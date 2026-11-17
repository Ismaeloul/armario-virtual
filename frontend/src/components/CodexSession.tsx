import { useEffect, useState } from "react";
import { t } from "../i18n/es";
import { api, type AIStatus, type CodexLogin } from "../lib/api";
import { Icon } from "./Icon";

/** Iniciar y cerrar la sesión de Codex (suscripción de ChatGPT) sin pasar por la terminal. */
export function CodexSession({ ai, onChange }: { ai: AIStatus; onChange: () => void }) {
  const [login, setLogin] = useState<CodexLogin | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
    if (!window.confirm(t.codex.confirmarCerrar)) return;
    setBusy(true);
    api
      .codexLogout()
      .then(onChange)
      .catch((e: Error) => setError(e.message || t.codex.fallo))
      .finally(() => setBusy(false));
  };

  const copy = (code: string) => {
    navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined);
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
        <button type="button" onClick={cancel} className="self-start text-[11px] text-text-2 underline">
          {t.codex.cancelar}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {ai.codex_logged_in ? (
        <button
          type="button"
          disabled={busy}
          onClick={logout}
          className="flex h-10 items-center justify-center rounded-lg border border-line bg-control text-xs font-medium disabled:opacity-40"
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
      {error && <p className="text-[11px] text-danger">{error}</p>}
    </div>
  );
}
