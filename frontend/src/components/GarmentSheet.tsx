import { t } from "../i18n/es";
import FichaPrenda from "../pages/FichaPrenda";
import { BottomSheet } from "./BottomSheet";

/**
 * La ficha completa de una prenda en una hoja que sube desde abajo, sobre el fondo difuminado: se mira
 * (fotos, detalles, lavadora, pareja…) sin salir del outfit o de la combinación de Gustos. Se cierra
 * deslizándola hacia abajo o tocando fuera.
 */
export function GarmentSheet({
  garmentId,
  onClose,
  onDeleted,
}: {
  garmentId: number;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  return (
    <BottomSheet label={t.ficha.cabecera} onClose={onClose}>
      <div className="px-5 pt-1">
        <FichaPrenda garmentId={garmentId} embedded onDeleted={onDeleted ?? onClose} />
      </div>
    </BottomSheet>
  );
}
