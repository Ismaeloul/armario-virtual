// Tema: Claro / Oscuro / Sistema. Se guarda en Ajustes (servidor) y en local
// para aplicarlo al arrancar sin parpadeo (ver index.html).
const KEY = "armario.tema";
const media = window.matchMedia("(prefers-color-scheme: dark)");

export function applyTheme(theme: string) {
  const dark = theme === "oscuro" || (theme === "sistema" && media.matches);
  const root = document.documentElement;
  const changed = root.classList.contains("dark") !== dark;
  root.classList.toggle("dark", dark);
  const color = dark ? "#131315" : "#fbf8fc";
  // Las bandas del iPhone (la de la hora y, en Safari, la de la dirección) se tiñen con el
  // theme-color o con el fondo de la página, y Safari no se entera si solo cambia una variable CSS
  // o el atributo de la etiqueta: hasta reabrir la app se quedaban del tema anterior. Por eso el
  // fondo se escribe directamente y la etiqueta se pone nueva en vez de retocarla.
  root.style.backgroundColor = color;
  document.body.style.backgroundColor = color;
  document.querySelector('meta[name="theme-color"]')?.remove();
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = color;
  document.head.appendChild(meta);
  if (changed) resample();
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* almacenamiento no disponible */
  }
}

/** Safari reciente saca el color de las bandas de lo que hay fijo arriba y abajo (la cabecera y la
 *  barra de pestañas) y solo lo mira cuando esos elementos aparecen: se quitan un fotograma y vuelven. */
function resample() {
  const fixed = [...document.querySelectorAll<HTMLElement>("header, nav")];
  requestAnimationFrame(() => {
    for (const el of fixed) el.style.display = "none";
    requestAnimationFrame(() => {
      for (const el of fixed) el.style.display = "";
    });
  });
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
