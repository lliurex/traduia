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
  debs) — subcomandos `fetch`, `wheels`, `debs` y `full`.
- `traduia-config` (paquete `zero-lliurex-traduia`): instalación y
  configuración integrada, desde zero-center o desde consola.

## Distribución offline

Los modelos, las dependencias Python y los paquetes del sistema se
empaquetan en un repositorio autocontenido (con `manifest.json` y
verificación sha256) que se puede distribuir por USB o HTTP e instalar en
aulas sin salida a Internet.

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
