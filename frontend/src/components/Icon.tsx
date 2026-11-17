// Iconos Material Symbols como SVG en línea: solo se empaquetan los que se usan
// y funcionan sin conexión (importante para la PWA y para Capacitor).
import add from "@material-symbols/svg-400/outlined/add.svg?raw";
import calendar from "@material-symbols/svg-400/outlined/calendar_month.svg?raw";
import delete_icon from "@material-symbols/svg-400/outlined/delete.svg?raw";
import done_all from "@material-symbols/svg-400/outlined/done_all.svg?raw";
import edit from "@material-symbols/svg-400/outlined/edit.svg?raw";
import favorite from "@material-symbols/svg-400/outlined/favorite.svg?raw";
import favorite_fill from "@material-symbols/svg-400/outlined/favorite-fill.svg?raw";
import history from "@material-symbols/svg-400/outlined/history.svg?raw";
import location from "@material-symbols/svg-400/outlined/location_on.svg?raw";
import notifications from "@material-symbols/svg-400/outlined/notifications.svg?raw";
import palette from "@material-symbols/svg-400/outlined/palette.svg?raw";
import rotate from "@material-symbols/svg-400/outlined/rotate_right.svg?raw";
import repeat from "@material-symbols/svg-400/outlined/repeat.svg?raw";
import sell from "@material-symbols/svg-400/outlined/sell.svg?raw";
import style from "@material-symbols/svg-400/outlined/style.svg?raw";
import texture from "@material-symbols/svg-400/outlined/texture.svg?raw";
import weather from "@material-symbols/svg-400/outlined/partly_cloudy_day.svg?raw";
import add_a_photo from "@material-symbols/svg-400/outlined/add_a_photo.svg?raw";
import arrow_back from "@material-symbols/svg-400/outlined/arrow_back_ios_new.svg?raw";
import bookmark_add from "@material-symbols/svg-400/outlined/bookmark_add.svg?raw";
import check_circle from "@material-symbols/svg-400/outlined/check_circle.svg?raw";
import checkroom from "@material-symbols/svg-400/outlined/checkroom.svg?raw";
import chevron_right from "@material-symbols/svg-400/outlined/chevron_right.svg?raw";
import contrast from "@material-symbols/svg-400/outlined/contrast.svg?raw";
import error from "@material-symbols/svg-400/outlined/error.svg?raw";
import laundry from "@material-symbols/svg-400/outlined/local_laundry_service.svg?raw";
import photo_camera from "@material-symbols/svg-400/outlined/photo_camera.svg?raw";
import refresh from "@material-symbols/svg-400/outlined/refresh.svg?raw";
import styler from "@material-symbols/svg-400/outlined/styler.svg?raw";
import sunny from "@material-symbols/svg-400/outlined/sunny.svg?raw";
import tune from "@material-symbols/svg-400/outlined/tune.svg?raw";

// El paquete no trae "auto_awesome": destello propio para todo lo relacionado con la IA.
const auto_awesome =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M10 3l1.9 5.1L17 10l-5.1 1.9L10 17l-1.9-5.1L3 10l5.1-1.9z"/>' +
  '<path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z"/></svg>';

const ICONS = {
  calendar,
  delete_icon,
  done_all,
  edit,
  favorite,
  favorite_fill,
  history,
  location,
  notifications,
  palette,
  repeat,
  rotate,
  sell,
  style,
  texture,
  weather,
  add,
  add_a_photo,
  arrow_back,
  auto_awesome,
  bookmark_add,
  check_circle,
  checkroom,
  chevron_right,
  contrast,
  error,
  laundry,
  photo_camera,
  refresh,
  styler,
  sunny,
  tune,
};

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 24, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`icon inline-flex shrink-0 ${className}`}
      style={{ fontSize: size }}
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  );
}
