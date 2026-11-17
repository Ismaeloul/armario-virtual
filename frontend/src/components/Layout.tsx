import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { t } from "../i18n/es";
import { Icon, type IconName } from "./Icon";

/** Cabecera de pantalla principal: percha + "Armario" (Hoy y Armario) o solo el título (Ajustes). */
export function MainHeader({ title, brand = false }: { title: string; brand?: boolean }) {
  return (
    <header className="fixed inset-x-0 top-0 z-40 mx-auto max-w-md border-b border-line bg-bg/85 pt-safe backdrop-blur-xl">
      <div className="flex h-14 items-center gap-2 px-5">
        {brand && <Icon name="checkroom" className="text-primary" />}
        <h1 className="font-display text-lg font-semibold tracking-tight">{title}</h1>
      </div>
    </header>
  );
}

/** Cabecera de pantalla secundaria: flecha atrás + nombre de pantalla. */
export function BackHeader({ title }: { title: string }) {
  const navigate = useNavigate();
  return (
    <header className="fixed inset-x-0 top-0 z-40 mx-auto max-w-md border-b border-line bg-bg/85 pt-safe backdrop-blur-xl">
      <div className="flex h-14 items-center gap-1 px-3">
        <button
          type="button"
          aria-label={t.comun.volver}
          onClick={() => navigate(-1)}
          className="flex h-11 w-11 items-center justify-center active:opacity-60"
        >
          <Icon name="arrow_back" size={22} />
        </button>
        <h1 className="font-display text-lg font-semibold tracking-tight">{title}</h1>
      </div>
    </header>
  );
}

const TABS: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: t.nav.hoy, icon: "sunny" },
  { to: "/armario", label: t.nav.armario, icon: "styler" },
  { to: "/ajustes", label: t.nav.ajustes, icon: "tune" },
];

/** Barra inferior con tres pestañas: Hoy, Armario, Ajustes. */
export function BottomNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 mx-auto max-w-md border-t border-line bg-bg/90 pb-safe backdrop-blur-xl">
      <div className="flex h-16 items-center justify-around">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) =>
              `flex min-h-11 min-w-16 flex-col items-center justify-center gap-0.5 ${
                isActive ? "font-semibold text-text" : "text-text-3"
              }`
            }
          >
            <Icon name={tab.icon} />
            <span className="text-[10px] tracking-wide">{tab.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

/** Marco de pantalla: columna de ancho móvil, con hueco para cabecera y barra inferior. */
export function Screen({ children, withNav = true }: { children: ReactNode; withNav?: boolean }) {
  return (
    <div className="mx-auto min-h-full max-w-md">
      <main
        className="px-5"
        style={{
          paddingTop: "calc(env(safe-area-inset-top, 0px) + 4.5rem)",
          paddingBottom: `calc(env(safe-area-inset-bottom, 0px) + ${withNav ? "6.5rem" : "2rem"})`,
        }}
      >
        {children}
      </main>
    </div>
  );
}
