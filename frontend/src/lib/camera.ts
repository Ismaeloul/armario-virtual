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

/** Gira 90° a la derecha una foto aún sin subir. Si el navegador no puede leerla, la devuelve igual. */
export async function rotateFile(file: File): Promise<File> {
  try {
    const bitmap = await createImageBitmap(file); // respeta la orientación EXIF
    // Lado máximo 2400 px: el servidor la reduce a 1600 de todos modos y evita el límite de lienzo de iOS.
    const scale = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = h;
    canvas.height = w;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.translate(h, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}
