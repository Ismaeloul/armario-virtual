import "@fontsource-variable/inter";
import "@fontsource-variable/plus-jakarta-sans";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useEffect, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigationType } from "react-router-dom";
import { api } from "./lib/api";
import { applyTheme, storedTheme } from "./lib/theme";
import AnadirPrenda from "./pages/AnadirPrenda";
import Ajustes from "./pages/Ajustes";
import Armario from "./pages/Armario";
import TusOutfits from "./pages/TusOutfits";
import Compras from "./pages/Compras";
import EditarPrenda from "./pages/EditarPrenda";
import FichaPrenda from "./pages/FichaPrenda";
import Gustos from "./pages/Gustos";
import Hoy from "./pages/Hoy";
import "./theme/tokens.css";

// Tema: primero el guardado en local (instantáneo); luego el de Ajustes en el servidor.
applyTheme(storedTheme());
api.settings().then((s) => applyTheme(s.theme)).catch(() => undefined);

/**
 * Dónde queda el scroll al cambiar de pantalla. Al entrar en una pantalla nueva, arriba del todo (sin
 * esto se heredaba el scroll de la anterior: desde el final del Armario, la ficha salía ya bajada).
 * Al volver atrás, donde se estaba: se espera a que la lista haya cargado y sea lo bastante alta.
 */
function ScrollManager() {
  const location = useLocation();
  const type = useNavigationType();
  const saved = useRef(new Map<string, number>());
  const current = useRef(location.key);
  // Al cambiar de pantalla se apunta por dónde iba la que se deja. Se hace al pintar, antes de que
  // cambie la página: después el navegador ya ha recolocado el scroll y el dato no vale.
  if (current.current !== location.key) {
    saved.current.set(current.current, window.scrollY);
    current.current = location.key;
  }

  useEffect(() => {
    try {
      window.history.scrollRestoration = "manual";
    } catch {
      /* navegador sin esa opción */
    }
  }, []);

  useEffect(() => {
    const target = type === "POP" ? (saved.current.get(location.key) ?? 0) : 0;
    if (target === 0) {
      window.scrollTo(0, 0);
      return;
    }
    // La pantalla a la que se vuelve aún está cargando: se reintenta hasta que quepa (un par de segundos).
    let timer = 0;
    const started = performance.now();
    const tryScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (max >= target || performance.now() - started > 2500) {
        window.scrollTo(0, Math.min(target, Math.max(0, max)));
        return;
      }
      timer = window.setTimeout(tryScroll, 50);
    };
    tryScroll();
    return () => window.clearTimeout(timer);
  }, [location.key, type]);

  return null;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollManager />
      <Routes>
        <Route path="/" element={<Hoy />} />
        <Route path="/armario" element={<Armario />} />
        <Route path="/armario/lavadora" element={<Armario laundryOnly />} />
        <Route path="/armario/outfits" element={<TusOutfits />} />
        <Route path="/nueva" element={<AnadirPrenda />} />
        <Route path="/prenda/:id" element={<FichaPrenda />} />
        <Route path="/prenda/:id/editar" element={<EditarPrenda />} />
        <Route path="/gustos" element={<Gustos />} />
        <Route path="/compras" element={<Compras />} />
        <Route path="/ajustes" element={<Ajustes />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
