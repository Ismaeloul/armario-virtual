// Captura de foto. Hoy usa el selector del navegador (en el móvil abre la cámara);
// al empaquetar con Capacitor se sustituye esta función por su plugin de cámara
// sin tocar las pantallas.
export function pickPhoto(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*"; // sin "capture": el móvil deja elegir entre cámara y galería
    input.style.display = "none";
    input.onchange = () => {
      resolve(input.files?.[0] ?? null);
      input.remove();
    };
    // Si se cierra el selector sin elegir, algunos navegadores disparan "cancel".
    input.addEventListener("cancel", () => {
      resolve(null);
      input.remove();
    });
    document.body.appendChild(input);
    input.click();
  });
}
