import "@fontsource-variable/inter";
import "@fontsource-variable/plus-jakarta-sans";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
import { applyTheme, storedTheme } from "./lib/theme";
import AnadirPrenda from "./pages/AnadirPrenda";
import Ajustes from "./pages/Ajustes";
import Armario from "./pages/Armario";
import Compras from "./pages/Compras";
import EditarPrenda from "./pages/EditarPrenda";
import FichaPrenda from "./pages/FichaPrenda";
import Gustos from "./pages/Gustos";
import Hoy from "./pages/Hoy";
import "./theme/tokens.css";

// Tema: primero el guardado en local (instantáneo); luego el de Ajustes en el servidor.
applyTheme(storedTheme());
api.settings().then((s) => applyTheme(s.theme)).catch(() => undefined);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Hoy />} />
        <Route path="/armario" element={<Armario />} />
        <Route path="/armario/lavadora" element={<Armario laundryOnly />} />
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
