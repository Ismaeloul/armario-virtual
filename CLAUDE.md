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
  opcional al descartar (quitado después: el usuario no quiere que se pregunte, y un descarte cuenta muy poco, 0,2 frente a 1 de un «me gusta», porque descartar no es decir que ese tipo de ropa no le gusta). El precio NO cuenta ni sale como motivo (el usuario no quiere). La temporada se lee también de la descripción. Codex NO analiza las finalistas.
  Buscador por referencia (lupa en Compras, 18-11-2026): se pega una referencia de Zara (3918/300,
  03918300…), un enlace de producto o texto libre, y cada resultado se puede guardar en Me gustan o meter
  directo en el armario («Ya la tengo»). Las referencias van directas a la ficha; el texto libre usa el
  buscador de Zara. Los resultados son `shop_items` en estado `buscado`, que se limpian a las 24 h.
  Descubrir cabe en una pantalla sin scroll, con botones flotantes redondos tipo Tinder (X, corazón y
  Volver) que animan la tarjeta; en Me gustan, tocar una prenda abre la foto en grande.
  Hecho el 18-11-2026: en el visor de la foto se desliza hacia arriba y sale la ficha (referencia tipo
  8281/765/800, tienda, color, tallas, composición y enlace, todo copiable) y «Combina con…» (las prendas
  del armario que mejor pegan, por parte del cuerpo; umbral `MATCH_MIN` 50). Selector de colores con
  circulitos en Descubrir, Me gustan y el buscador: el me gusta vale para el color que se ve y el otro
  queda como `variante`, que no se propone aparte en esa tanda. Las prendas del armario que vienen de
  Compras guardan `reference`, `store_name` y `store_url` y la Ficha los enseña SIN precio; hay un campo
  «Referencia» opcional al editar cualquier prenda. Probado por el usuario en el iPhone. En Descubrir,
  tocar el nombre de la tarjeta abre ese mismo visor. El enlace de la tienda se abre tocando el propio
  enlace (sin botón aparte) y no hay «Copiar todo» (el usuario los quitó). El contador de propuestas va en
  la pestaña («Descubrir (27)») para dejarle más alto a la foto.
  Decisiones del 18-11-2026 sobre tiendas: de momento TODAS con su versión de FRANCIA (el usuario vive allí;
  más adelante se añadirá España además de Francia, sin distinguir envíos). Pull&Bear y Bershka (y casi todas
  las grandes: H&M, Mango, Uniqlo, ASOS, Zalando, Adidas…) rechazan a un programa sin navegador y a un Chromium
  sin ventana, pero dejan pasar un Chromium de serie CON ventana (probado una vez con Playwright, sin parches).
  Plan aprobado: meter en la app un Chromium con pantalla virtual y leer las respuestas JSON que pide la propia
  página. Límite acordado con el usuario: solo «trucos legales»; nada de parches que oculten el navegador ni de
  resolver o rodear captchas: si una tienda pone captcha o bloquea, sale como «Falló» con el motivo en Tiendas.
  Se dejan leer sin navegador (sondeo): Nike, Jack & Jones, Jules, Courir; JD Sports solo las 72 primeras por sección.
  Hecho el 18-11-2026 (en `main`, sin publicar): tiendas de Francia. Con conector normal: Zara (ahora la
  francesa), Courir (martes) y JD Sports (miércoles; solo ~350-400 zapatillas, se pide con `curl` porque httpx
  recibe 403; sin probar en Linux). Con navegador (`services/shops/browser.py`, Playwright + Chromium de serie con
  ventana, Xvfb en Linux; `inditex.py`): Pull&Bear (lunes) y Bershka (jueves), que escuchan el JSON que pide la
  propia página. Probado en Windows sin bloqueos; SIN probar en Docker/Umbrel (en el PC del usuario no hay Docker:
  virtualización desactivada). El panel Tiendas distingue «el navegador no arranca» de «la tienda ha bloqueado».
  En local los navegadores van en `.playwright-browsers/` (fuera de git): desde `AppData` no se dejan ejecutar
  en este entorno («spawn UNKNOWN»). Las zapatillas guardan la marca y el algoritmo la aprende. Los nombres,
  colores y composición se traducen al español con Codex en lote (`services/ai/translate.py`), con modelo y
  esfuerzo propios en Ajustes (el usuario quiere Luna en bajo para traducir y Terra en alto para las fotos).
  Construidas el 18-11-2026 las 15 tiendas acordadas (en `main`, sin publicar; 20 en total, 416 tests), todas
  desactivadas: Massimo Dutti y Lefties (`inditex.py`), Jack & Jones, Carhartt WIP, Foot Locker (estas
  tres sin navegador, sin probar en Linux: si dan 403 allí, pasar a `needs_browser = True`), Nike (con
  navegador desde el 18-11-2026: la segunda página pedida con httpx empezó a dar HTTP 400, en el PC y en el
  Umbrel; ahora se baja la página y se escucha lo que pide sola; de día la ficha sale de lo guardado del
  listado, con una sola foto), Snipes, size?,
  Jules y Bonobo (`sfra.py`), y Uniqlo, Mango, H&M, COS y Weekday (`listing.py`: solo se lee el listado, nunca
  la ficha; H&M, COS, Uniqlo y Mango sin tallas, «Míralas en la tienda» y talla a mano al comprar; H&M con
  tope de 8 páginas por sección). Las zapatillas iguales de varias tiendas salen una sola vez (`maker_code`,
  «También en: …»; JD Sports no da ese código). Cada noche, como mucho 3 tiendas y 2 pesadas. Probadas de
  verdad en Windows todas menos dos: Uniqlo dio «Access Denied» en la primera página (se paró ahí) y Mango
  cargó pero el conector no encontró productos (retocado después, solo con tests). Nada probado en el Umbrel.
  Tiendas nuevas acordadas con el usuario el 18-11-2026 (lista y motivos; notas y fixtures por
  tienda en el scratchpad de esa sesión, carpeta `tiendas/`): sin navegador Nike (solo zapatillas), Jack & Jones,
  Carhartt WIP y Foot Locker (por marcas y novedades; no pagina bien); con navegador Snipes, Size?, Jules, Bonobo,
  Massimo Dutti y Lefties (mismo `inditex.py`), Uniqlo, Mango y Weekday; y H&M y COS solo con el listado (la ficha
  da Access Denied: sin tallas). Fuera: Arket y Springfield (decisión del usuario: fotos dudosas / solo con
  modelo), Adidas, New Balance, Levi's, Celio, Kiabi y Citadium (bloqueo o captcha también con navegador),
  Stradivarius (sin hombre en Francia) y los marketplaces (Zalando, ASOS, About You, La Redoute: el usuario no
  los quiere). No usar identificadores copiados de la web para llamar a APIs internas (Nike disponibilidad,
  Uniqlo `x-fr-clientid`, Mango): esas tiendas van por el navegador escuchando lo que pide la página. Todas
  nacen desactivadas. Ojo al investigar: un agente lanzó 33 peticiones seguidas a Mango y otro llegó al
  cortafuegos de Citadium; las dos bloquearon un tiempo la IP de casa. Pausas siempre.
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
- **Publicada en el Umbrel: 0.4.17** (20-11-2026): hoja que sube desde abajo (`components/BottomSheet.tsx`,
  sin X: se cierra deslizando hacia abajo desde el asa o desde el contenido arriba del todo, tocando fuera o
  con Escape, con animación de cierre) con la ficha completa de la prenda (`GarmentSheet` = `FichaPrenda`
  con `embedded`) al tocar una prenda en Tus outfits, Gustos (toda la fila, salvo al señalar la que no
  pega), Armario y Hoy. «Monta tu outfit» y el selector de pareja usan la misma hoja. Compras: un solo
  botón «Filtros» (hoja con tienda y tipo) y tocar la parte blanca de la tarjeta de Descubrir abre
  `ShopSheet` (datos, «Ver en <tienda>» grande y «Combina con»; `ShopFacts` compartido con el visor).
  Uniqlo: antes de proponer, la ficha de API.SH (`/product`, 1 crédito por producto, todos sus colores,
  guardada 12 h) dice qué tallas quedan y lo agotado no sale; se deja de mirar a 40 créditos del tope
  (`STOCK_RESERVE`); fuera lo `store_stock_only`. Uniqlo deja pasar MEN y UNISEX (un jogging que parecía
  de mujer era de esos; pendiente de que el usuario decida si quitar los unisex).
- **Antes: 0.4.16** (20-11-2026): saldo real de API.SH en Ajustes (`apish.account()`,
  `GET /v1/account`, gratis; `GET /api/settings/apish-account`; en memoria 5 min). En el Armario, el título
  y «Tus outfits» van en la misma fila, justo encima del selector de temporada.
- **Antes: 0.4.15** (20-11-2026). Uniqlo por API.SH (servicio de scraping de pago,
  decisión expresa del usuario como excepción SOLO para Uniqlo, que bloquea nuestro Chromium con Akamai;
  las demás tiendas no cambian). `services/apish.py` (cliente común, `raw=0`, contador de créditos
  mensual y GLOBAL en `settings.apish_credits`, tope 300 con `ARMARIO_APISH_MONTHLY_CREDITS`),
  `services/vault.py` (clave cifrada con Fernet en `settings.secret_apish`; la llave maestra en
  `CODEX_HOME/armario-vault.key`, fuera de `data/`), `shops/uniqlo.py` reescrito (`uses_apish = True`,
  sin navegador). La clave se pega en Ajustes → «API.SH» (solo escritura, nunca se devuelve; en
  desarrollo manda `ARMARIO_APISH_KEY`). La API no filtra por clase: cada sección es hombre (37609) + una
  palabra (13 secciones); se ordena por novedad y se para al llegar a lo ya visto; recorrido completo
  una vez al mes. Solo se proponen colores con foto de producto sin modelo (`goods_`). Prueba real en
  local el 20-11-2026: 18 créditos, 323 productos, 2 min; 10 propuestas sin gastar más. Sin probar en
  el Umbrel. El usuario renovará la clave de prueba (la pegó en el chat) y pegará la nueva en Ajustes.
- **Antes: 0.4.14** (19-11-2026). «Tus outfits» pasa de Gustos al Armario: botón con el
  icono del armario encima del selector de temporada, pantalla `/armario/outfits` (`pages/TusOutfits.tsx`)
  con «Montar un outfit» (`OutfitPicker` en `components/OwnOutfits.tsx`), lista horizontal y tarjeta del
  outfit al tocarlo (prendas enlazadas a su ficha, zoom en la foto, quitar). En Gustos, «Me gusta y
  guardar» (`save` en `/taste/rate`): va a «Tus outfits», cuenta doble y no se vuelve a preguntar.
  Uniqlo: investigado el 19-11-2026, Akamai Bot Manager bloquea el navegador automatizado ya en la
  portada (con un navegador normal y la misma IP sí carga). El usuario NO quiere ocultar la automatización
  y lo dio por cerrado: Uniqlo se queda desactivada. Idea aparcada: un marcador «Guardar en Armario» que
  mande a la app los datos de la ficha que el usuario tiene abierta en su navegador.
- **Antes: 0.4.13** (19-11-2026). «Tus outfits» en Gustos (`components/OwnOutfits.tsx`,
  `GET|POST /api/taste/own`, `DELETE /api/taste/own/{id}`): el usuario monta un outfit que sabe que le
  queda bien y cuenta como un «me gusta» con peso 2 (`Rating.source = "propio"`); arriba puede llevar
  varias prendas, abajo y calzado una. Ajuste «Qué ropa toca ahora» (`settings.season_mode`: auto,
  verano o invierno; manda sobre el mes). Arreglo: la camiseta de debajo de la sudadera con cremallera
  salía siempre la misma (la de España, marcada de verano): ahora respeta la temporada, prefiere una
  lisa y rota (`REPEATED_UNDERSHIRT` y azar); y la afinidad mínima ya no cuela ropa fuera de temporada.
- **Antes: 0.4.12** (19-11-2026): en Gustos, tocar la foto de una prenda la abre en
  grande con `ZoomViewer` (todas sus fotos), sin salir de la pantalla: ir a la Ficha cambiaba la
  combinación al volver. El resto de la fila sigue marcando la prenda que no pega.
- **Antes: 0.4.11** (19-11-2026). El usuario está metiendo su armario real y el
  proceso era lento. Lleva:
  Añadir prenda: las fotos de Codex se generan TODAS A LA VEZ (`StudioReview`, antes de una en una).
  Foto opcional «Textura y color» (primer plano de la tela): no se guarda en la prenda, va de apoyo al
  análisis (color correcto: un marrón muy oscuro salía negro) y a Codex al redibujar (`texture` en
  `/garments/analyze` y `/photos/studio`). Zapatillas: foto obligatoria «Las dos juntas»
  (`garments.photo_pair`), que es la portada (`photo_cover` en la API) y la primera de la Ficha.
  Ficha: vuelve «Editar fotos con Codex» (`components/GarmentExtras.tsx`, `StudioCard`) para las vistas
  que siguen siendo de la cámara (`photos_edited_views`); y «Pareja» (`PairCard`, `garments.pair_id`,
  `PUT /garments/{id}/pair`): la otra mitad de un conjunto (chándal), enlace en los dos sentidos, solo ropa.
  Hoy (`services/outfits.py`): la pareja junta compite con ventaja (`PAIR_TOGETHER`) pero se puede separar;
  afinidad mínima del 60 % (`MIN_AFFINITY`; si nada llega, nota `afinidad_baja`); camiseta debajo de la
  sudadera SOLO si tiene cremallera entera (se añade al final, no cuenta en la afinidad ni en las
  valoraciones: `without_undershirt`); con frío la capa exterior es obligatoria si alguna vale.
  Sin probar con Codex real (la sesión de Codex de la copia local caducó): la foto de textura, las dos
  juntas y dos ediciones simultáneas.
  Auditoría de seguridad con Mythos: APARCADA por el usuario (gastaba demasiados tokens). Solo se hizo el
  reconocimiento y el plan de cobertura, guardados en `~/security-audit-skill/armario-virtual/run-1/`. El
  repaso general con Fable no produjo nada (se quedó sin límite). No relanzar sin que lo pida.
- **Antes: 0.4.10** (19-11-2026). La 0.4.9 se etiquetó pero NO llegó a la tienda (su
  arreglo de colores era malo). Lleva:
  Colores de Compras bien definidos (agente con Fable): en Courir el bloque «Couleur» enlaza TODA la línea
  del modelo (una Air Force 1 Luxe enlaza 41 productos distintos), no los colores de la zapatilla. Ahora
  solo cuentan como colores los del mismo modelo (`courir.same_model`: misma dirección de ficha salvo el
  número; `partial_colors = True`), todo pasa por `shopping.family_of`, y al cambiar de color los dos
  items comparten familia (`_share_family`), así que volver al anterior no va a la tienda. Si un color no
  tiene foto de producto lo dice y su circulito se quita (`_forget_color`). Las demás tiendas no cambian.
  Pendiente: fotos `.png` de Courir (el conector solo reconoce `_101.jpg`; al probar una dio 403).
  Fotos pendientes: lo guardado o buscado sin foto de una tienda de navegador las baja solo
  (`shopping.photos_soon` / `fetch_missing_photos`: trabajo corto con su propia sesión de navegador, hasta
  8 fichas, reintentos cada vez más espaciados; `GET /api/shop/items?ids=` y `usePendingPhotos` para que
  la foto aparezca sin recargar). Motivo: una Air Force de JD Sports guardada desde el buscador en el
  Umbrel se quedó sin foto. Sin probar con un navegador real.
  Ofertas: `shop_items.old_price_cents`, solo de lo que dice la tienda (nunca comparando con otro día);
  componente `Price` en Descubrir, Me gustan, buscador y visor (etiqueta «−30 %», anterior tachado, actual
  en `text-danger`). No influye en la puntuación; en el armario no hay precios. Sin forzar consultas
  (decisión del usuario): lo traen los productos según entran. Implementado en 16 tiendas; SIN precio
  anterior en Zara, H&M, Mango y Jack & Jones porque no había nada rebajado en los datos para saber el
  campo: repetir UNA petición a Zara cuando empiece el Black Friday (hacia el 26-11).
  El botón del corazón de Descubrir va invertido (fondo blanco, corazón verde), a petición del usuario.
- **Antes: 0.4.9** (solo etiqueta, 19-11-2026): al elegir un color en Compras ya no desaparecen los
  demás. En Courir la ficha de cada color solo enlaza a unos pocos hermanos (la Dunk gris nombra diez; la
  beige, dos), y la app se quedaba con la lista corta. Ahora los colores conocidos se conservan
  (`_merge_siblings` en `shopping.py`, en `switch_color` y en `_apply_detail`). Un color que deje de
  existir sigue saliendo y al tocarlo dice que ya no está. Sin probar contra Courir de verdad.
- **Antes: 0.4.8** (19-11-2026): la foto de la Ficha. El recuadro toma la proporción
  de la foto (sin bandas); la de la primera se mide antes de pintar la ficha y la foto va a su ancho,
  pegada arriba, para que al cambiar de alto no parezca que hace zoom. Puntos abajo en vez de «Vista
  frontal / posterior» y toque en la mitad derecha o izquierda para pasar de foto, en bucle como en
  Compras. El botón de girar ya NO está en la Ficha: solo al añadir la prenda (decisión del usuario).
  `ScrollManager` en `main.tsx`: al entrar en una pantalla el scroll va arriba (antes la ficha heredaba
  el del Armario) y al volver atrás se recupera donde se estaba.
- **Antes: 0.4.7** (18-11-2026): fotos de tienda al añadir la prenda. El usuario
  confirmó en el Umbrel que Codex genera imágenes dentro del contenedor y convirtió sus dos prendas; la
  tarjeta temporal de la Ficha ya NO existe. Ahora, en «Nueva prenda», tras el análisis sale cada foto
  junto a la que redibuja Codex (`components/StudioReview.tsx`, `POST /api/photos/studio`, de una en una):
  «Me vale» o «No me vale», que abre un cuadro para explicar qué falló y la rehace con ese comentario y el
  intento anterior. Solo las que tienen el visto bueno sustituyen a la original al guardar
  (`/studio/apply`); sin visto bueno se queda la foto del usuario. Tocar una foto la abre en grande con
  zoom (`components/ZoomViewer.tsx`: pellizco, doble toque, rueda; cambia entre «Tu foto» y «Codex» sin
  perder el encuadre). El pellizco está sin probar en un iPhone. Un agente revisó las animaciones: las
  de entrada llevan relleno `backwards`, no `both` (con `both` la pantalla seguía siendo contexto de
  apilamiento y lo `fixed` de dentro quedaba bajo la barra); el visor de fotos de Compras va en un portal;
  los skeletons miden como el contenido real; la pastilla de `Segmented` solo se desliza si la toca el
  usuario.
- **Antes: 0.4.6** (18-11-2026): animaciones y fotos de tienda con Codex.
  Animaciones (`theme/tokens.css`, `components/Skeleton.tsx`): skeletons con destello en vez de
  «Cargando…», fundido al cambiar de pantalla, Ficha y lavadora entran por la derecha, tarjetas escalonadas,
  fotos que aparecen al cargar, pastilla deslizante en `Segmented`, diálogos y paneles animados y destello
  en los textos «Analizando…» (`shimmer-text`). Al usuario le gustaron tal cual. `Screen` solo anima la
  opacidad: un transform ahí descoloca lo `fixed` de dentro. `?lento=1` retrasa las cargas 1,5 s para
  ver los skeletons (`?lento=0` lo quita).
  «Editar foto con Codex» en la Ficha (temporal; quitada en la 0.4.7): `services/ai/studio.py` lanza `codex exec`
  con todas las fotos de la prenda, diciendo cuál es la delantera y cuál la trasera (sin eso dibujó la
  capucha de delante como si fuera la espalda), y recoge la imagen de `CODEX_HOME/generated_images/`.
  Unos 40 s por foto. Se enseña antes y después; las de la cámara se guardan en `garments.photos_camera`
  y se puede volver. Codex redibuja, no recorta: puede cambiar detalles. Probado en Windows; SIN probar
  en el Umbrel. Bandas del iPhone al cambiar de tema (`lib/theme.ts`: fondo escrito a mano, etiqueta
  theme-color nueva y cabecera y barra ocultas un fotograma): sin probar en un iPhone.
- **Antes: 0.4.5** (18-11-2026): prendas «pedidas». En Me gustan, al comprar se elige
  «La he pedido, aún no ha llegado» o «Ya la tengo en casa». Lo pedido entra en el armario con la
  etiqueta «Pedida» (`garments.on_order`, `ordered_at`): Hoy no lo propone y no se puede apuntar un uso,
  pero en Gustos SÍ sale para valorar (decisión del usuario: entrenar ya con lo que está por llegar).
  En la Ficha, «Ya me ha llegado» lo deja como una prenda más; la talla se cambia en «Editar detalles».
  La foto de la Ficha se ve entera (`object-contain`; la etiqueta salía ampliada). El aviso «N prendas
  en la lavadora» del Armario abre `/armario/lavadora`, el mismo listado solo con lo que se lava (antes
  llevaba a Ajustes); en el Armario siguen saliendo todas.
- **Antes: 0.4.4** (18-11-2026): Nike con navegador, la tarjeta de debajo ya no cambia al
  llegar propuestas nuevas y «Ver más de <tienda>» / «Buscar más en <tienda>» con el filtro de una tienda.
- **Antes: 0.4.3** (18-11-2026): las 20 tiendas, el catálogo completo de noche, la pila de
  tarjetas, la barra de progreso real y los colores apagados. Nada de eso probado antes en el Umbrel.
- **Antes: 0.4.2** (18-11-2026): JD Sports pasa a leerse con el navegador y al cambiar de
  color se hereda el nombre traducido. En la 0.4.1 se comprobó en el Umbrel real: el Chromium arranca con
  Xvfb y Pull&Bear funciona (449 productos, 0 fallos); JD Sports con `curl` daba 403 en Linux (filtro por
  huella del cliente), por eso se pasó al navegador. Límite firme, hablado con el usuario: no se disfraza el
  navegador (ni extensiones para cambiar el user agent ni nada parecido), tampoco «solo para una tienda».
- **Antes: 0.4.1** (la etiqueta v0.4.0 existe pero su imagen no llegó a construirse: faltaba `libatomic1`) (18-11-2026: Fase 4, Compras, con cinco tiendas de Francia; es la primera vez que el Chromium y JD Sports corren en Linux, sin probar). Antes 0.3.2 (18-11-2026: barrido de pulido; antes 0.3.1, 17-11-2026; la 0.3.0 más el arreglo de copiar el código de Codex por http): incluye todo lo que abajo figura
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

Lo último de todo (idea del usuario, 18-11-2026): que la app se conecte por su dominio propio, sin VPN.
Exige poner login antes (ver «Acceso»: no exponerla a internet sin login).

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
