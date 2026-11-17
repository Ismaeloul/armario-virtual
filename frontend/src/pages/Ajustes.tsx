import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Segmented, inputClass } from "../components/Controls";
import { Icon, type IconName } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { cap, t } from "../i18n/es";
import { api, mediaUrl, type Garment, type Settings } from "../lib/api";
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

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setTheme(s.theme);
        setCity(s.city);
        applyTheme(s.theme);
      })
      .catch(() => undefined);
    api
      .garments()
      .then((g) => setLaundry(g.filter((x) => x.in_laundry)))
      .catch(() => undefined);
  }, []);

  const change = (changes: Partial<Settings>) => {
    if (changes.theme) {
      setTheme(changes.theme);
      applyTheme(changes.theme); // inmediato, aunque el servidor tarde
    }
    setSettings((s) => (s ? { ...s, ...changes } : s));
    api.updateSettings(changes).then(setSettings).catch(() => undefined);
  };

  const clearLaundry = () => {
    setLaundry([]);
    api.clearLaundry().catch(() => undefined);
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
          </Section>

          <Section label={t.ajustes.ia}>
            <Title icon="auto_awesome" title={t.ajustes.iaTitulo} />
            <Segmented
              value={settings?.ai_provider ?? "codex"}
              onChange={(v) => change({ ai_provider: v })}
              options={["codex", "claude"].map((value) => ({ value, label: t.proveedores[value] }))}
            />
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.iaTexto}</p>
          </Section>

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
                        src={mediaUrl(g.photo_front.thumb_url)}
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
                  onClick={clearLaundry}
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
                <button
                  type="button"
                  role="switch"
                  aria-checked={notify}
                  aria-label={t.ajustes.avisoTitulo}
                  onClick={() => change({ notify_enabled: !notify })}
                  className={`flex h-7 w-12 shrink-0 items-center rounded-full p-0.5 transition-colors ${
                    notify ? "justify-end bg-primary" : "justify-start bg-control"
                  }`}
                >
                  <span className="h-6 w-6 rounded-full bg-white shadow" />
                </button>
              }
            />
            <label className="flex items-center justify-between gap-3 border-t border-control pt-3">
              <span className="text-xs font-medium">{t.ajustes.avisoHora}</span>
              <input
                type="time"
                value={settings?.notify_time ?? "07:30"}
                onChange={(e) => e.target.value && change({ notify_time: e.target.value })}
                className="rounded-full border border-line bg-card-2 px-3 py-1 font-display text-xs font-semibold text-primary outline-none"
              />
            </label>
          </Section>

          <Section label={t.ajustes.tiempo}>
            <Title icon="weather" title={t.ajustes.ciudad} />
            <div className="flex items-center gap-2">
              <Icon name="location" size={18} className="shrink-0 text-primary" />
              <input
                className={inputClass}
                value={city}
                maxLength={80}
                onChange={(e) => setCity(e.target.value)}
                onBlur={() => city.trim() && city.trim() !== settings?.city && change({ city: city.trim() })}
              />
            </div>
            <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.proximamente}</p>
          </Section>

          <p className="text-center text-[11px] tracking-wider text-text-3">{t.ajustes.version}</p>
        </div>
      </Screen>
      <BottomNav />
    </>
  );
}
