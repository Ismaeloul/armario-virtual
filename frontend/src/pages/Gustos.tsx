import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { FadeImg, OutfitSkeleton, Skeleton, stagger } from "../components/Skeleton";
import { GarmentSheet } from "../components/GarmentSheet";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Catalog, type Garment, type Taste } from "../lib/api";

const REASONS = ["colores", "calzado", "estilo", "soso", "recargado"] as const;

/** Valorar combinaciones para que el algoritmo aprenda qué pega y qué no. */
export default function Gustos() {
  const [state, setState] = useState<Taste | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // Al decir "no me gusta" se pregunta por qué antes de pasar a la siguiente.
  const [asking, setAsking] = useState(false);
  const [reasons, setReasons] = useState<string[]>([]);
  const [culprits, setCulprits] = useState<number[]>([]);
  const [sendError, setSendError] = useState(false);
  const [saved, setSaved] = useState(false); // el último fue «Me gusta y guardar»
  // La prenda cuya foto se está viendo en grande (en la lista son muy pequeñas para juzgar).
  const [viewing, setViewing] = useState<Garment | null>(null);

  const load = () => {
    setFailed(false);
    api.tasteNext().then(setState).catch(() => setFailed(true));
  };
  useEffect(() => {
    load();
    api.catalog().then(setCatalog).catch(() => undefined);
  }, []);

  const combo = state?.combo;

  const send = (liked: boolean, save = false) => {
    if (!combo) return;
    setBusy(true);
    setSendError(false);
    setSaved(false);
    api
      .tasteRate({
        garment_ids: combo.garments.map((g) => g.id),
        liked,
        reasons: liked ? [] : reasons,
        culprit_ids: liked ? [] : culprits,
        save,
      })
      .then((next) => {
        setState(next);
        setSaved(save);
        setAsking(false);
        setReasons([]);
        setCulprits([]);
      })
      .catch(() => setSendError(true))
      .finally(() => setBusy(false));
  };

  const toggleReason = (r: string) =>
    setReasons((list) => (list.includes(r) ? list.filter((x) => x !== r) : [...list, r]));

  const hasShoes = combo?.garments.some((g) => g.category === "calzado");

  return (
    <>
      <MainHeader title={t.gustos.titulo} />
      <Screen>
        <div className="flex flex-col gap-5">
          <header className="flex flex-col gap-1">
            <span className="label-caps text-text-2">{t.gustos.etiqueta}</span>
            <p className="text-sm text-text-2">{t.gustos.intro}</p>
            {state && state.rated > 0 && (
              <p className="text-xs text-text-3">{t.gustos.progreso(state.rated, state.liked, state.remaining)}</p>
            )}
            {/* El hueco de esa línea mientras carga (lo normal es que ya haya valoraciones): así la
                tarjeta no baja al llegar. */}
            {!state && !failed && <Skeleton className="h-4 w-56 rounded-md" />}
          </header>

          {failed && (
            <div className="card flex flex-col items-center gap-3 p-6 text-center">
              <Icon name="error" className="text-danger" size={28} />
              <p className="text-sm text-text-2">{t.comun.errorRed}</p>
              <button type="button" onClick={load} className="min-h-11 px-3 text-sm font-semibold text-primary">
                {t.comun.reintentar}
              </button>
            </div>
          )}
          {!failed && !state && <OutfitSkeleton kind="gustos" />}

          {state && !combo && (
            <div className="card flex flex-col items-center gap-3 p-8 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-card-2 text-primary">
                <Icon name="check_circle" size={28} />
              </span>
              <h3 className="font-display text-xl font-semibold tracking-tight">
                {state.rated > 0 ? t.gustos.finTitulo : t.gustos.vacioTitulo}
              </h3>
              <p className="text-sm text-text-2">{state.rated > 0 ? t.gustos.finTexto : t.gustos.vacioTexto}</p>
              <Link
                to="/nueva"
                className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98]"
              >
                <Icon name="add_a_photo" size={20} />
                {t.armario.anadir}
              </Link>
            </div>
          )}

          {state && combo && (
            <>
              {/* La clave es la combinación: al valorar, la siguiente entra animada. */}
              <section
                key={combo.garments.map((g) => g.id).join("-")}
                className={`card flex animate-enter flex-col p-5 transition-opacity duration-300 ${busy ? "opacity-50" : ""}`}
              >
                <div className="flex items-center justify-between gap-2 pb-4">
                  <h3 className="font-display text-lg font-semibold">
                    {asking ? t.gustos.porQue : t.gustos.pregunta}
                  </h3>
                  <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-chip px-3 py-1 text-on-chip">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span className="label-caps">{t.hoy.afinidad(combo.affinity)}</span>
                  </span>
                </div>

                <div className="flex flex-col gap-3">
                  {combo.garments.map((g, i) => {
                    const marked = culprits.includes(g.id);
                    return (
                      <div
                        key={g.id}
                        style={stagger(i + 1, 70)}
                        className={`flex animate-enter items-center gap-3.5 rounded-2xl border p-2.5 transition-colors duration-200 ${
                          marked ? "border-danger bg-danger/10" : "border-line bg-card-2"
                        }`}
                      >
                        {/* La foto abre la ficha. El resto de la fila también, salvo mientras se señala la
                            prenda que no pega: entonces la marca. */}
                        <button
                          type="button"
                          aria-label={t.gustos.verFoto(g.name)}
                          onClick={() => setViewing(g)}
                          className="shrink-0 cursor-zoom-in active:opacity-80"
                        >
                          <FadeImg
                            src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                            alt=""
                            className="h-24 w-20 rounded-xl object-cover"
                          />
                        </button>
                        <button
                          type="button"
                          aria-pressed={asking ? marked : undefined}
                          onClick={() =>
                            asking
                              ? setCulprits((list) => (marked ? list.filter((id) => id !== g.id) : [...list, g.id]))
                              : setViewing(g)
                          }
                          className="min-w-0 flex-1 self-stretch text-left"
                        >
                          <span className="label-caps text-text-2">{catalog?.categories[g.category] ?? ""}</span>
                          <h4 className="truncate text-base font-medium">{g.name}</h4>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            <span className="flex items-center gap-1 rounded-full bg-control px-2 py-0.5 text-[11px] text-text-2">
                              <span
                                className="h-2 w-2 rounded-full border border-text/10"
                                style={{ background: g.color_primary.hex }}
                              />
                              {cap(g.color_primary.name)}
                            </span>
                            {marked && (
                              <span className="rounded-full bg-danger px-2 py-0.5 text-[11px] font-medium text-bg">
                                {t.gustos.estaNo}
                              </span>
                            )}
                          </div>
                        </button>
                      </div>
                    );
                  })}
                </div>

                {asking && (
                  <div className="mt-4 flex flex-col gap-2 border-t border-control pt-4">
                    <div className="flex flex-wrap gap-1.5">
                      {REASONS.filter((r) => r !== "calzado" || hasShoes).map((r) => (
                        <button
                          key={r}
                          type="button"
                          aria-pressed={reasons.includes(r)}
                          onClick={() => toggleReason(r)}
                          className={`min-h-10 rounded-full border px-3 py-2 text-xs font-medium ${
                            reasons.includes(r)
                              ? "border-primary bg-primary text-on-primary"
                              : "border-line bg-card-2 text-text-2"
                          }`}
                        >
                          {t.gustos.motivos[r]}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-text-3">{t.gustos.tocaPrenda}</p>
                  </div>
                )}
              </section>

              {sendError && (
                <p role="alert" className="-mt-2 text-center text-sm text-danger">
                  {t.comun.errorRed}
                </p>
              )}

              {asking ? (
                <section className="flex flex-col gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => send(false)}
                    className="flex h-12 items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
                  >
                    {reasons.length > 0 || culprits.length > 0 ? t.gustos.enviar : t.gustos.sinMotivo}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAsking(false);
                      setReasons([]);
                      setCulprits([]);
                      setSendError(false);
                    }}
                    className="h-11 text-xs font-medium text-text-2 underline"
                  >
                    {t.comun.cancelar}
                  </button>
                </section>
              ) : (
                <section className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setAsking(true)}
                    className="flex h-14 items-center justify-center gap-2 rounded-xl border border-line bg-control font-display text-[15px] font-semibold active:scale-[0.98] disabled:opacity-40"
                  >
                    <Icon name="close" size={22} className="text-text-2" />
                    {t.gustos.no}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => send(true)}
                    className="flex h-14 items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98] disabled:opacity-40"
                  >
                    <Icon name="favorite_fill" size={22} />
                    {t.gustos.si}
                  </button>
                  {/* Para los que se pondría: va a «Tus outfits» del Armario y cuenta el doble. */}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => send(true, true)}
                    className="col-span-2 flex h-12 items-center justify-center gap-2 rounded-xl border border-line bg-card text-sm font-semibold text-primary active:scale-[0.98] disabled:opacity-40"
                  >
                    <Icon name="bookmark_add" size={20} />
                    {t.gustos.guardar}
                  </button>
                  {saved && (
                    <p role="status" className="col-span-2 animate-enter text-center text-xs text-text-2">
                      {t.gustos.guardado}
                    </p>
                  )}
                </section>
              )}
            </>
          )}

          {/* Lo que va aprendiendo */}
          {state && (state.learned.likes.length > 0 || state.learned.dislikes.length > 0) && (
            <section className="flex flex-col gap-2 rounded-2xl border border-line bg-card-2 p-4">
              <span className="label-caps text-text-2">{t.gustos.aprendido}</span>
              {state.learned.likes.length > 0 && (
                <p className="text-xs">
                  <span className="font-semibold">{t.gustos.teGusta} </span>
                  {state.learned.likes.map(([a, b]) => t.gustos.pareja(a, b)).join(" · ")}
                </p>
              )}
              {state.learned.dislikes.length > 0 && (
                <p className="text-xs">
                  <span className="font-semibold">{t.gustos.noTeGusta} </span>
                  {state.learned.dislikes.map(([a, b]) => t.gustos.pareja(a, b)).join(" · ")}
                </p>
              )}
            </section>
          )}
        </div>
      </Screen>
      <BottomNav />
      {viewing && (
        <GarmentSheet
          garmentId={viewing.id}
          onClose={() => setViewing(null)}
          onDeleted={() => {
            setViewing(null);
            load();
          }}
        />
      )}
    </>
  );
}
