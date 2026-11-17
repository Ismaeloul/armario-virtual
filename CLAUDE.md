# Armario virtual

App personal de armario virtual: catalogar prendas con foto, analizarlas con IA y recibir un outfit diario.
Un solo usuario y un solo armario, desplegada en casa sobre Umbrel.

## Estado

- Diseño cerrado. Stitch queda solo como referencia visual; no se le mandan más cambios.
- Fase 1: prototipo completo en local. Hoy provisional; Armario (filtros, vacío, botón "+"); Nueva prenda
  (análisis, borrador, error, a mano); Ficha (fotos, favorita, lavadora, uso, editar, eliminar); Ajustes
  (tema, IA, lavadora, aviso y ciudad guardados para la Fase 2). Las fotos huérfanas se limpian al arrancar.
- Desplegada en el Umbrel como app de la tienda propia (`Ismaeloul/umbrel-app-store`, carpeta
  `ismaeloul-armario`, puerto 7798, detrás del login de Umbrel). El usuario ha añadido una prenda allí y
  Codex la ha analizado dentro del contenedor (17-11-2026).
- Publicar una versión: subir el tag `vX.Y.Z` en este repo (el workflow publica
  `ghcr.io/ismaeloul/armario:X.Y.Z`) y actualizar `version` e `image` en la carpeta de la tienda.
  El Umbrel tarda unos minutos en refrescar la tienda; no instalar hasta ver la versión nueva.
- Pendiente de la Fase 1: probar Claude con API key real (se pega en Ajustes), probar el resto de
  pantallas y la cámara desde el iPhone y, al final, quitar el fondo de las fotos.
- "Crear look con esta prenda" se muestra desactivado ("Pronto"): llega en la Fase 3.
- Codex por suscripción: funciona en el PC (12-18 s por análisis) y dentro del contenedor del Umbrel.

## Comandos

- Backend: `backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000`
- Tests: `cd backend && .venv/Scripts/python -m pytest`
- Frontend: `cd frontend && npm run dev` (desarrollo) · `npm run build` (lo sirve el backend desde `frontend/dist`)

## Plan de fases

1. **Armario.** Añadir prenda con análisis por IA, catálogo con filtros, ficha, lavadora, Ajustes (tema y
   proveedor de IA), armario vacío y error de análisis. PWA instalable. Al final, si da tiempo: quitar el
   fondo de las fotos en local (p. ej. rembg), guardando siempre también la original.
2. **Outfit del día.** Outfit diario según temporada y tiempo de la ciudad (API meteo gratuita, p. ej.
   Open-Meteo). Botones "Me gusta", "Pasar" y "Generar otra propuesta". Registrar lo que se usa cada día y
   no repetir outfits seguidos. No proponer prendas en la lavadora.
3. **Que aprenda.** Algoritmo propio que puntúa combinaciones a partir de las valoraciones; la IA ayuda al
   principio y con prendas nuevas, el objetivo es que el algoritmo acabe proponiendo solo. % e índice de
   afinidad reales. "Crear look con esta prenda". Aviso de prendas olvidadas.
4. **iPhone.** App con Capacitor (instalada como .ipa). Notificación diaria con el outfit a la hora configurada.

Más adelante: recomendaciones de qué prenda comprar según lo que ya hay.

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
- Pantallas: Hoy, Armario (catálogo), Añadir Prenda, Ficha de Prenda, Ajustes. Cada una en claro y oscuro.
- Barra inferior con 3 pestañas: Hoy, Armario, Ajustes.
- Botón flotante "+" solo en Armario (abajo a la derecha, encima de la barra).
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
