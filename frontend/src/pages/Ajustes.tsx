import { useEffect, useState } from "react";
import { Segmented } from "../components/Controls";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { t } from "../i18n/es";
import { api, type Settings } from "../lib/api";
import { applyTheme, storedTheme } from "../lib/theme";

// Fase 1: tema y proveedor de IA. Aviso diario, ciudad y lavadora llegan después.
export default function Ajustes() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [theme, setTheme] = useState(storedTheme());

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setTheme(s.theme);
        applyTheme(s.theme);
      })
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

  return (
    <>
      <MainHeader title={t.ajustes.titulo} />
      <Screen>
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-2">
            <span className="label-caps px-1 text-text-3">{t.ajustes.apariencia}</span>
            <div className="card flex flex-col gap-3.5 p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-card-2 text-primary">
                  <Icon name="contrast" size={19} />
                </span>
                <h2 className="font-display text-sm font-semibold">{t.ajustes.tema}</h2>
              </div>
              <Segmented
                value={theme}
                onChange={(v) => change({ theme: v })}
                options={["claro", "oscuro", "sistema"].map((value) => ({ value, label: t.temas[value] }))}
              />
              <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.temaTexto}</p>
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <span className="label-caps px-1 text-text-3">{t.ajustes.ia}</span>
            <div className="card flex flex-col gap-3.5 p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-card-2 text-primary">
                  <Icon name="auto_awesome" size={19} />
                </span>
                <h2 className="font-display text-sm font-semibold">{t.ajustes.iaTitulo}</h2>
              </div>
              <Segmented
                value={settings?.ai_provider ?? "codex"}
                onChange={(v) => change({ ai_provider: v })}
                options={["codex", "claude"].map((value) => ({ value, label: t.proveedores[value] }))}
              />
              <p className="px-0.5 text-[11px] text-text-3">{t.ajustes.iaTexto}</p>
            </div>
          </section>

          <p className="text-center text-[11px] tracking-wider text-text-3">{t.ajustes.version}</p>
        </div>
      </Screen>
      <BottomNav />
    </>
  );
}
