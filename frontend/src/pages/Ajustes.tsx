import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApishKey } from "../components/ApishKey";
import { CodexSession } from "../components/CodexSession";
import { ForgetTaste } from "../components/ForgetTaste";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Field, Segmented, Switch, inputClass } from "../components/Controls";
import { Icon, type IconName } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type AIStatus, type CodexModels, type Garment, type Settings } from "../lib/api";
import { applyTheme, storedTheme } from "../lib/theme";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <span className="label-caps px-1 text-text-3">{label}</span>
      <div className="card flex flex-col gap-3.5 p-4">{children}</div>
    </section>
  );
}

function Title({ icon, title, text, right }: { icon: IconName; title: string; text?: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-card-2 text-primary">
          <Icon name={icon} size={19} />
        </span>
        <div>
          <h2 className="font-display text-sm font-semibold leading-tight">{title}</h2>
          {text && <p className="text-xs text-text-2">{text}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

export default function Ajustes() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [theme, setTheme] = useState(storedTheme());
  const [city, setCity] = useState("");
  const [laundry, setLaundry] = useState<Garment[]>([]);
  const [ai, setAi] = useState<AIStatus | null>(null);
  const [models, setModels] = useState<CodexModels | null>(null);
  const [claudeKey, setClaudeKey] = useState("");
  const [keyError, setKeyError] = useState(false);
  // Ajuste cuyo último cambio no llegó al servidor (se muestra el aviso en su sección).
  const [failedKeys, setFailedKeys] = useState<(keyof Settings)[]>([]);
  const [confirmingLaundry, setConfirmingLaundry] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [laundryError, setLaundryError] = useState<string | null>(null);

  const loadAi = useCallback(() => {
    api.aiStatus().then(setAi).catch(() => undefined);
  }, []);
  const saveKey = (key: string) => {
    setKeyError(false);
    api
      .saveClaudeKey(key)
      .then(() => {
        setClaudeKey("");
        loadAi();
      })
      .catch(() => setKeyError(true));
  };

  useEffect(() => {
    api.codexModels().then(setModels).catch(() => undefined); // sin la lista no se enseña el selector
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setTheme(s.theme);
        setCity(s.city);
        applyTheme(s.theme);
      })
      .catch(() => undefined);
    loadAi();
    api
      .garments()
      .then((g) => setLaundry(g.filter((x) => x.in_laundry)))
      .catch(() => undefined);
  }, []);

  /**
   * Se pinta ya y se confirma con el servidor. De la respuesta solo se toman las claves enviadas, para
   * que la respuesta de un cambio no pise otro hecho justo después. Si falla, se deshace y se avisa.
   */
  const change = (changes: Partial<Settings>) => {
    const keys = Object.keys(changes) as (keyof Settings)[];
    const pick = (s: Settings) => Object.fromEntries(keys.map((k) => [k, s[k]])) as Partial<Settings>;
    const previous = settings ? pick(settings) : null;
    const previousTheme = theme;
    if (changes.theme) {
      setTheme(changes.theme);
      applyTheme(changes.theme); // inmediato, aunque el servidor tarde
    }
    setFailedKeys((list) => list.filter((k) => !keys.includes(k)));
    setSettings((s) => (s ? { ...s, ...changes } : s));
    api
      .updateSettings(changes)
      .then((saved) => setSettings((s) => (s ? { ...s, ...pick(saved) } : saved)))
      .catch(() => {
        if (previous) setSettings((s) => (s ? { ...s, ...previous } : s));
        if (changes.theme) {
          setTheme(previousTheme);
          applyTheme(previousTheme);
        }
        if (changes.city !== undefined && previous?.city !== undefined) setCity(previous.city);
        setFailedKeys((list) => [...list, ...keys]);
      });
  };
  const changeFailed = (...keys: (keyof Settings)[]) =>
    keys.some((k) => failedKeys.includes(k)) && (
      <p role="alert" className="px-0.5 text-[11px] text-danger">
        {t.comun.errorRed}
      </p>
    );

  const clearLaundry = () => {
    setClearing(true);
    setLaundryError(null);
    api
      .clearLaundry()
      .then(() => {
        setLaundry([]);
        setConfirmingLaundry(false);
      })
      .catch(() => setLaundryError(t.comun.errorRed))
      .finally(() => setClearing(false));
  };

  const notify = settings?.notify_enabled ?? true;

  return (
    <>
      <MainHeader title={t.ajustes.titulo} />
      <Screen>
        <div className="flex flex-col gap-6">
          <Section label={t.ajustes.apariencia}>
            <Title icon="contrast" title={t.ajustes.tema} />
            <Segmented
              value={theme}
              onChange={(v) => change({ theme: v })}
              options={["claro", "oscuro", "sistema"].map((value) => ({ value, label: t.temas[value] }))}
            />
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.temaTexto}</p>
            {changeFailed("theme")}
          </Section>

          <Section label={t.ajustes.temporada}>
            <Title icon="calendar" title={t.ajustes.temporadaTitulo} />
            <Segmented
              value={settings?.season_mode ?? "auto"}
              onChange={(v) => change({ season_mode: v })}
              options={["auto", "verano", "invierno"].map((value) => ({ value, label: t.ajustes.temporadas[value] }))}
            />
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.temporadaTexto}</p>
            {changeFailed("season_mode")}
          </Section>

          <Section label={t.ajustes.ia}>
            <Title icon="auto_awesome" title={t.ajustes.iaTitulo} />
            <Segmented
              value={settings?.ai_provider ?? "codex"}
              onChange={(v) => change({ ai_provider: v })}
              options={["codex", "claude"].map((value) => ({ value, label: t.proveedores[value] }))}
            />
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.iaTexto}</p>
            {changeFailed("ai_provider")}

            {ai && (
              <div className="flex flex-col gap-1.5 border-t border-control pt-3">
                {[
                  {
                    ok: ai.codex_logged_in,
                    text: !ai.codex_installed
                      ? t.ajustes.estado.codexNoInstalado
                      : ai.codex_logged_in
                        ? t.ajustes.estado.codexListo
                        : t.ajustes.estado.codexSinSesion,
                  },
                  {
                    ok: ai.claude_configured,
                    text: ai.claude_configured ? t.ajustes.estado.claudeListo : t.ajustes.estado.claudeFalta,
                  },
                ].map((row) => (
                  <p key={row.text} className="flex items-center gap-2 text-xs">
                    <Icon
                      name={row.ok ? "check_circle" : "error"}
                      size={16}
                      className={row.ok ? "text-primary" : "text-text-3"}
                    />
                    <span className={row.ok ? "text-text" : "text-text-2"}>{row.text}</span>
                  </p>
                ))}
              </div>
            )}

            {ai && <CodexSession ai={ai} onChange={loadAi} />}

            {models && models.models.length > 0 && (
              <div className="flex flex-col gap-2 border-t border-control pt-3">
                <div className="grid grid-cols-2 gap-2">
                  <Field label={t.ajustes.codexModelo}>
                    <select
                      className={inputClass}
                      value={settings?.codex_model ?? ""}
                      onChange={(e) => change({ codex_model: e.target.value })}
                    >
                      <option value="">{t.ajustes.codexAuto}</option>
                      {models.models.map((m) => (
                        <option key={m.slug} value={m.slug}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t.ajustes.codexEsfuerzo}>
                    <select
                      className={inputClass}
                      value={settings?.codex_effort ?? ""}
                      onChange={(e) => change({ codex_effort: e.target.value })}
                    >
                      <option value="">{t.ajustes.codexEsfuerzoAuto}</option>
                      {models.efforts.map((e) => (
                        <option key={e} value={e}>
                          {t.ajustes.codexEsfuerzos[e] ?? e}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.codexModeloTexto}</p>
                {changeFailed("codex_model", "codex_effort")}

                <div className="mt-1 grid grid-cols-2 gap-2">
                  <Field label={t.ajustes.codexTraducir}>
                    <select
                      className={inputClass}
                      value={settings?.codex_translate_model ?? ""}
                      onChange={(e) => change({ codex_translate_model: e.target.value })}
                    >
                      <option value="">{t.ajustes.codexAuto}</option>
                      {(models.translate_models ?? models.models).map((m) => (
                        <option key={m.slug} value={m.slug}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t.ajustes.codexEsfuerzo}>
                    <select
                      className={inputClass}
                      value={settings?.codex_translate_effort ?? "low"}
                      onChange={(e) => change({ codex_translate_effort: e.target.value })}
                    >
                      <option value="">{t.ajustes.codexEsfuerzoAuto}</option>
                      {models.efforts.map((e) => (
                        <option key={e} value={e}>
                          {t.ajustes.codexEsfuerzos[e] ?? e}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.codexTraducirTexto}</p>
                {changeFailed("codex_translate_model", "codex_translate_effort")}
              </div>
            )}

            <form
              className="flex flex-col gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (claudeKey.trim()) saveKey(claudeKey.trim());
              }}
            >
              <label htmlFor="clave-claude" className="label-caps text-text-2">
                {t.ajustes.claveEtiqueta}
              </label>
              <div className="flex gap-2">
                <input
                  id="clave-claude"
                  type="password"
                  autoComplete="off"
                  className={inputClass}
                  placeholder={t.ajustes.clavePlaceholder}
                  value={claudeKey}
                  onChange={(e) => setClaudeKey(e.target.value)}
                />
                <button
                  type="submit"
                  disabled={!claudeKey.trim()}
                  className="shrink-0 rounded-lg bg-primary px-4 text-xs font-semibold text-on-primary disabled:opacity-40"
                >
                  {t.ajustes.claveGuardar}
                </button>
              </div>
              <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.claveAyuda}</p>
              {keyError && (
                <p role="alert" className="px-0.5 text-[11px] text-danger">
                  {t.comun.errorRed}
                </p>
              )}
              {ai?.claude_configured && (
                <button
                  type="button"
                  onClick={() => saveKey("")}
                  className="-ml-2 inline-flex min-h-11 items-center self-start px-2 text-[11px] text-danger"
                >
                  {t.ajustes.claveBorrar}
                </button>
              )}
            </form>
          </Section>

          {settings?.apish && (
            <Section label={t.ajustes.apish.seccion}>
              <Title icon="store" title={t.ajustes.apish.titulo} text={t.ajustes.apish.texto} />
              <ApishKey
                status={settings.apish}
                onSaved={(saved) => setSettings((s) => (s ? { ...s, apish: saved.apish } : saved))}
              />
            </Section>
          )}

          <Section label={t.ajustes.lavadora}>
            <Title
              icon="laundry"
              title={t.ajustes.lavadoraTitulo}
              right={
                <span className="shrink-0 rounded-full bg-chip px-2.5 py-0.5 text-[11px] font-semibold text-on-chip">
                  {t.ajustes.nPrendas(laundry.length)}
                </span>
              }
            />
            {laundry.length === 0 ? (
              <p className="px-0.5 text-xs text-text-3">{t.ajustes.lavadoraVacia}</p>
            ) : (
              <>
                <div className="flex flex-col">
                  {laundry.map((g) => (
                    <Link key={g.id} to={`/prenda/${g.id}`} className="flex items-center gap-3 py-1.5">
                      <img
                        src={mediaUrl((g.photo_cover ?? g.photo_front).thumb_url)}
                        alt=""
                        className="h-11 w-11 shrink-0 rounded-xl border border-line object-cover"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-display text-xs font-semibold">{g.name}</p>
                        <p className="text-[11px] text-text-2">
                          {cap(g.type)} · {cap(g.color_primary.name)}
                        </p>
                      </div>
                      <Icon name="chevron_right" size={18} className="text-text-3" />
                    </Link>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setLaundryError(null);
                    setConfirmingLaundry(true);
                  }}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-chip px-4 py-2.5 font-display text-xs font-semibold text-on-chip active:scale-[0.99]"
                >
                  <Icon name="done_all" size={17} />
                  {t.ajustes.limpiar}
                </button>
              </>
            )}
          </Section>

          <Section label={t.ajustes.aviso}>
            <Title
              icon="notifications"
              title={t.ajustes.avisoTitulo}
              text={t.ajustes.avisoTexto}
              right={
                <Switch
                  checked={notify}
                  label={t.ajustes.avisoTitulo}
                  onChange={() => change({ notify_enabled: !notify })}
                />
              }
            />
            <label className="flex items-center justify-between gap-3 border-t border-control pt-3">
              <span className="text-xs font-medium">{t.ajustes.avisoHora}</span>
              <input
                type="time"
                value={settings?.notify_time ?? "07:30"}
                onChange={(e) => e.target.value && change({ notify_time: e.target.value })}
                className="min-h-10 rounded-full border border-line bg-card-2 px-3 py-1 font-display text-base font-semibold text-primary outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              />
            </label>
            {/* El aviso todavía no se envía (llega con la app de iPhone): que no parezca que ya funciona. */}
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.avisoAyuda}</p>
            {changeFailed("notify_enabled", "notify_time")}
          </Section>

          <Section label={t.ajustes.tiempo}>
            <Title icon="weather" title={t.ajustes.ciudad} />
            <div className="flex items-center gap-2">
              <Icon name="location" size={18} className="shrink-0 text-primary" />
              <input
                className={inputClass}
                aria-label={t.ajustes.ciudad}
                value={city}
                maxLength={80}
                onChange={(e) => setCity(e.target.value)}
                onBlur={() => city.trim() && city.trim() !== settings?.city && change({ city: city.trim() })}
              />
            </div>
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.ciudadAyuda}</p>
            {changeFailed("city")}
          </Section>

          <p className="text-center text-[11px] tracking-wider text-text-3">{t.ajustes.version}</p>
          <ForgetTaste />
        </div>
      </Screen>
      <BottomNav />
      <ConfirmDialog
        open={confirmingLaundry}
        title={t.ajustes.limpiarTitulo}
        text={t.ajustes.limpiarTexto(laundry.length)}
        confirmLabel={t.ajustes.limpiarBoton}
        destructive={false}
        busy={clearing}
        error={laundryError}
        onConfirm={clearLaundry}
        onCancel={() => setConfirmingLaundry(false)}
      />
    </>
  );
}
