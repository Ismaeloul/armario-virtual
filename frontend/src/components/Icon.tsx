// Iconos Tabler (línea de grosor 2) como SVG en línea: solo se empaquetan los que se usan y
// funcionan sin conexión (importante para la PWA y para Capacitor).
// Los nombres de la izquierda son los que usa la app; a la derecha, el archivo de Tabler.
// Única excepción: el armario, que Tabler no tiene. Es el de Iconoir con la línea a grosor 2,
// y su versión rellena está dibujada a mano (decisión del usuario, 18-11-2026).
import tune from "@tabler/icons/outline/adjustments-horizontal.svg?raw";
import error from "@tabler/icons/outline/alert-circle.svg?raw";
import notifications from "@tabler/icons/outline/bell.svg?raw";
import bookmark_add from "@tabler/icons/outline/bookmark.svg?raw";
import store from "@tabler/icons/outline/building-store.svg?raw";
import calendar from "@tabler/icons/outline/calendar.svg?raw";
import add_a_photo from "@tabler/icons/outline/camera-plus.svg?raw";
import photo_camera from "@tabler/icons/outline/camera.svg?raw";
import done_all from "@tabler/icons/outline/checks.svg?raw";
import arrow_back from "@tabler/icons/outline/chevron-left.svg?raw";
import chevron_right from "@tabler/icons/outline/chevron-right.svg?raw";
import check_circle from "@tabler/icons/outline/circle-check.svg?raw";
import schedule from "@tabler/icons/outline/clock.svg?raw";
import rain from "@tabler/icons/outline/cloud-rain.svg?raw";
import cloud from "@tabler/icons/outline/cloud.svg?raw";
import style from "@tabler/icons/outline/color-swatch.svg?raw";
import contrast from "@tabler/icons/outline/contrast.svg?raw";
import open_in_new from "@tabler/icons/outline/external-link.svg?raw";
import weather from "@tabler/icons/outline/haze.svg?raw"; // Tabler no tiene «sol con nube»
import favorite from "@tabler/icons/outline/heart.svg?raw";
import history from "@tabler/icons/outline/history.svg?raw";
import location from "@tabler/icons/outline/map-pin.svg?raw";
import palette from "@tabler/icons/outline/palette.svg?raw";
import edit from "@tabler/icons/outline/pencil.svg?raw";
import add from "@tabler/icons/outline/plus.svg?raw";
import refresh from "@tabler/icons/outline/refresh.svg?raw";
import repeat from "@tabler/icons/outline/repeat.svg?raw";
import rotate from "@tabler/icons/outline/rotate-clockwise.svg?raw";
import search from "@tabler/icons/outline/search.svg?raw";
import styler from "@tabler/icons/outline/shirt.svg?raw";
import cart from "@tabler/icons/outline/shopping-cart.svg?raw";
import snow from "@tabler/icons/outline/snowflake.svg?raw";
import auto_awesome from "@tabler/icons/outline/sparkles.svg?raw";
import sunny from "@tabler/icons/outline/sun.svg?raw";
import sell from "@tabler/icons/outline/tag.svg?raw";
import texture from "@tabler/icons/outline/texture.svg?raw";
import delete_icon from "@tabler/icons/outline/trash.svg?raw";
import laundry from "@tabler/icons/outline/wash-machine.svg?raw";
import close from "@tabler/icons/outline/x.svg?raw";
import tune_fill from "@tabler/icons/filled/adjustments-horizontal.svg?raw";
import favorite_fill from "@tabler/icons/filled/heart.svg?raw";
import cart_fill from "@tabler/icons/filled/shopping-cart.svg?raw";
import sunny_fill from "@tabler/icons/filled/sun.svg?raw";

const checkroom =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M9 14H8"/><path d="M16 14H15"/>' +
  '<path d="M12 2H20.4C20.7314 2 21 2.26863 21 2.6V21.4C21 21.7314 20.7314 22 20.4 22H12M12 2H3.6C3.26863 2 3 2.26863 3 2.6V21.4C3 21.7314 3.26863 22 3.6 22H12M12 2V22"/></svg>';

const checkroom_fill =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd">' +
  '<path d="M3.2 1H11.3V23H3.2A1.2 1.2 0 0 1 2 21.8V2.2A1.2 1.2 0 0 1 3.2 1ZM8 13H9A1 1 0 0 1 9 15H8A1 1 0 0 1 8 13Z"/>' +
  '<path d="M12.7 1H20.8A1.2 1.2 0 0 1 22 2.2V21.8A1.2 1.2 0 0 1 20.8 23H12.7ZM15 13H16A1 1 0 0 1 16 15H15A1 1 0 0 1 15 13Z"/></svg>';

const ICONS = {
  add,
  add_a_photo,
  arrow_back,
  auto_awesome,
  bookmark_add,
  calendar,
  cart,
  cart_fill,
  check_circle,
  checkroom,
  checkroom_fill,
  chevron_right,
  close,
  cloud,
  contrast,
  delete_icon,
  done_all,
  edit,
  error,
  favorite,
  favorite_fill,
  history,
  laundry,
  location,
  notifications,
  open_in_new,
  palette,
  photo_camera,
  rain,
  refresh,
  repeat,
  rotate,
  schedule,
  search,
  sell,
  snow,
  store,
  style,
  styler,
  sunny,
  sunny_fill,
  texture,
  tune,
  tune_fill,
  weather,
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
