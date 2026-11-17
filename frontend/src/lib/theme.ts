// Tema: Claro / Oscuro / Sistema. Se guarda en Ajustes (servidor) y en local
// para aplicarlo al arrancar sin parpadeo (ver index.html).
const KEY = "armario.tema";
const media = window.matchMedia("(prefers-color-scheme: dark)");

export function applyTheme(theme: string) {
  const dark = theme === "oscuro" || (theme === "sistema" && media.matches);
  document.documentElement.classList.toggle("dark", dark);
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#131315" : "#fbf8fc");
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* almacenamiento no disponible */
  }
}

export function storedTheme(): string {
  try {
    return localStorage.getItem(KEY) ?? "sistema";
  } catch {
    return "sistema";
  }
}

// Si el tema es "sistema", seguir los cambios del dispositivo.
media.addEventListener("change", () => {
  if (storedTheme() === "sistema") applyTheme("sistema");
});
