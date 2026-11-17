import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PrimaryButton } from "../components/Controls";
import { GarmentForm } from "../components/GarmentForm";
import { Icon } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { t } from "../i18n/es";
import { api, type Catalog, type GarmentFields } from "../lib/api";

export default function EditarPrenda() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<GarmentFields | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then(setCatalog).catch(() => undefined);
    api
      .garment(Number(id))
      .then((g) =>
        setForm({
          name: g.name,
          type: g.type,
          color_primary: g.color_primary,
          colors_secondary: g.colors_secondary,
          pattern: g.pattern,
          style: g.style,
          closure: g.closure,
          hood: g.hood,
          fit: g.fit,
          thickness: g.thickness,
          details: g.details,
          season: g.season,
          brand: g.brand,
          size: g.size,
          notes: g.notes,
        }),
      )
      .catch(() => setError(t.ficha.noExiste));
  }, [id]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    if (!form.name.trim()) {
      setError(t.nueva.falta);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateGarment(Number(id), form);
      navigate(-1);
    } catch {
      setError(t.nueva.errorGuardar);
      setSaving(false);
    }
  };

  return (
    <>
      <BackHeader title={t.editar.cabecera} />
      <Screen withNav={false}>
        {form && catalog ? (
          <form onSubmit={save} className="flex flex-col gap-4">
            <GarmentForm catalog={catalog} form={form} onChange={setForm} />
            {error && <p className="text-center text-sm text-danger">{error}</p>}
            <PrimaryButton type="submit" disabled={saving}>
              <Icon name="check_circle" size={20} />
              {saving ? t.nueva.guardando : t.editar.guardar}
            </PrimaryButton>
          </form>
        ) : (
          <p className="mt-10 text-center text-sm text-text-3">{error ?? t.comun.cargando}</p>
        )}
      </Screen>
    </>
  );
}
