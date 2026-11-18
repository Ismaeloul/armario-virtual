/**
 * Copia un texto al portapapeles. Devuelve si se pudo.
 *
 * El portapapeles moderno solo existe en páginas seguras (https o localhost). En el Umbrel la app se
 * abre por http, así que ahí se copia a la antigua: con un campo de texto oculto y `execCommand`.
 * (La misma forma que el código de Codex en Ajustes.)
 */
export async function copyText(text: string): Promise<boolean> {
  const legacy = () => {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    // Dentro de un diálogo modal el foco no sale de él: el campo se cuelga del que esté abierto.
    const host = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]') ?? document.body;
    host.appendChild(field);
    field.select();
    field.setSelectionRange(0, text.length); // iOS no selecciona con select() a secas
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      field.remove();
    }
  };
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return legacy();
    }
  }
  return legacy();
}
