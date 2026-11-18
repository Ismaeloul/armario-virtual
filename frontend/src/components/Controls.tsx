import type { ReactNode } from "react";
import { t } from "../i18n/es";
import { Icon } from "./Icon";

/** Control segmentado tipo iOS (temporada, tema, proveedor de IA). */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-xl border border-line bg-control p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`flex min-h-10 flex-1 items-center justify-center rounded-lg px-1 py-1.5 text-xs font-medium transition-colors ${
            o.value === value ? "bg-card text-text shadow-sm" : "text-text-2"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="label-caps text-text-2">{label}</span>
      {children}
    </label>
  );
}

// text-base (16 px): con menos, Safari de iPhone amplía la página al enfocar el campo.
export const inputClass =
  "w-full rounded-lg border border-line bg-card-2 px-3.5 py-2.5 text-base text-text outline-none " +
  "placeholder:text-text-3 focus:ring-2 focus:ring-primary/40";

export function PrimaryButton({
  children,
  disabled,
  onClick,
  type = "button",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary transition-transform active:scale-[0.98] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  disabled,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-line bg-control text-xs font-medium text-text transition-transform active:scale-[0.98] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/** Botón redondo para girar una foto 90°. Se coloca encima de la imagen. */
export function RotateButton({
  onClick,
  disabled,
  className = "",
}: {
  onClick: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-label={t.comun.girar}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-11 w-11 items-center justify-center rounded-full bg-text/80 text-bg backdrop-blur-md active:scale-90 disabled:opacity-50 ${className}`}
    >
      <Icon name="rotate" size={18} />
    </button>
  );
}

/** Interruptor encendido/apagado. El área que se puede tocar mide 44 px de alto. */
export function Switch({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className="-mr-1 flex h-11 shrink-0 items-center px-1"
    >
      <span
        className={`flex h-7 w-12 items-center rounded-full p-0.5 transition-colors ${
          checked ? "justify-end bg-primary" : "justify-start bg-control"
        }`}
      >
        <span className={`h-6 w-6 rounded-full shadow ${checked ? "bg-on-primary" : "bg-text-3"}`} />
      </span>
    </button>
  );
}
