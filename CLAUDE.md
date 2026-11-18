# Armario virtual

App personal de armario virtual: catalogar prendas con foto, analizarlas con IA y recibir un outfit diario.
Un solo usuario y un solo armario, desplegada en casa sobre Umbrel.

## Estado

- Diseño cerrado. Stitch queda solo como referencia visual; no se le mandan más cambios.
- **En `main`, sin publicar: Fase 4, Compras (18-11-2026).** Pestaña «Compras» (quinta pestaña, carrito)
  con «Descubrir» (tarjetas tipo Tinder, deslizar o botones), «Me gustan» y el panel «Tiendas» (estado de
  cada tienda: funciona / falló / sin consultar, error en claro, próxima consulta, «Consultar ahora» y
  categorías). Conector por tienda en `services/shops/` (solo Zara), lógica en `services/shopping.py`, API
  en `routers/shop.py`, tabla `shop_items`. Zara se lee SIN navegador y SIN IA (comprobado desde el PC y
  desde el Umbrel): tipo, color y estampado se estiman por el nombre; Codex solo analiza al marcar «La he
  comprado». Cada tienda se consulta un día fijo a la semana, el siguiente a sus novedades (Zara: viernes,
  porque saca novedades los jueves según la prensa; no es dato oficial). Una tanda completa real: 1.220
  productos vistos, 40 propuestas, 116 s. Lo descartado o caducado no se vuelve a proponer; los «me gusta»
  caducan a los 30 días o si se agotan. La tienda arranca desactivada. Sin probar: «La he comprado» con
  Codex real, el bucle semanal en un proceso largo, nada en el Umbrel, modo oscuro.
  Rehecho el mismo día tras probarlo el usuario (salían piezas llamativas: cropped, culotte, colores que no
  lleva; todo era de Zara Hombre, el fallo era premiar «lo que no tienes»). Decidido con él: primero sus
  gustos (lo que acepta y descarta por tipo, color, palabras del nombre y precio, medido respecto a lo que
  acepta en general) y parecerse a lo que lleva; los huecos del armario, solo desempate. «Ver más» al
  acabar la tanda (el catálogo entero se guarda como candidatos sin fotos). Tiendas mezcladas en una lista
  con filtros por tienda y por tipo de prenda (no separar por tienda). «Volver» deshace decisiones. Motivo
  opcional al descartar. El precio NO cuenta ni sale como motivo (el usuario no quiere). La temporada se lee también de la descripción. Codex NO analiza las finalistas.
  Pendiente: tiendas de zapatillas (JD Sports respondió sin navegador; Foot Locker muestra captcha y no se
  va a saltar; Courir, Pull&Bear y Bershka sin mirar a fondo).
- **En `main`, sin publicar: modelo y esfuerzo de Codex en Ajustes (18-11-2026).** La lista de modelos se
  lee de `models_cache.json` de la carpeta de Codex (`services/ai/codex_models.py`); vacío = el de Codex
  por defecto. Esfuerzo: bajo, medio o alto. Cada prenda guarda con qué modelo se analizó (`ai_model`).
  Probado con un análisis real (gpt-6.2-astra · medium, 20 s frente a ~12 s por defecto).
- **Barrido de pulido (18-11-2026, publicado en la 0.3.2):** 53 fallos e incoherencias corregidos por
  agentes (confirmaciones con `ConfirmDialog` propio en vez de `window.confirm`, errores que se tragaban,
  campos a 16 px para que iOS no haga zoom, timeouts de Codex, fotos compartidas, fecha de «hoy» en
  hora de `ARMARIO_TZ`, por defecto Europe/Paris). El algoritmo se reescribió: reglas y gustos se
  promedian por pareja, las reglas generales pierden peso según el usuario valora eso mismo, la afinidad
  es la misma en Hoy y Gustos y ya no es solo orientativa, «Pasar» cuenta como media valoración, y hay
  una simulación en `tests/test_simulacion.py`. Sin probar en el Umbrel con datos reales.
- **Publicada en el Umbrel: 0.3.2** (18-11-2026: barrido de pulido, ver abajo; antes 0.3.1, 17-11-2026; la 0.3.0 más el arreglo de copiar el código de Codex por http): incluye todo lo que abajo figura
  como «en `main`, sin publicar» (Fase 2, Gustos, calzado, reglas de estilo, palabras clave). A partir de
  ahora se publica una versión por fase. El usuario va a fotografiar su ropa real en el Umbrel y a
  entrenar ahí el algoritmo; lo de la copia local es todo ropa de prueba (Vinted y Zara), nada es suyo.
- **Publicada en el Umbrel: 0.2.0** (17-11-2026), como app de la tienda propia (`Ismaeloul/umbrel-app-store`,
  carpeta `ismaeloul-armario`, puerto 7798, detrás del login de Umbrel). Incluye toda la Fase 1 más: sesión
  y límite de Codex desde Ajustes, foto de etiqueta, aviso de dudas en el color y reglas afinadas de la IA.
- **En `main`, sin publicar: Fase 2 (outfit del día).** Tiempo de la ciudad con Open-Meteo
  (`services/weather.py`), propuesta por reglas sin IA (`services/outfits.py`), tabla `outfits` con el estado
  de cada propuesta, y pantalla Hoy con «Pasar», «Me gusta» (apunta el uso de cada prenda, se puede
  deshacer) y «Generar otra propuesta». No propone prendas en la lavadora ni repite combinaciones.
- **En `main`, sin publicar: pestaña Gustos (inicio de la Fase 3).** Se valoran combinaciones (me gusta /
  no me gusta con varios motivos a la vez: colores, calzado, estilo, soso, recargado, y señalando una o
  varias prendas) y
  `services/taste.py` aprende parejas de prendas, de colores y de estilos; lo aprendido ajusta el outfit
  de Hoy y la afinidad. No se distingue quién valora (decisión del usuario: al algoritmo solo le importa
  si pega o no). El usuario entrena en local con datos de prueba para ver cómo se comporta: la copia
  local (`data/`) tiene 25 prendas de Vinted analizadas por Codex además de las suyas; no son su armario
  real. Gustos enseña antes las combinaciones que no mezclan verano con invierno. En Ajustes, escondido
  tras «Opciones avanzadas», está «Borrar lo aprendido» (doble toque para confirmar).
- **En `main`, sin publicar: reglas generales de estilo** (`services/style_rules.py` + `style_rules.json`,
  17-11-2026). Punto de partida del algoritmo antes de conocer los gustos: parejas de colores, estilos,
  estampados y tipos, y qué capa va sobre qué, sacadas de guías de moda (búsqueda corta con Haiku: 12
  búsquedas, muchas notas inferidas; se puede ampliar). Pesan poco a propósito: lo valorado en Gustos manda.
  Regla del usuario: cazadora o sobrecamisa sobre sudadera con cremallera no se propone (la cremallera se
  detecta con la palabra clave `closure`; si la prenda aún no la tiene, por la palabra en el texto).
  Ampliadas el mismo día (32 búsquedas): 171 parejas de colores, 94 de ellas sin fuente y en neutro.
- **En `main`, sin publicar: palabras clave de la prenda** (17-11-2026): `closure` (sin cierre, botones,
  media cremallera, cremallera), `hood`, `fit` (ajustado, normal, ancho) y `thickness` (fino, medio,
  grueso). Listas cerradas en `catalog.py`; las rellena la IA, se editan en el formulario y salen en la
  Ficha como «Rasgos». El calzado no las lleva. Las prendas anteriores las tienen vacías hasta
  reanalizarlas: al publicar habrá que hacerlo con las del Umbrel (en local ya está hecho).
- **Ropa de verano solo del 1 de mayo al 30 de septiembre** (decisión del usuario, 17-11-2026): fuera de
  esos meses Hoy no propone pantalón corto, manga corta ni nada de temporada Verano aunque suba la
  temperatura. Camisetas y polos cuentan como manga corta salvo que digan «manga larga».
- También sin publicar: al añadir se elige "Prenda de ropa" o "Zapatilla". El calzado tiene vistas
  propias (lateral, de frente, otro lateral) y una cuarta foto `photo_extra`.
- Versiones: no publicar en el Umbrel cambio a cambio. Se acumulan mejoras y arreglos en `main` y se publica
  una versión grande cuando el usuario lo diga.
- Publicar una versión: subir el tag `vX.Y.Z` en este repo (el workflow publica
  `ghcr.io/ismaeloul/armario:X.Y.Z`) y actualizar `version`, `image` y `releaseNotes` en la carpeta de la
  tienda. El Umbrel tarda unos minutos en refrescar la tienda; no instalar hasta ver la versión nueva.
- Sin probar en el Umbrel (solo en Windows): el lector de límites de Codex (`codex app-server`) y la
  migración de columnas sobre la base de datos real. Sin probar en ningún sitio: Claude con API key real.
- Pendiente de la Fase 2: el aviso diario (llega con la app de iPhone, Fase 5) y afinar las reglas del
  outfit con el uso real. La «afinidad» que se muestra es orientativa, no aprendida.
- "Crear look con esta prenda" se muestra desactivado ("Pronto"): llega en la Fase 3.
- Afinado de la IA: el usuario prueba en el backend local (`http://localhost:8000`, sesión de Codex propia
  en `codex-home/`, aparte de la del Codex de escritorio) con fotos de Vinted. Reglas ajustadas el
  17-11-2026: temporada por tipo de prenda (sudadera, jersey, abrigo y botas = invierno; el usuario usa las
  sudaderas sobre todo en invierno), estampado "bloques de color", criterio logo/gráfico/texturizado y
  nombres en singular. El usuario suele guardar el borrador sin revisar, así que el informe
  `GET /api/ai/corrections` sale vacío: hay que mirar las fotos uno mismo.
- Codex por suscripción funciona en el PC (7-18 s por análisis) y dentro del contenedor del Umbrel. La
  cuenta del usuario es plan Plus.

## Comandos

- Backend: `backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000`
- Tests: `cd backend && .venv/Scripts/python -m pytest`
- Frontend: `cd frontend && npm run dev` (desarrollo) · `npm run build` (lo sirve el backend desde `frontend/dist`)

## Plan de fases

1. **Armario.** Añadir prenda con análisis por IA, catálogo con filtros, ficha, lavadora, Ajustes (tema y
   proveedor de IA), armario vacío y error de análisis. PWA instalable.
2. **Outfit del día.** Outfit diario según temporada y tiempo de la ciudad (API meteo gratuita, p. ej.
   Open-Meteo). Botones "Me gusta", "Pasar" y "Generar otra propuesta". Registrar lo que se usa cada día y
   no repetir outfits seguidos. No proponer prendas en la lavadora.
3. **Que aprenda.** Algoritmo propio que puntúa combinaciones a partir de las valoraciones; la IA ayuda al
   principio y con prendas nuevas, el objetivo es que el algoritmo acabe proponiendo solo. % e índice de
   afinidad reales. "Crear look con esta prenda". Aviso de prendas olvidadas. Quitar el fondo de las fotos en local (p. ej. rembg),
   guardando siempre también la original (el usuario lo movió aquí desde la Fase 1 el 17-11-2026).
4. **Compras.** (Decidido el 17-11-2026; el iPhone pasó a la Fase 5.) Pestaña «Compras» con un carrito,
   entre Gustos y Ajustes. El usuario activa tiendas (se empieza solo con Zara; después Pull&Bear, Bershka…)
   y la app trae cada semana las novedades de su catálogo: nombre, precio, fotos de producto y enlace.
   Se puntúan contra el armario con las reglas de estilo y lo aprendido en Gustos, y también se propone
   «lo que le falta al armario». Me gusta / no me gusta enseña al algoritmo. «La he comprado» pasa la
   prenda al armario con las fotos de la tienda, ya analizada (solo se elige talla). Codex no navega por
   las tiendas: solo analiza las fotos de las finalistas (10-15 por tanda) para no gastar el límite; el
   catálogo lo trae un conector por tienda. La app enlaza a la tienda y nunca compra ni guarda datos de
   pago. Interacción tipo Tinder: deslizar a la derecha = me gusta, a la izquierda = no me gusta. Las que
   gustan van a un apartado «Me gustan» dentro de Compras, y desde ahí se compra o se descarta. Todo
   caduca: las propuestas y los «me gustan» tienen fecha de caducidad porque las tiendas rotan el
   catálogo (pendiente de fijar el plazo; idea: comprobar cada semana si el producto sigue en la tienda y
   retirarlo si ya no está). Lo primero a comprobar antes de construir: si Zara deja leer el catálogo desde el Umbrel sin
   navegador (el 17-11-2026 se leyó desde un navegador con `<categoría>.html?ajax=true` y
   `<producto>.html?ajax=true`; las fotos de producto son las `-e1`, `-e2`… de `xmedia`).
5. **iPhone.** App con Capacitor (instalada como .ipa). Notificación diaria con el outfit a la hora configurada.

## Stack

- Backend: Python + FastAPI + SQLite.
- Frontend: React + Vite + Tailwind + TypeScript, mobile-first, componentes a mano (sin librería de UI).
- Un solo contenedor: FastAPI sirve la API y el build del frontend (el frontend es un paso de build del
  Dockerfile). De momento docker-compose lanzado a mano; app de Umbrel "de verdad", más adelante.
- Todo lo persistente dentro de `data/` (base de datos y fotos): hacer copia es copiar esa carpeta.
- PWA instalable ya en la Fase 1 (manifest e icono).
- El frontend debe poder empaquetarse con Capacitor: sin dependencias que lo impidan, URL de la API
  configurable, cámara detrás de `lib/camera.ts`, respetar las safe areas.
- Textos de la interfaz solo en español, pero en un único archivo para poder traducir algún día.

## Acceso

- Sin login en la Fase 1. Solo red local y Tailscale.
- No exponerla a internet (Cloudflare u otros) mientras no haya login.

## Diseño

- `stitch/*.html` son referencia visual, no base de código. `stitch/original/` es lo que salió de Stitch sin tocar.
- Pantallas: Hoy, Armario (catálogo), Añadir Prenda, Ficha de Prenda, Gustos y Ajustes, en claro y oscuro.
  Gustos no tiene diseño en Stitch: se hizo directamente en código con el mismo estilo.
- Barra inferior con 5 pestañas: Hoy, Armario, Gustos, Compras y Ajustes. Botón flotante "+" solo en Armario
  (abajo a la derecha, encima de la barra). El 17-11-2026 se probó el "+" en el centro de la barra y al
  usuario no le gustó: no volver a proponerlo.
- Iconos: Tabler (`@tabler/icons`, línea) como SVG en línea, elegidos por el usuario el 18-11-2026 entre
  ocho propuestas; no volver a Phosphor ni a Material Symbols. Única excepción: el armario es el de
  Iconoir (Tabler no tiene), con su versión rellena dibujada a mano en `Icon.tsx`. La pestaña activa de
  la barra inferior lleva el icono relleno. Va en la pestaña Armario y en la cabecera.
- Cabeceras: percha + "Armario" en Hoy y Armario; flecha atrás + nombre de pantalla en las secundarias
  ("Nueva prenda", "Detalle"); "Ajustes" a secas en Ajustes.
- El modo oscuro se cambia solo en Ajustes: Claro / Oscuro / Sistema.
- Añadir Prenda no tiene "Cancelar" (solo flecha atrás). La Ficha no tiene "Compartir ficha";
  "Editar detalles" va a ancho completo bajo "Crear look con esta prenda".
- Nada de precio ni "coste por uso" en la Ficha.
- Hoy en la Fase 1: estado provisional ("Pronto aquí verás tu outfit del día") con botón para ir al Armario.
- Estados que se construyen directamente en código con el mismo estilo:
  - Armario vacío: mensaje + botón para añadir la primera prenda.
  - Error al analizar una prenda: "Reintentar" o "Rellenar a mano".

## Tokens de diseño

Las paletas son tokens comunes (variables CSS + tema de Tailwind) que usan todas las pantallas, incluida Ajustes.
Nada de colores sueltos en los componentes.

| Token    | Claro                 | Oscuro                |
| -------- | --------------------- | --------------------- |
| Fondo    | `#fbf8fc`             | `#131315`             |
| Tarjetas | `#ffffff` / `#f6f2f7` | `#1b1b1e` / `#1f1f22` |
| Primario | `#464d48`             | `#c1c8c1`             |
| Texto    | `#1b1b1e`             | `#e4e1e6`             |
| Bordes   | sin borde             | blanco al 6 %         |

Tipografías: Plus Jakarta Sans (títulos) e Inter (texto).

## Datos

Listas cerradas (validadas en backend y usadas en los selectores del frontend):

- **Tipo → categoría** (`category` se deduce del tipo; el outfit de la Fase 2 se monta por categorías):
  - Parte superior: camiseta, camisa, polo, sudadera, jersey
  - Capa exterior: sobrecamisa, chaqueta, abrigo
  - Parte inferior: pantalón, vaquero, chino, pantalón corto, chándal
  - Calzado: zapatillas, zapatos, botas
- **Temporada** (una sola por prenda): Verano, Invierno, Todo el año.
- **Color** (nombre de paleta fija + hex libre solo para pintarlo): negro, blanco, gris, beige, crudo, marrón,
  azul marino, azul, celeste, verde, verde oliva, rojo, burdeos, amarillo, naranja, rosa, morado, multicolor.
  El color secundario es una lista, no un único valor.
- **Estampado:** liso, rayas, cuadros, gráfico, logo, texturizado.
- **Estilo:** casual, smart casual, deportivo, formal.

Tablas:

- `garments`: id, name, type, category, color_primary (+hex), colors_secondary (lista), pattern, style, details,
  season, brand, size, notes, photo_front, photo_back, photo_front_original, photo_back_original,
  in_laundry, laundry_since, favorite, ai_provider, ai_confidence, created_at, updated_at.
- `wear_log`: garment_id, fecha. El contador de usos y la última vez se derivan de aquí.
- `settings` (clave-valor): theme, ai_provider, city (Argenteuil por defecto), notify_enabled, notify_time.

Fotos: redimensionar a ~1600 px, WebP y miniatura. En la Fase 1 se guardan tal cual (sin quitar fondo).

## API

`GET /api/health` · `POST /api/garments/analyze` (devuelve borrador, no guarda) · `POST /api/garments` ·
`GET /api/garments` (filtros) · `GET /api/garments/summary` · `GET|PATCH|DELETE /api/garments/{id}` ·
`POST /api/garments/{id}/wear` · `POST /api/laundry/clear` · `GET|PATCH /api/settings` · `GET /media/...`

## IA

- Analiza las fotos (delantera y, si hay, trasera) y propone nombre, tipo, colores, estampado, estilo,
  detalles y temporada. Marca y talla solo si la etiqueta se lee claramente en alguna foto. Todo es
  editable antes de guardar.
- Interfaz común con dos implementaciones; el proveedor principal se elige en Ajustes.
  - **Codex:** suscripción de ChatGPT a través del CLI (`codex exec` no interactivo), sin API key.
  - **Claude:** API de Anthropic con API key.
- Modelos configurables por variables de entorno. Por defecto, uno económico con visión: en Claude, el
  Haiku más reciente; en Codex, el que use el CLI por defecto.
- Si falla el principal, se pasa al otro automáticamente pero no en silencio: el borrador muestra una nota
  tipo "Analizado con Claude". Si fallan los dos: error claro con "Reintentar" o "Rellenar a mano".
- La respuesta se valida contra el esquema (listas cerradas incluidas).

## Proceso

- Git desde el principio, repositorio privado en GitHub.
- `.gitignore`: `data/`, `.env` y cualquier credencial (incluidas las de Codex).
- Tests ligeros desde el principio: pytest en el backend para la validación del esquema de la IA y los
  endpoints principales.
- Idioma de la interfaz y de la conversación: español.
- Las cosas pequeñas se arreglan en local; a herramientas externas solo se les piden cambios grandes.
- Las ediciones de pantallas existentes hechas por el MCP de Stitch no se guardan (solo persisten las
  pantallas generadas como nuevas): no fiarse de su respuesta, comprobar descargando el HTML.
