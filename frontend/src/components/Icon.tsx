// Iconos Phosphor (trazo fino y redondeado) como SVG en línea: solo se empaquetan los que
// se usan y funcionan sin conexión (importante para la PWA y para Capacitor).
// Los nombres de la izquierda son los que usa la app; a la derecha, el archivo de Phosphor.
import auto_awesome from "@phosphor-icons/core/assets/regular/sparkle.svg?raw";
import refresh from "@phosphor-icons/core/assets/regular/arrows-clockwise.svg?raw";
import rotate from "@phosphor-icons/core/assets/regular/arrow-clockwise.svg?raw";
import notifications from "@phosphor-icons/core/assets/regular/bell.svg?raw";
import bookmark_add from "@phosphor-icons/core/assets/regular/bookmark-simple.svg?raw";
import calendar from "@phosphor-icons/core/assets/regular/calendar-blank.svg?raw";
import add_a_photo from "@phosphor-icons/core/assets/regular/camera-plus.svg?raw";
import photo_camera from "@phosphor-icons/core/assets/regular/camera.svg?raw";
import arrow_back from "@phosphor-icons/core/assets/regular/caret-left.svg?raw";
import chevron_right from "@phosphor-icons/core/assets/regular/caret-right.svg?raw";
import check_circle from "@phosphor-icons/core/assets/regular/check-circle.svg?raw";
import done_all from "@phosphor-icons/core/assets/regular/checks.svg?raw";
import contrast from "@phosphor-icons/core/assets/regular/circle-half.svg?raw";
import history from "@phosphor-icons/core/assets/regular/clock-counter-clockwise.svg?raw";
import rain from "@phosphor-icons/core/assets/regular/cloud-rain.svg?raw";
import weather from "@phosphor-icons/core/assets/regular/cloud-sun.svg?raw";
import cloud from "@phosphor-icons/core/assets/regular/cloud.svg?raw";
import checkroom from "@phosphor-icons/core/assets/regular/coat-hanger.svg?raw";
import texture from "@phosphor-icons/core/assets/regular/grid-four.svg?raw";
import favorite from "@phosphor-icons/core/assets/regular/heart.svg?raw";
import location from "@phosphor-icons/core/assets/regular/map-pin.svg?raw";
import palette from "@phosphor-icons/core/assets/regular/palette.svg?raw";
import edit from "@phosphor-icons/core/assets/regular/pencil-simple.svg?raw";
import add from "@phosphor-icons/core/assets/regular/plus.svg?raw";
import repeat from "@phosphor-icons/core/assets/regular/repeat.svg?raw";
import tune from "@phosphor-icons/core/assets/regular/sliders-horizontal.svg?raw";
import snow from "@phosphor-icons/core/assets/regular/snowflake.svg?raw";
import sunny from "@phosphor-icons/core/assets/regular/sun.svg?raw";
import style from "@phosphor-icons/core/assets/regular/swatches.svg?raw";
import styler from "@phosphor-icons/core/assets/regular/t-shirt.svg?raw";
import sell from "@phosphor-icons/core/assets/regular/tag.svg?raw";
import delete_icon from "@phosphor-icons/core/assets/regular/trash.svg?raw";
import error from "@phosphor-icons/core/assets/regular/warning-circle.svg?raw";
import laundry from "@phosphor-icons/core/assets/regular/washing-machine.svg?raw";
import close from "@phosphor-icons/core/assets/regular/x.svg?raw";
import favorite_fill from "@phosphor-icons/core/assets/fill/heart-fill.svg?raw";

const ICONS = {
  add,
  add_a_photo,
  arrow_back,
  auto_awesome,
  bookmark_add,
  calendar,
  check_circle,
  checkroom,
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
  palette,
  photo_camera,
  rain,
  refresh,
  repeat,
  rotate,
  sell,
  snow,
  style,
  styler,
  sunny,
  texture,
  tune,
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
