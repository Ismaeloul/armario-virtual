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

type Tab = { to: string; label: string; icon: IconName };

const LEFT: Tab[] = [
  { to: "/", label: t.nav.hoy, icon: "sunny" },
  { to: "/armario", label: t.nav.armario, icon: "styler" },
];
const RIGHT: Tab[] = [
  { to: "/gustos", label: t.nav.gustos, icon: "favorite" },
  { to: "/ajustes", label: t.nav.ajustes, icon: "tune" },
];

function TabLink({ tab }: { tab: Tab }) {
  return (
    <NavLink
      to={tab.to}
      end={tab.to === "/"}
      className={({ isActive }) =>
        `flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 ${
          isActive ? "font-semibold text-text" : "text-text-3"
        }`
      }
    >
      <Icon name={tab.icon} />
      <span className="text-[10px] tracking-wide">{tab.label}</span>
    </NavLink>
  );
}

/** Barra inferior: dos pestañas a cada lado y el "+" de añadir prenda en el centro. */
export function BottomNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 mx-auto max-w-md border-t border-line bg-bg/90 pb-safe backdrop-blur-xl">
      <div className="flex h-16 items-center">
        {LEFT.map((tab) => (
          <TabLink key={tab.to} tab={tab} />
        ))}
        <NavLink to="/nueva" aria-label={t.armario.anadir} className="flex flex-1 flex-col items-center justify-center">
          <span className="-mt-6 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-on-primary shadow-float active:scale-95">
            <Icon name="add" size={28} />
          </span>
          <span className="mt-0.5 text-[10px] tracking-wide text-text-3">{t.nav.anadir}</span>
        </NavLink>
        {RIGHT.map((tab) => (
          <TabLink key={tab.to} tab={tab} />
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
