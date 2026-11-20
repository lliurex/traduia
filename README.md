# traduIA

TraduIA permite realizar traducciones automáticas en tiempo real desde el
sonido del sistema o el micrófono hacia un cliente web que muestra las
traducciones, soportando múltiples idiomas.

## Qué hace

- Captura el audio del sistema o del micrófono y lo transcribe
  (faster-whisper).
- Traduce la transcripción en tiempo real (set Marian u Optimized/CT2).
- Sirve un cliente web donde cada usuario ve las traducciones en su idioma.

## Componentes principales

- `traduia` / `traduia_server.py`: servidor de transcripción y traducción,
  con el cliente web incluido.
- `install-models-traduia`: instalación de modelos desde Internet, USB o
  LAN.
- `traduia-make-repo`: genera repositorios offline (modelos + wheels +
  debs) — acciones `--export`, `--fetch`, `--wheels`, `--debs` y `--full`.
- `traduia-config` (paquete `zero-lliurex-traduia`): instalación y
  configuración integrada, desde zero-center o desde consola.

## Lectura en voz alta (TTS)

El cliente web incluye un botón de lectura en el modo «Ver traducido». Cada
frase nueva se lee con la síntesis de voz del dispositivo (no en el
servidor). Empieza desactivado y solo lee las frases que lleguen a partir de
ese momento; no repite el historial ni se muestra en modo transcripción.

- Por defecto solo se usan voces locales. Si el navegador únicamente ofrece
  voces en la nube, el botón aparece deshabilitado por privacidad.
- En Android e iOS la lectura se detiene cuando la pestaña pasa a segundo
  plano (limitación del navegador). En escritorio, Firefox y Chromium siguen
  leyendo con la pestaña oculta o la ventana minimizada.
- Si el cliente se abre en el mismo equipo que captura el audio del sistema
  (monitor), la lectura se deshabilita para no reinyectar su propia salida en
  la transcripción. Con captura de micrófono sí se permite.
- El motor de síntesis es compartido por el navegador: dos pestañas de
  TraduIA pueden cancelarse entre sí.

Política configurable en `traduia_server.py`:

- `TTS_ALLOW_CLOUD = False`: permite usar voces no locales (nube); por
  defecto solo se usan voces locales.
- `TTS_MOBILE_ENABLED = True`: permite la lectura en Android/iOS.
- `TTS_DEBUG_API = False`: expone `window.TraduiaTTS` en el cliente para
  depuración con DevTools. Debe permanecer `False` en los paquetes; para
  depurar una instalación se edita manualmente y se reinicia el servidor.

Dependencias: `piper-tts-server` figura en `Suggests` (no se instala
obligatoriamente). El instalador de TraduIA permite marcarlo como opcional;
la app `zero-lliurex-piper-tts-server` se recomienda (`Recommends`) pero no
es obligatoria y usa `Service=False` (sin estado N4D). En escritorio Linux,
Firefox necesita `speech-dispatcher` y un motor de voz local; en Android/iOS
se usa el motor del sistema.

Con `TTS_DEBUG_API = True`, desde la consola del navegador:

```js
TraduiaTTS.state();
TraduiaTTS.setDebug({ allowCloud: true });
TraduiaTTS.setDebug({ localClient: true, capture: "monitor" });
TraduiaTTS.speak("Hello", "en");
TraduiaTTS.stop();
```

## Distribución offline

Los modelos, las dependencias Python, los paquetes del sistema (TraduIA,
instaladores zero-center, Piper, voces, ONNX y dependencias estáticas) y un
índice apt local se empaquetan en un repositorio autocontenido (con
`manifest.json` y verificación sha256). Incluye `install-offline.sh`, que
instala desde el USB/directorio usando un entorno apt temporal en `/tmp` sin
modificar los repositorios del sistema. También se puede publicar por HTTP e
instalar en aulas sin salida a Internet.

## Documentación

- `docs/howto-export-models.md` — guía completa (creación del repositorio e
  instalación, con la referencia de comandos en el apéndice).
- `docs/readme.md` — guía mínima: repositorio completo en un USB.

## Requisitos

- Ubuntu jammy (22.04) o noble (24.04) con los repositorios de LliureX
  actualizados (`lliurex-upgrade` / `lliurex-up`).
- Dependencias del sistema: `python3-venv`, `kdialog`, `jq`,
  `lliurex-firefox-settings`, `zero-center`/`epi-gtk` (detalle completo en
  `debian/control`).
