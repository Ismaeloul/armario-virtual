import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PrimaryButton, RotateButton, SecondaryButton } from "../components/Controls";
import { EMPTY_GARMENT, GarmentForm } from "../components/GarmentForm";
import { Icon } from "../components/Icon";
import { BackHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Analysis, type Catalog, type GarmentFields } from "../lib/api";
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
        <span className="label-caps absolute left-2 top-2 rounded-full border border-line bg-card/90 px-2 py-0.5 backdrop-blur-md">
          {label}
        </span>
      </div>
      <div className="flex items-center justify-between px-2.5 py-2 text-xs text-text-2">
        <span>{preview ? t.nueva.cambiarFoto : (hint ? t.nueva.opcional : t.nueva.tomarFoto)}</span>
        {preview && <Icon name="check_circle" size={16} className="text-primary" />}
      </div>
      </button>
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
  const [frontUrl, setFrontUrl] = useState<string | null>(null);
  const [backUrl, setBackUrl] = useState<string | null>(null);
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
          ? { frontId: analysis.photo_front.id, backId: analysis.photo_back?.id, skipAi }
          : { front: front!, back: back ?? undefined, skipAi },
      );
      setAnalysis(result);
      if (result.draft) {
        const { confidence: _c, ...fields } = result.draft;
        setForm(fields);
        setStep("formulario");
      } else if (skipAi) {
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
        ai_provider: analysis.draft ? analysis.provider : null,
        ai_confidence: analysis.draft?.confidence ?? null,
        ai_draft: analysis.draft, // la propuesta original, para ver después qué se corrigió
      });
      navigate("/armario", { replace: true });
    } catch {
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
            <div className="grid grid-cols-2 gap-2">
              <PhotoSlot
                label={t.nueva.delante}
                preview={frontUrl}
                onPick={() => pick(setFront)}
                onRotate={() => front && rotateFile(front).then(setFront)}
              />
              <PhotoSlot
                label={t.nueva.detras}
                hint={t.nueva.detrasAyuda}
                preview={backUrl}
                onPick={() => pick(setBack)}
                onRotate={() => back && rotateFile(back).then(setBack)}
              />
            </div>
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
              {(["photo_front", "photo_back"] as const).map((side) => {
                const photo = analysis[side];
                return (
                  photo && (
                    <div key={side} className="relative">
                      <img
                        src={mediaUrl(photo.url)}
                        alt={side === "photo_front" ? t.nueva.delante : t.nueva.detras}
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
            <GarmentForm catalog={catalog} form={form} onChange={setForm} />

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
