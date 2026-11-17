import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { BottomNav, MainHeader, Screen } from "../components/Layout";
import { t } from "../i18n/es";

// Fase 1: estado provisional. El outfit del día llega en la Fase 2.
export default function Hoy() {
  return (
    <>
      <MainHeader title={t.app} brand />
      <Screen>
        <div className="card mt-10 flex flex-col items-center gap-3 p-8 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-card-2 text-primary">
            <Icon name="auto_awesome" size={28} />
          </div>
          <h2 className="font-display text-xl font-semibold tracking-tight">{t.hoy.titulo}</h2>
          <p className="text-sm text-text-2">{t.hoy.texto}</p>
          <Link
            to="/armario"
            className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-display text-[15px] font-semibold text-on-primary active:scale-[0.98]"
          >
            <Icon name="styler" size={20} />
            {t.hoy.irArmario}
          </Link>
        </div>
      </Screen>
      <BottomNav />
    </>
  );
}
