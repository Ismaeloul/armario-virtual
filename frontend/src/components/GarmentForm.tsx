import { cap, t } from "../i18n/es";
import type { Catalog, GarmentFields } from "../lib/api";
import { DEFAULT_HEX } from "../lib/colors";
import { Field, Segmented, inputClass } from "./Controls";
import { Icon } from "./Icon";

export const EMPTY_GARMENT: GarmentFields = {
  name: "",
  type: "camiseta",
  color_primary: { name: "negro", hex: DEFAULT_HEX.negro },
  colors_secondary: [],
  pattern: "liso",
  style: "casual",
  closure: null,
  hood: false,
  fit: null,
  thickness: null,
  details: "",
  season: "todo_el_ano",
  brand: null,
  size: null,
  notes: "",
  reference: null,
};

/** Tarjeta con los atributos editables de una prenda. La usan Nueva prenda y Editar. */
export function GarmentForm({
  catalog,
  form,
  onChange,
  colorDoubt,
}: {
  catalog: Catalog;
  form: GarmentFields;
  onChange: (form: GarmentFields) => void;
  /** Los dos colores entre los que dudaba la IA para el principal, si dudaba. */
  colorDoubt?: [string, string];
}) {
  const set = <K extends keyof GarmentFields>(key: K, value: GarmentFields[K]) => onChange({ ...form, [key]: value });

  const toggleSecondary = (name: string) =>
    set(
      "colors_secondary",
      form.colors_secondary.some((c) => c.name === name)
        ? form.colors_secondary.filter((c) => c.name !== name)
        : [...form.colors_secondary, { name, hex: DEFAULT_HEX[name] }].slice(0, 4),
    );

  // El color principal no puede estar también entre los secundarios.
  const setPrimary = (name: string) =>
    onChange({
      ...form,
      color_primary: { name, hex: DEFAULT_HEX[name] },
      colors_secondary: form.colors_secondary.filter((c) => c.name !== name),
    });

  // El calzado no tiene cierre, corte, grosor ni capucha: se limpian al pasar a un tipo de calzado.
  const setType = (type: string) =>
    onChange(
      catalog.types[type] === "calzado"
        ? { ...form, type, closure: null, fit: null, thickness: null, hood: false }
        : { ...form, type },
    );

  return (
    <div className="card flex flex-col gap-4 p-4">
      <Field label={t.nueva.campos.nombre}>
        <input className={inputClass} value={form.name} maxLength={120} onChange={(e) => set("name", e.target.value)} />
      </Field>

      <Field label={t.nueva.campos.tipo}>
        <select className={inputClass} value={form.type} onChange={(e) => setType(e.target.value)}>
          {Object.entries(catalog.categories).map(([cat, label]) => (
            <optgroup key={cat} label={label}>
              {Object.entries(catalog.types)
                .filter(([, c]) => c === cat)
                .map(([type]) => (
                  <option key={type} value={type}>
                    {cap(type)}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      </Field>

      <Field label={t.nueva.campos.colorPrincipal}>
        <div className="flex items-center gap-2">
          <input
            type="color"
            aria-label={t.nueva.campos.colorPrincipal}
            value={form.color_primary.hex}
            onChange={(e) => set("color_primary", { ...form.color_primary, hex: e.target.value })}
            className="h-11 w-11 shrink-0 cursor-pointer rounded-full border border-line bg-transparent p-0"
          />
          <select
            className={inputClass}
            value={form.color_primary.name}
            onChange={(e) => setPrimary(e.target.value)}
          >
            {catalog.colors.map((c) => (
              <option key={c} value={c}>
                {cap(c)}
              </option>
            ))}
          </select>
        </div>
      </Field>

      {/* Aviso cuando la IA no tenía claro el color: se puede cambiar al otro candidato con un toque. */}
      {colorDoubt && (
        <div className="-mt-2 flex flex-col gap-2 rounded-lg border border-line bg-chip/50 p-3">
          <p className="flex items-start gap-2 text-xs text-text">
            <Icon name="error" size={16} className="mt-px shrink-0 text-primary" />
            {t.nueva.dudaColor(cap(colorDoubt[0]), cap(colorDoubt[1]))}
          </p>
          <div className="flex gap-2">
            {colorDoubt.map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={form.color_primary.name === c}
                onClick={() => setPrimary(c)}
                className={`flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-full border px-2.5 py-2 text-xs font-medium ${
                  form.color_primary.name === c ? "border-primary bg-card text-text" : "border-line bg-card-2 text-text-2"
                }`}
              >
                <span className="h-2.5 w-2.5 rounded-full border border-text/10" style={{ background: DEFAULT_HEX[c] }} />
                {cap(c)}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <span className="label-caps text-text-2">{t.nueva.campos.coloresSecundarios}</span>
        <div className="flex flex-wrap gap-1.5">
          {catalog.colors
            .filter((c) => c !== form.color_primary.name)
            .map((c) => {
              const active = form.colors_secondary.find((s) => s.name === c);
              return (
                <button
                  key={c}
                  type="button"
                  aria-pressed={!!active}
                  onClick={() => toggleSecondary(c)}
                  className={`flex min-h-10 items-center gap-1.5 rounded-full border px-3 py-2 text-xs ${
                    active ? "border-primary bg-chip text-on-chip" : "border-line bg-card-2 text-text-2"
                  }`}
                >
                  <span
                    className="h-2.5 w-2.5 rounded-full border border-text/10"
                    style={{ background: active?.hex ?? DEFAULT_HEX[c] }}
                  />
                  {cap(c)}
                </button>
              );
            })}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label={t.nueva.campos.estampado}>
          <select className={inputClass} value={form.pattern} onChange={(e) => set("pattern", e.target.value)}>
            {catalog.patterns.map((p) => (
              <option key={p} value={p}>
                {cap(p)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t.nueva.campos.estilo}>
          <select className={inputClass} value={form.style} onChange={(e) => set("style", e.target.value)}>
            {catalog.styles.map((s) => (
              <option key={s} value={s}>
                {cap(s)}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {catalog.types[form.type] !== "calzado" && (
        <>
      {/* Dos columnas: en tres, «Sin indicar» y valores largos se cortaban en un móvil de 375 px. */}
      <div className="grid grid-cols-2 gap-2">
        <Field label={t.nueva.campos.cierre}>
          <select className={inputClass} value={form.closure ?? ""} onChange={(e) => set("closure", e.target.value || null)}>
            <option value="">{t.nueva.campos.sinDato}</option>
            {catalog.closures.map((v) => (
              <option key={v} value={v}>
                {cap(v)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t.nueva.campos.corte}>
          <select className={inputClass} value={form.fit ?? ""} onChange={(e) => set("fit", e.target.value || null)}>
            <option value="">{t.nueva.campos.sinDato}</option>
            {catalog.fits.map((v) => (
              <option key={v} value={v}>
                {cap(v)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t.nueva.campos.grosor}>
          <select className={inputClass} value={form.thickness ?? ""} onChange={(e) => set("thickness", e.target.value || null)}>
            <option value="">{t.nueva.campos.sinDato}</option>
            {catalog.thicknesses.map((v) => (
              <option key={v} value={v}>
                {cap(v)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <label className="-mt-2 flex min-h-11 items-center gap-2.5 text-sm text-text">
        <input
          type="checkbox"
          className="h-5 w-5 accent-primary"
          checked={form.hood}
          onChange={(e) => set("hood", e.target.checked)}
        />
        {t.nueva.campos.capucha}
      </label>
        </>
      )}

      <div className="flex flex-col gap-1.5">
        <span className="label-caps text-text-2">{t.nueva.campos.temporada}</span>
        <Segmented
          value={form.season}
          onChange={(v) => set("season", v)}
          options={Object.entries(catalog.seasons).map(([value, label]) => ({ value, label }))}
        />
      </div>

      <Field label={t.nueva.campos.detalles}>
        <input
          className={inputClass}
          value={form.details}
          maxLength={300}
          onChange={(e) => set("details", e.target.value)}
        />
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label={t.nueva.campos.marca}>
          <input
            className={inputClass}
            value={form.brand ?? ""}
            maxLength={80}
            onChange={(e) => set("brand", e.target.value || null)}
          />
        </Field>
        <Field label={t.nueva.campos.talla}>
          <input
            className={inputClass}
            value={form.size ?? ""}
            maxLength={20}
            onChange={(e) => set("size", e.target.value || null)}
          />
        </Field>
      </div>

      <Field label={t.nueva.campos.referencia}>
        <input
          className={inputClass}
          value={form.reference ?? ""}
          maxLength={40}
          placeholder={t.nueva.campos.referenciaEjemplo}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          onChange={(e) => set("reference", e.target.value || null)}
        />
      </Field>

      <Field label={t.nueva.campos.notas}>
        <textarea
          className={inputClass}
          rows={3}
          value={form.notes}
          maxLength={500}
          onChange={(e) => set("notes", e.target.value)}
        />
      </Field>
    </div>
  );
}
