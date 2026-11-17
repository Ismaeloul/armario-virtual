import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PrimaryButton, RotateButton, SecondaryButton, Segmented } from "../components/Controls";
import { EMPTY_GARMENT, GarmentForm } from "../components/GarmentForm";
import { Icon, type IconName } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { ApiError, api, mediaUrl, type Analysis, type Catalog, type GarmentFields } from "../lib/api";
import { pickPhoto, rotateFile } from "../lib/camera";

type Step = "fotos" | "analizando" | "error" | "formulario";

/** Ranura de foto: vacía (botón para tomarla) o con la imagen elegida. */
function PhotoSlot({
  label,
  hint,
  preview,
  onPick,
  onRotate,
}: {
  label: string;
  hint?: string;
  preview: string | null;
  onPick: () => void;
  onRotate: () => void;
}) {
  return (
    <div className="relative">
      {preview && <RotateButton onClick={onRotate} className="absolute right-2 top-2 z-10" />}
      <button type="button" onClick={onPick} className="card flex w-full flex-col overflow-hidden text-left active:opacity-80">
      <div className="relative flex aspect-[3/4] w-full flex-col items-center justify-center bg-card-2 p-4 text-center">
        {preview ? (
          <>
            <img src={preview} alt={label} className="absolute inset-0 h-full w-full object-cover" />
            <span className="absolute bottom-2.5 right-2.5 flex h-9 w-9 items-center justify-center rounded-full bg-text/80 text-bg">
              <Icon name="photo_camera" size={18} />
            </span>
          </>
        ) : (
          <>
            <span className="mb-2 flex h-12 w-12 items-center justify-center rounded-full border border-line bg-card text-primary">
              <Icon name="add_a_photo" />
            </span>
            <span className="font-display text-[15px] font-semibold">{label}</span>
            {hint && <span className="mt-1 text-xs leading-tight text-text-2">{hint}</span>}
          </>
        )}
        {/* Con la ranura vacía el nombre ya sale en el centro: el chip solo hace falta sobre la foto. */}
        {preview && (
          <span className="label-caps absolute left-2 top-2 rounded-full border border-line bg-card/90 px-2 py-0.5 backdrop-blur-md">
            {label}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between px-2.5 py-2 text-xs text-text-2">
        <span>{preview ? t.nueva.cambiarFoto : (hint ? t.nueva.opcional : t.nueva.tomarFoto)}</span>
        {preview && <Icon name="check_circle" size={16} className="text-primary" />}
      </div>
      </button>
    </div>
  );
}

/** Fila para una foto opcional (otro lateral, etiqueta): miniatura, texto y botones de girar/quitar. */
function RowSlot({
  icon,
  title,
  help,
  file,
  preview,
  onPick,
  onChange,
}: {
  icon: IconName;
  title: string;
  help: string;
  file: File | null;
  preview: string | null;
  onPick: () => void;
  onChange: (file: File | null) => void;
}) {
  return (
    <div className="card flex items-center gap-3 p-3">
      <button type="button" onClick={onPick} className="flex min-w-0 flex-1 items-center gap-3 text-left active:opacity-70">
        {preview ? (
          <img src={preview} alt={title} className="h-14 w-14 shrink-0 rounded-lg object-cover" />
        ) : (
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-card-2 text-primary">
            <Icon name={icon} />
          </span>
        )}
        <span className="min-w-0">
          <span className="flex items-center gap-2">
            <span className="font-display text-[15px] font-semibold">{title}</span>
            <span className="label-caps rounded-full bg-chip px-2 py-0.5 text-on-chip">{t.nueva.opcional}</span>
          </span>
          <span className="mt-0.5 block text-xs leading-tight text-text-2">{preview ? t.nueva.etiquetaLista : help}</span>
        </span>
      </button>
      {file && (
        <div className="flex shrink-0 items-center">
          <RotateButton onClick={() => rotateFile(file).then(onChange)} />
          <button
            type="button"
            onClick={() => onChange(null)}
            className="inline-flex min-h-11 items-center px-2 text-[11px] text-text-2 underline"
          >
            {t.nueva.quitar}
          </button>
        </div>
      )}
    </div>
  );
}

export default function AnadirPrenda() {
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [preferred, setPreferred] = useState("codex");
  const [step, setStep] = useState<Step>("fotos");
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [extra, setExtra] = useState<File | null>(null);
  const [label, setLabel] = useState<File | null>(null);
  const [kind, setKind] = useState<"ropa" | "calzado">("ropa");
  const [frontUrl, setFrontUrl] = useState<string | null>(null);
  const [backUrl, setBackUrl] = useState<string | null>(null);
  const [labelUrl, setLabelUrl] = useState<string | null>(null);
  const [extraUrl, setExtraUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [form, setForm] = useState<GarmentFields>(EMPTY_GARMENT);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then(setCatalog).catch(() => undefined);
    api.settings().then((s) => setPreferred(s.ai_provider)).catch(() => undefined);
  }, []);

  // Vistas previas locales de las fotos elegidas.
  useEffect(() => {
    const url = front ? URL.createObjectURL(front) : null;
    setFrontUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [front]);
  useEffect(() => {
    const url = back ? URL.createObjectURL(back) : null;
    setBackUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [back]);
  useEffect(() => {
    const url = label ? URL.createObjectURL(label) : null;
    setLabelUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [label]);
  useEffect(() => {
    const url = extra ? URL.createObjectURL(extra) : null;
    setExtraUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [extra]);

  const pick = async (set: (f: File) => void) => {
    const file = await pickPhoto();
    if (file) set(file);
  };

  /** Sube las fotos (o reutiliza las ya subidas) y pide el borrador a la IA. */
  const runAnalysis = async (skipAi: boolean) => {
    if (!front && !analysis) return;
    setStep("analizando");
    try {
      const result = await api.analyze(
        analysis
          ? {
              frontId: analysis.photo_front.id,
              backId: analysis.photo_back?.id,
              extraId: analysis.photo_extra?.id,
              labelId: analysis.photo_label?.id,
              kind,
              skipAi,
            }
          : {
              front: front!,
              back: back ?? undefined,
              extra: kind === "calzado" ? (extra ?? undefined) : undefined,
              label: label ?? undefined,
              kind,
              skipAi,
            },
      );
      setAnalysis(result);
      if (result.draft) {
        const { confidence: _c, color_primary_alt: _alt, ...fields } = result.draft;
        setForm(fields);
        setStep("formulario");
      } else if (skipAi) {
        // Formulario limpio (sin restos de un intento anterior) y con un tipo acorde a lo elegido.
        setForm({ ...EMPTY_GARMENT, type: kind === "calzado" ? "zapatillas" : "camiseta" });
        setStep("formulario");
      } else {
        setStep("error");
      }
    } catch {
      setStep(analysis ? "error" : "fotos");
      if (!analysis) setFormError(t.comun.errorRed);
    }
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!analysis) return;
    if (!form.name.trim()) {
      setFormError(t.nueva.falta);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api.createGarment({
        ...form,
        photo_front: analysis.photo_front.id,
        photo_back: analysis.photo_back?.id ?? null,
        photo_extra: analysis.photo_extra?.id ?? null,
        photo_label: analysis.photo_label?.id ?? null,
        ai_provider: analysis.draft ? analysis.provider : null,
        ai_confidence: analysis.draft?.confidence ?? null,
        ai_draft: analysis.draft, // la propuesta original, para ver después qué se corrigió
      });
      navigate("/armario", { replace: true });
    } catch (err) {
      // 409: ya estaba guardada (un reintento tras perder la respuesta): no es un error para el usuario.
      if (err instanceof ApiError && err.status === 409) {
        navigate("/armario", { replace: true });
        return;
      }
      setFormError(t.nueva.errorGuardar);
      setSaving(false);
    }
  };

  const provider = analysis?.provider ? t.proveedores[analysis.provider] : "";

  return (
    <>
      <BackHeader title={t.nueva.cabecera} />
      <Screen withNav={false}>
        <div className="flex flex-col gap-1">
          <span className="label-caps tracking-widest text-primary">{t.nueva.etiqueta}</span>
          <h2 className="font-display text-2xl font-semibold tracking-tight">{t.nueva.titulo}</h2>
        </div>

        {step === "fotos" && (
          <div className="mt-6 flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span className="label-caps text-text-2">{t.nueva.queEs}</span>
              <Segmented
                value={kind}
                onChange={setKind}
                options={[
                  { value: "ropa", label: t.nueva.ropa },
                  { value: "calzado", label: t.nueva.calzado },
                ]}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <PhotoSlot
                label={kind === "calzado" ? t.nueva.lateral : t.nueva.delante}
                preview={frontUrl}
                onPick={() => pick(setFront)}
                onRotate={() => front && rotateFile(front).then(setFront)}
              />
              <PhotoSlot
                label={kind === "calzado" ? t.nueva.frente : t.nueva.detras}
                hint={kind === "calzado" ? t.nueva.frenteAyuda : t.nueva.detrasAyuda}
                preview={backUrl}
                onPick={() => pick(setBack)}
                onRotate={() => back && rotateFile(back).then(setBack)}
              />
            </div>

            {/* En el calzado, una tercera vista: no todas las zapatillas son iguales por los dos lados. */}
            {kind === "calzado" && (
              <RowSlot
                icon="add_a_photo"
                title={t.nueva.otroLado}
                help={t.nueva.otroLadoAyuda}
                file={extra}
                preview={extraUrl}
                onPick={() => pick(setExtra)}
                onChange={setExtra}
              />
            )}

            {/* La etiqueta, para que la IA rellene marca y talla. */}
            <RowSlot
              icon="sell"
              title={t.nueva.etiquetaFoto}
              help={t.nueva.etiquetaAyuda}
              file={label}
              preview={labelUrl}
              onPick={() => pick(setLabel)}
              onChange={setLabel}
            />
            {formError && <p className="text-center text-sm text-danger">{formError}</p>}
            <PrimaryButton disabled={!front} onClick={() => runAnalysis(false)}>
              <Icon name="auto_awesome" size={20} />
              {t.nueva.analizar}
            </PrimaryButton>
            <button
              type="button"
              disabled={!front}
              onClick={() => runAnalysis(true)}
              className="py-2 text-center text-xs font-medium text-text-2 disabled:opacity-40"
            >
              {t.nueva.aMano}
            </button>
          </div>
        )}

        {step === "analizando" && (
          <div className="card mt-6 flex flex-col items-center gap-3 p-8 text-center">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-primary" />
            </span>
            <h3 className="font-display text-lg font-semibold">{t.nueva.analizando}</h3>
            <p className="text-sm text-text-2">{t.nueva.analizandoTexto}</p>
          </div>
        )}

        {/* Estado de error: la IA no respondió. Reintentar o rellenar a mano. */}
        {step === "error" && (
          <div className="card mt-6 flex flex-col items-center gap-3 p-6 text-center">
            <Icon name="error" size={32} className="text-danger" />
            <h3 className="font-display text-lg font-semibold">{t.nueva.error.titulo}</h3>
            <p className="text-sm text-text-2">{t.nueva.error.texto}</p>
            <div className="mt-2 flex w-full flex-col gap-2">
              <PrimaryButton onClick={() => runAnalysis(false)}>
                <Icon name="refresh" size={20} />
                {t.comun.reintentar}
              </PrimaryButton>
              <SecondaryButton onClick={() => runAnalysis(true)}>{t.nueva.aMano}</SecondaryButton>
            </div>
          </div>
        )}

        {step === "formulario" && analysis && catalog && (
          <form onSubmit={save} className="mt-6 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-2">
              {(["photo_front", "photo_back", "photo_extra", "photo_label"] as const).map((side) => {
                const photo = analysis[side];
                return (
                  photo && (
                    <div key={side} className="relative">
                      <img
                        src={mediaUrl(photo.url)}
                        alt=""
                        className="aspect-[3/4] w-full rounded-xl border border-line object-cover"
                      />
                      <RotateButton
                        className="absolute right-2 top-2"
                        onClick={() =>
                          api
                            .rotatePhoto(photo.id)
                            .then((rotated) => setAnalysis((a) => (a ? { ...a, [side]: rotated } : a)))
                            .catch(() => undefined)
                        }
                      />
                    </div>
                  )
                );
              })}
            </div>

            {/* Quién analizó. El plan B nunca es silencioso. */}
            {analysis.draft && (
              <div className="card flex items-center justify-between gap-2 px-4 py-3">
                <span className="flex items-center gap-2 text-xs font-medium">
                  <Icon name="auto_awesome" size={16} className="text-primary" />
                  {analysis.fallback_used
                    ? t.nueva.planB(t.proveedores[preferred] ?? cap(preferred), provider)
                    : t.nueva.analizadoCon(provider)}
                </span>
                <span className="label-caps shrink-0 rounded-full bg-chip px-2 py-0.5 text-on-chip">
                  {t.nueva.certeza(Math.round(analysis.draft.confidence * 100))}
                </span>
              </div>
            )}

            <span className="label-caps text-text-2">{t.nueva.atributos}</span>
            <GarmentForm
              catalog={catalog}
              form={form}
              onChange={setForm}
              colorDoubt={
                analysis.draft?.color_primary_alt
                  ? [analysis.draft.color_primary.name, analysis.draft.color_primary_alt]
                  : undefined
              }
            />

            {formError && <p className="text-center text-sm text-danger">{formError}</p>}
            <PrimaryButton type="submit" disabled={saving}>
              <Icon name="bookmark_add" size={20} />
              {saving ? t.nueva.guardando : t.nueva.guardar}
            </PrimaryButton>
          </form>
        )}
      </Screen>
    </>
  );
}
