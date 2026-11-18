/**
 * La dirección con la que abrir una página de fuera (la de una tienda).
 *
 * Cuando la app está añadida a la pantalla de inicio del iPhone no tiene pestañas: un enlace normal,
 * aunque lleve target="_blank", se abre encima de la app en un navegador incrustado. Con el esquema
 * `x-safari-https://` (iOS 17 o posterior) el enlace se manda a Safari de verdad y la app se queda como
 * estaba. En cualquier otro caso se devuelve la dirección tal cual y `target="_blank"` abre otra pestaña.
 */
export function externalHref(url: string): string {
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  if (standalone && /^https?:\/\//.test(url)) return `x-safari-${url}`;
  return url;
}

/**
 * Qué foto toca al pulsar sobre la actual, como en las historias: el tercio izquierdo vuelve a la
 * anterior y el resto pasa a la siguiente. Da la vuelta al llegar a un extremo.
 */
export function photoAfterTap(clientX: number, box: DOMRect, current: number, total: number): number {
  if (total < 2) return current;
  const back = clientX - box.left < box.width / 3;
  return (current + (back ? total - 1 : 1)) % total;
}
