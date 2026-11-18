import { useEffect, useRef, useState, type ReactNode } from "react";
import { t } from "../i18n/es";
import { copyText } from "../lib/clipboard";
import { Icon } from "./Icon";

const DONE_MS = 1500;

/** Copia `text` y lo confirma un momento con una marca. Devuelve si acaba de copiar y la función que copia. */
export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = (text: string) => {
    void copyText(text).then((ok) => {
      if (!ok) return;
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), DONE_MS);
    });
  };
  return [copied, copy];
}

/** Botón pequeño (solo icono) para copiar un dato. `label` dice qué copia, para quien no ve el icono. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, copy] = useCopy();
  return (
    <button
      type="button"
      aria-label={copied ? t.comun.copiado : t.comun.copiar(label)}
      title={copied ? t.comun.copiado : t.comun.copiar(label)}
      onClick={() => copy(text)}
      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full active:scale-90 ${
        copied ? "text-ok" : "text-text-2"
      }`}
    >
      <Icon name={copied ? "check" : "content_copy"} size={18} />
    </button>
  );
}

/** Un dato con su etiqueta y su botón de copiar (y, si se le pasa, algo más a la derecha: un enlace). */
export function CopyRow({
  label,
  value,
  children,
  extra,
}: {
  label: string;
  value: string;
  /** Lo que se pinta en lugar del texto (unas tallas tachadas, por ejemplo). Se copia `value`. */
  children?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-line bg-card-2 py-1 pr-1 pl-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 py-1">
        <span className="label-caps text-text-2">{label}</span>
        {children ?? <span className="text-sm break-words text-text select-text">{value}</span>}
      </div>
      {extra}
      <CopyButton text={value} label={label} />
    </div>
  );
}
