import type { ReactNode } from "react";

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
          className={`flex-1 rounded-lg px-1 py-1.5 text-xs font-medium transition-colors ${
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

export const inputClass =
  "w-full rounded-lg border border-line bg-card-2 px-3.5 py-2.5 text-sm text-text outline-none " +
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

export function SecondaryButton({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-line bg-control text-xs font-medium text-text transition-transform active:scale-[0.98]"
    >
      {children}
    </button>
  );
}
