# TraduIA — repositorio offline en un USB (guía mínima)

## 1. Crear el repositorio en el USB

En un equipo con el paquete `traduia` instalado y acceso a Internet:

    traduia-make-repo full /media/usuario/USB/traduia

Deja en el USB todos los modelos (whisper + marian + ct2), las dependencias
Python (wheels) y los paquetes del sistema de jammy y noble, con su
`manifest.json` y verificador. Requiere el paquete Python `huggingface_hub`
en el `python3` del sistema.

## 2. Instalar en otra máquina desde el USB

En el equipo destino (jammy o noble):

    # <distro> = codename del equipo (jammy o noble)
    sudo apt install /media/usuario/USB/traduia/debs/<distro>/zero-lliurex-traduia_*.deb
    sudo apt install /media/usuario/USB/traduia/debs/<distro>/traduia_*.deb

    sudo traduia-config install

En el asistente: modo **Servidor**, origen **USB** y seleccionar
`/media/usuario/USB/traduia`. Los modelos quedan instalados y el sistema
configurado y listo para usarse, sin necesidad de Internet.

Guía completa: [`howto-export-models.md`](howto-export-models.md).
