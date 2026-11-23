# TraduIA — repositorio offline en un USB (guía mínima)

## 1. Crear el repositorio en el USB

En un equipo con el paquete `traduia` instalado y acceso a Internet:

    traduia-make-repo --full --output-dir /media/usuario/USB/traduia

Deja en el USB todos los modelos (whisper + marian + ct2), las dependencias
Python (wheels) y los paquetes del sistema de jammy y noble, con su
`manifest.json` y verificador. Requiere el paquete Python `huggingface_hub`
en el `python3` del sistema.

## 2. Instalar en otra máquina desde el USB

En el equipo destino (jammy o noble):

    sudo /media/usuario/USB/traduia/install-offline.sh

Elegir:

- **TraduIA cliente** o **TraduIA servidor**.
- **Todo con todas las voces**.
- En cliente/servidor se pregunta si instalar Piper; si se acepta, se
  instalan todas las voces.

El instalador usa un entorno apt temporal en `/tmp` y no modifica
`/etc/apt` ni los repositorios del sistema. Al terminar avisa y ofrece
ejecutar `traduia-config`:

    sudo traduia-config

En cliente/servidor el modo y el origen USB ya quedan preconfigurados; en
“Todo con todas las voces”, `traduia-config` pregunta modo y origen. Los
modelos quedan instalados y el sistema configurado, sin necesidad de
Internet.

Guía completa: [`howto-export-models.md`](howto-export-models.md).
