# HowTo: repositorio offline de TraduIA (creación e instalación)

Este documento describe el flujo completo de trabajo con el **repositorio
offline de TraduIA**: cómo **crear** un repositorio autocontenido (modelos de
traducción y transcripción, dependencias Python y paquetes del sistema, con
un `manifest.json` de integridad) y cómo **instalar TraduIA en otras
máquinas** a partir de él, tanto por **USB** como por **red** (HTTP).

- **Máquina origen**: la que genera el repositorio. No necesita tener los
  modelos instalados: el subcomando `full` los descarga de HuggingFace (con
  Internet).
- **Máquina destino**: la que instala TraduIA desde el repositorio, con
  distribución **jammy** (Ubuntu 22.04) o **noble** (Ubuntu 24.04).

Organización del documento:

- **Sección 2 — Crear el repositorio** de la forma más sencilla (un comando).
- **Sección 3 — Instalar en otra máquina** a partir del repositorio (USB o
  red), incluida la instalación completa con `traduia-config`.
- **Sección 4 — Modos avanzados**: crear u obtener el repositorio por partes
  (modelos desde una máquina que ya los tiene, fetch/wheels/debs
  independientes, publicación HTTP).
- **Sección 5 — Apéndice**: referencia de comandos con la salida literal de
  sus `--help`.

> **Requisito previo — `python3-venv`**: el equipo **destino** debe tener el
> paquete `python3-venv` **funcional y coherente con las versiones de Python
> instaladas** (jammy → Python 3.10, noble → Python 3.12). Para disponer de
> la versión correcta del paquete, el sistema operativo debe estar
> **actualizado con las últimas correcciones del repositorio de LliureX**
> mediante las herramientas de actualización de LliureX: `lliurex-upgrade`
> (gráfico) o `lliurex-up` (consola). El instalador crea el entorno
> virtual con `python3 -m venv` y la comprobación previa offline crea además
> un venv temporal de validación; si el paquete falta o no coincide con la
> versión de `python3` del sistema (por ejemplo, tras una actualización de
> Python), la creación del venv falla con un error claro y la instalación se
> aborta. En equipos sin red este paquete debe estar disponible de antemano
> (ver sección 4.5); los detalles del venv están en la sección 3.6.

---

## 2. Crear el repositorio (la forma más sencilla)

### 2.1 Un comando: `full`

El subcomando `full` genera el repositorio 100% offline en un solo paso y
**sin necesidad de tener los modelos previamente instalados** en la máquina
origen: los descarga directamente de HuggingFace.

```bash
# Con los repositorios por defecto (lliurex.net, para ambas distros):
traduia-make-repo full /srv/export/traduia

# Apuntando al repositorio con los debs más actualizados:
traduia-make-repo full /srv/export/traduia \
    --url-jammy <URL_REPO_JAMMY> \
    --url-noble <URL_REPO_NOBLE>
```

- **Equivale a** ejecutar `fetch all` (whisper + marian + ct2 desde
  HuggingFace), `wheels` (dependencias Python para jammy cp310 y noble
  cp312) y `debs all` (paquetes `traduia` y `zero-lliurex-traduia` de
  jammy y noble), más el `manifest.json` global y el verificador
  `verify-models.py`.
- **Idempotente**: si algún paso falla se continúan los demás y al final se
  avisa (`[WARN]`) con código de salida 1; re-ejecutar el mismo comando
  reintenta solo lo que falta (los modelos ya descargados se omiten, los
  wheels y los debs se refrescan). Al terminar sin errores imprime
  `Repository ready`.
- **Requisito**: la descarga de modelos necesita el paquete Python
  `huggingface_hub` en el `python3` del sistema
  (`pip install huggingface_hub`); los pasos de wheels y debs solo usan la
  librería estándar.
- `--url-jammy`/`--url-noble` tienen el mismo significado que en `debs`
  (sección 4.5) y solo afectan al paso de descarga de los debs.

### 2.2 Qué contiene el repositorio

El repositorio tiene un **único `manifest.json` en la raíz** que cubre todo
el contenido (`whisper-small/` + los sets presentes + wheels + debs), con
`size` + `sha256` por fichero. Estructura resultante:

```
/srv/export/traduia/
├── manifest.json          # manifest GLOBAL (todo el contenido)
├── verify-models.py       # verificador de integridad (sección 2.3)
├── whisper-small/…        # UNA sola copia, compartida
├── ct2/opus-mt-{par}/…    # set optimizado (CTranslate2)
├── marian/opus-mt-{par}/… # set original (Marian)
├── wheels/…               # dependencias Python (offline total)
├── debs/jammy/…           # traduia y zero-lliurex-traduia de jammy
└── debs/noble/…           # traduia y zero-lliurex-traduia de noble
```

Ejemplo de `manifest.json`:

```json
{
  "version": 1,
  "generated": "2026-08-06T12:00:00Z",
  "mode": "marian",
  "files": [
    {"path": "whisper-small/model.bin", "size": 484114091, "sha256": "abc123…"}
  ]
}
```

> Todos los subcomandos de `traduia-make-repo` son **aditivos**: se puede
> ejecutar una vez por cada cosa que se quiera llevar, apuntando siempre al
> **mismo** directorio de salida; `whisper-small` solo se copia en la primera
> ejecución — **nunca se duplica** — y re-ejecutar refresca los ficheros
> (idempotente, útil al actualizar). El `mode` del manifest se detecta del
> contenido (`ct2` | `marian` | `both`) y el verificador `verify-models.py`
> se escribe/actualiza en cada ejecución. Las especializaciones (un solo
> set, wheels o debs por separado, modelos desde un directorio local…) se
> detallan en la sección 4.

### 2.3 Verificación de la integridad

`traduia-make-repo` genera junto al manifest un verificador
(`verify-models.py`). Se comprueba que cada fichero coincide con su sha256:

```bash
cd /srv/export/traduia
python3 verify-models.py                    # todo el repositorio
python3 verify-models.py --mode ct2 <dir>   # solo whisper + un set
```

- Imprime `OK: <ruta>` por fichero (o `FALTA/TAMAÑO:` / `SHA256 INCORRECTO:` /
  `ERROR NO LEGIBLE:`), un resumen final y devuelve `exit 0` si todo es
  correcto o `1` si hay errores. Con `--mode` falla si el set pedido no está
  en el manifest.
- El verificador viaja con el repositorio (USB o repo HTTP), así que puede
  ejecutarse en cualquier máquina sin copiar nada de esta documentación.

---

## 3. Instalar en otra máquina desde el repositorio

### 3.1 Poner el repositorio a disposición

El repositorio generado en la sección 2 (o el que se produzca con los modos
avanzados de la sección 4) se puede distribuir de dos formas: **USB** o
**red (HTTP)**. Ambas usan el mismo contenido; solo cambia cómo llega a la
máquina destino.

**Por USB** — el contenido se copia al USB (o se genera directamente sobre
él; la autodetección de filesystems hará la copia):

```bash
rsync -a --progress /srv/export/traduia/ /media/usuario/USB/traduia/
sync

# Verificación de la copia (el verificador viaja con el repositorio):
python3 /media/usuario/USB/traduia/verify-models.py
```

Para una validación rápida del repositorio también se puede usar
`traduia-config validate /media/usuario/USB/traduia` (ver sección 3.3).

> **Nota**: `traduia-config validate` **no** equivale al verificador de
> ficheros: solo comprueba que el `manifest.json` es un repositorio válido
> (existe, con `files[]` no vacío y al menos un set `ct2/` o `marian/`). No
> comprueba la presencia de los ficheros ni su tamaño/sha256; para la
> verificación de integridad por fichero se usa `verify-models.py` (o
> `traduia-verify-models` en el sistema).

Estructura en el USB:

```
USB/traduia/
├── manifest.json
├── verify-models.py
├── whisper-small/…
├── ct2/opus-mt-{par}/…    # (si se llevó el set ct2)
├── marian/opus-mt-{par}/… # (si se llevó el set marian)
├── wheels/…               # (opcional: dependencias Python, offline total)
├── debs/jammy/…           # (opcional: paquetes de jammy)
└── debs/noble/…           # (opcional: paquetes de noble)
```

Espacio aproximado (tamaños reales): el modo **ct2 ≈ 1.3 GB** (whisper
~0.45 GB + 10 pares ~0.8 GB) y el modo **marian ≈ 3.7 GB** (los pesos
`tf_model.h5` de TensorFlow no se exportan: no los usa el servicio).
Whisper-small está compartido, no se suma dos veces. Si el USB lleva
**ambos modos** (aditivo), la instalación usará solo uno. Es recomendable
usar un USB con espacio suficiente.

> **Nota**: el USB **no** incluye los marcadores de modo (`.use_ct2` /
> `.use_marian`). Los crea el instalador en la máquina destino según el set
> copiado; el servidor, además, los autodetecta desde el disco si no existen.

**Dependencias Python en el USB (offline total)**: los wheels generados
quedan en `wheels/` dentro del mismo repositorio y el instalador los usa
automáticamente (no hay ningún paso adicional en el cliente): los valida
antes de instalar (sección 3.6) y después instala con `--no-index`. Sin
wheels, la instalación avisa con `[WARN]` y las dependencias Python se toman
de internet (comportamiento histórico).

**Por red (HTTP)** — se publica el repositorio en un servidor de ficheros
estáticos. Requisitos: la máquina **origen** del repositorio y un
**servidor** que pueda servir ficheros estáticos por HTTP (nginx, Apache,
lighttpd, o un contenedor/servidor de ficheros cualquiera).

```bash
rsync -a /srv/export/traduia/ server:/var/www/public/models/traduia/
```

(o `scp -r` si se prefiere, aunque `rsync` permite reanudar copias grandes).

> Si el repositorio se generó con wheels, los clientes instalan también las
> **dependencias Python** desde este mismo repo HTTP (`--no-index`
> automático + `pip check`): despliegues de aula sin salida a internet. El
> instalador los **valida antes de instalar** (sección 3.6); si el repo
> declara wheels pero no se pueden descargar ni verificar, la instalación
> **aborta** con error. Sin wheels, las dependencias van a PyPI (aviso
> `[WARN]`).

> Si el repositorio lleva también `debs/<distro>/` (sección 4.5), los
> clientes pueden obtener los paquetes `traduia` y `zero-lliurex-traduia`
> desde el propio repo HTTP (útil en equipos sin acceso a los repositorios
> de LliureX): se descargan los `*.deb` y se instalan con `apt install ./…`
> (o `dpkg -i` + `apt -f install`), en el orden de la sección 3.2.

Configuración del servidor web (ejemplo con nginx):

```nginx
location /public/models/traduia/ {
    alias /var/www/public/models/traduia/;
    autoindex off;
    expires 30d;            # ficheros inmutables: cacheables
}
```

Con Apache:

```apache
Alias /public/models/traduia/ /var/www/public/models/traduia/
<Directory /var/www/public/models/traduia/>
    Options Indexes
    Require all granted
</Directory>
```

> **Proxy caching**: todo el tráfico del cliente son GET a ficheros estáticos
> (manifest.json + modelos), perfectamente cacheable. Si los modelos cambian,
> se regenera el manifest y se vuelve a sincronizar; la verificación sha256
> del cliente garantiza consistencia incluso con una caché intermedia.

> **Sin repositorio en la red de la organización**: para una prueba rápida
> o un aula puntual, el propio directorio del repositorio puede servirse
> temporalmente con el servidor web integrado de Python, ejecutando en la
> raíz del repositorio `python3 -m http.server -p PUERTO`; no es una
> solución para producción, pero permite apuntar a los clientes a
> `http://<máquina>:PUERTO/` sin configurar un servidor web.

Verificación de la publicación:

```bash
# El manifest debe responder:
curl -fsSL http://servidor:puerto/public/models/traduia/manifest.json

# Prueba de instalación completa en un equipo cliente:
install-models-traduia --url http://servidor:puerto/public/models/traduia
```

### 3.2 Preparación del equipo destino: paquetes del sistema

**Instalación previa de los paquetes del sistema (solo USB / offline total)**:

El equipo debe tener `traduia-config` disponible y el paquete `traduia`
instalado. Con origen **USB** (offline total) se instalan desde el
repositorio, en este orden:

```bash
# En los ejemplos, <distro> es el codename del equipo (jammy o noble).

# 1. zero-lliurex-traduia: proporciona traduia-config
sudo apt install /media/usuario/USB/traduia/debs/<distro>/zero-lliurex-traduia_*.deb

# 2. traduia: desde la red fallaría; se instala el fichero del repositorio
sudo apt install /media/usuario/USB/traduia/debs/<distro>/traduia_*.deb
# (o dpkg -i + apt -f install)
```

Con origen **LAN** no es necesario este paso: se asume red parcial y el
repositorio habitual por red sí dispone de `traduia`, que se instala con
`apt-get` de forma normal (sección 3.3).

Si el repositorio USB/LAN incluye `debs/<distro>/traduia_*.deb` (sección
4.5, con `<distro>` el codename del equipo), el instalador prefiere ese
fichero cuando su versión es **superior o igual** a la disponible por apt
(misma versión con build distinta incluida): instala el fichero con
`apt-get install -y <deb>`. Solo se usa `apt-get install -y traduia` si el
deb de la distribución del equipo no existe en el repositorio o su versión
es menor.

### 3.3 Instalación completa con `traduia-config` (recomendada)

Para una instalación completa de forma sencilla desde la terminal, se puede
usar la herramienta `traduia-config` (`/usr/sbin/traduia-config`), que
realiza la instalación de forma semejante a como se haría desde zero-center:

```bash
sudo traduia-config install
```

El comando `install` reproduce el flujo de zero-center:

1. **Q&A interactivo** (diálogos kdialog): modo de instalación (Cliente o
   Servidor), origen de los modelos (Internet, USB o LAN) y optimización
   (Marian por defecto u Optimized/CT2, experimental). Con origen USB/LAN,
   si el repositorio solo trae un set (`ct2` o `marian`), la optimización no
   se pregunta: se elige el set presente.
2. **Instalación del paquete** `traduia`: si el origen es USB/LAN y el
   repositorio incluye un deb de `traduia` en `debs/<distro>/` con versión
   **superior o igual** a la disponible por apt (`apt-cache policy`), se
   instala ese fichero con apt (`apt-get install -y <deb>`); en caso
   contrario se usa `apt-get install -y traduia`. En el flujo de zero-center
   el apt del paquete lo realiza el propio zero-center entre `preInstall` y
   `postInstall`; `traduia-config postinstall` aplica entonces el mismo
   criterio como *override*: si el origen es USB/LAN y el repositorio trae
   un deb de `traduia` con versión **superior o igual** a la instalada, se
   reinstala con ese fichero tras la instalación de zero-center.
3. **Descarga de modelos** desde el origen elegido: con USB/LAN se usa
   `install-models-traduia --from <dir|url>`; con Internet, sin `--from`. Si
   el repositorio lleva wheels (sección 4.4), las dependencias Python se
   instalan offline (sección 3.6). Esta descarga solo se realiza en modo
   Servidor.
4. **Entradas web**: la tarjeta de `lliurex-firefox-settings` se configura
   en ambos modos (Cliente y Servidor) si hay metas instaladas
   (`lliurex-meta-adi` / `lliurex-meta-lab-pro`) o si la comprobación de
   metas se omite (ver la opción `--disable-meta-checks` más abajo). La
   entrada Ainur (`lliurex-www`) solo se crea en modo Servidor y con el
   paquete `lliurex-www` instalado; en un cliente nunca se crea.

El origen USB/LAN se valida como repositorio: debe contener un
`manifest.json` con `files[]` y al menos un set (`ct2/` o `marian/`). En
modo **Cliente** no se descargan modelos: solo se instala el paquete y se
configura la entrada de Firefox cuando procede.

La comprobación de metas se puede omitir con la opción `--disable-meta-checks`
(equivale a `TRADUIA_SKIP_METAS_CHECK=1`): la tarjeta de Firefox se configura
aunque no haya metas instaladas. La limitación de Ainur al modo Servidor se
mantiene en todos los casos:

```bash
sudo traduia-config install --disable-meta-checks
# la opción también se acepta antes del comando:
sudo traduia-config --disable-meta-checks install
```

La opción se puede combinar con `preinstall` y `postinstall` (por ejemplo,
para reproducir el flujo de zero-center desde la terminal). En el flujo de
zero-center el equivalente es la variable `TRADUIA_SKIP_METAS_CHECK=1` en el
entorno del proceso `postinstall`.

> **Permisos**: `help`, `status` y `validate <directorio>` funcionan sin root
> (solo lectura y sin descargas). El resto (`install`, `remove`,
> `preinstall`, `postinstall` y `validate <url>`) requiere root: la
> ejecución se realiza con `sudo`, `pkexec` o desde una terminal de root; en
> otro caso se muestra el aviso `This command must be run as root` y se
> termina. Otros subcomandos: `remove` (pregunta si se eliminan los modelos y
> limpia paquete y entradas), `status` (estado de las entradas web),
> `validate <dir|url>` (validación rápida de la estructura del manifest; no
> verifica los ficheros, ver sección 3.1) y `preinstall`/`postinstall`
> (flujo interno que usa zero-center). Al completar la instalación, el
> paquete se registra como configurado en zero-center (`set-configured`); al
> eliminarse, se registra como no configurado (`set-non-configured`). El
> retorno de estas notificaciones no es crítico para la operación.

> **Offline total (USB)**: `traduia-config` proviene del paquete
> `zero-lliurex-traduia` y el paquete `traduia` debe estar instalado: se
> instalan antes desde `debs/<distro>/` del repositorio (ver sección 3.2),
> porque el `apt-get install -y traduia` interno fallaría sin red. Con
> origen **LAN** se asume red parcial: `traduia` se instala con apt de forma
> normal y este paso no es necesario.

### 3.4 Instalación por pasos y clientes del repositorio HTTP

Como alternativa a `traduia-config install`, los modelos se pueden
instalar directamente con `install-models-traduia`, indicando el origen
del repositorio:

**Opción rápida (recomendada)** — sin cp/rsync manual, el instalador copia
desde el directorio:

```bash
sudo install-models-traduia --dir /media/usuario/USB/traduia
sudo install-models-traduia optimized --dir /media/usuario/USB/traduia

# o con autodetección url/ruta local:
sudo install-models-traduia --from /media/usuario/USB/traduia
```

**Opción manual** — copia previa a la instalación:

```bash
sudo mkdir -p /opt/ai/traduia/models
sudo rsync -a --progress /media/usuario/USB/traduia/whisper-small/ /opt/ai/traduia/models/whisper-small/
sudo rsync -a --progress /media/usuario/USB/traduia/ct2/ /opt/ai/traduia/models/ct2/
# (o marian:  sudo rsync -a --progress /media/usuario/USB/traduia/marian/ /opt/ai/traduia/models/marian/)
```

> **Importante**: la estructura destino debe ser la estándar:
> `/opt/ai/traduia/models/whisper-small/` + `ct2/` o `marian/`. Si se copian
> ambos sets, el instalador detecta `complete:both` y el modo lo deciden el
> flag `optimized`/los marcadores.

**Configuración de los clientes para un repositorio HTTP**: la URL base del
repositorio (la raíz que contiene `manifest.json`) se fija con cualquiera de
estos mecanismos (**prioridad de mayor a menor**):

1. **Parámetro CLI**:
   ```bash
   install-models-traduia --url http://servidor:puerto/public/models/traduia
   install-models-traduia optimized --url http://servidor:puerto/public/models/traduia
   # o con autodetección:
   install-models-traduia --from http://servidor:puerto/public/models/traduia
   ```
2. **Variable de entorno**:
   ```bash
   export TRADUIA_MODELS_URL=http://servidor:puerto/public/models/traduia
   install-models-traduia install
   ```
3. **Fichero de configuración** (recomendado para despliegues), `/etc/traduia/models-repo.conf`:
   ```bash
   TRADUIA_MODELS_URL=http://servidor:puerto/public/models/traduia
   ```
   (puede sembrarse con puppet/ansible o por otro paquete).
4. **Sin ninguna configuración** → HuggingFace.

El instalador descarga del manifest global solo `whisper-small/` + el set de
su modo (`ct2` si `optimized`, si no `marian`), con verificación de tamaño y
sha256 por fichero y validación de completitud **antes** de descargar.

### 3.5 Verificación de los ficheros instalados

Tras instalar (desde USB o HTTP), el instalador **verifica automáticamente**
el set instalado contra el manifest del origen (tamaño + sha256 por fichero)
y aborta si algo falla. Además guarda un **manifest persistente** en
`/opt/ai/traduia/models/manifest.json` (whisper + los sets completos en el
sistema) para poder re-verificar cuando se quiera:

```bash
# Verificación posterior (herramienta del sistema, con i18n):
traduia-verify-models                        # por defecto /opt/ai/traduia/models
traduia-verify-models --mode ct2             # solo whisper + set ct2
traduia-verify-models /ruta/a/modelos

# O con el verificador del repositorio/USB:
python3 /media/usuario/USB/traduia/verify-models.py /opt/ai/traduia/models
python3 /media/usuario/USB/traduia/verify-models.py --mode marian /opt/ai/traduia/models
```

> En la **copia manual rsync** (sin `--dir`), se puede usar el verificador
> del USB con `--mode` para comprobar el set copiado: si el USB lleva ambos
> sets y solo se instaló uno, `--mode` verifica solo el instalado.

A continuación se instala el paquete `traduia` (deb o zero-center) de forma
normal. El instalador:

- Comprueba `/opt/ai/traduia/models` **antes** de descargar.
- La descarga es **por-set**: si el set pedido ya está **completo** en disco
  (copiado desde USB o de una instalación anterior) → **skip**; si no, se
  **descarga/completa** lo que falte (desde el repo HTTP si está configurado,
  o desde HuggingFace).
- En el zero-center **siempre se pregunta** el modo: `Marian` (por defecto) u
  `Optimized`/CT2 (experimental); con esa respuesta se ejecuta
  `install-models-traduia [install|optimized]`.

### 3.6 Instalación de las dependencias Python (con/sin wheels)

La descarga local **se aplica a los modelos**; las dependencias Python del
venv dependen de si el repositorio lleva wheels (sección 4.4):

- **Con wheels**: instalación **100% offline** — antes de tocar el entorno
  definitivo, el instalador realiza una **comprobación previa** en dos
  partes:
  1. **Coherencia repo↔manifest**: si el origen es un directorio (`--dir`),
     comprueba que cada wheel listado en el `manifest.json` existe en
     `wheels/` con su tamaño y sha256, y que no hay wheels presentes que el
     manifest no liste; cualquier inconsistencia aborta la instalación.
  2. **Completitud del repositorio de wheels (paquetes Python)**: en un
     **venv temporal** ejecuta
     `pip install --dry-run --no-index --find-links` con el árbol completo
     de dependencias (incluido torch y, en modos con CT2, `ctranslate2`);
     si la resolución falla, el repositorio de wheels está incompleto y la
     instalación aborta con error, sin haber modificado nada.
  Superada esa comprobación, se instala con
  `pip install --no-index --find-links` contra `wheels/`.
- **Sin wheels**: el instalador **descarga las dependencias de internet**
  (PyPI + índice CPU de torch), avisando con `[WARN]` antes de empezar. Solo
  se llega aquí si el repositorio no declara wheels; si los declara y no se
  pueden descargar ni verificar (caso HTTP), la instalación aborta.

Comportamiento común de la instalación de dependencias:

- Todos los fallos de `pip` son **fatales** y quedan registrados en
  `/var/log/traduia-install.log`; ante un error se muestran las últimas 60
  líneas del registro junto al mensaje.
- La consistencia del entorno se verifica siempre con `pip check` al final
  de la instalación de dependencias (con o sin wheels).
- El venv (`/opt/ai/traduia/venv`) se **recrea limpio** en cada instalación
  (`python3 -m venv --clear`) y se prepara **antes** de la descarga de los
  modelos (torch incluido); requiere el requisito previo de `python3-venv`
  descrito al inicio del documento. Con wheels simplemente no necesita salir
  a la red.

### 3.7 Verificación tras la instalación

```bash
# Marcadores de modo (los crea el instalador):
#   set ct2    -> existe .use_ct2, no existe .use_marian
#   set marian -> existe .use_marian, no existe .use_ct2
ls -la /opt/ai/traduia/models/.use_ct2 /opt/ai/traduia/models/.use_marian

# El servidor debe arrancar y abrir el navegador sin descargar nada:
/usr/bin/traduia

# Se comprueba que no hay tráfico de modelos a huggingface.co:
# (sin configuración TRADUIA_MODELS_URL y con modelos completos, no debe
#  haber conexiones salientes al instalar)
```

También es posible comprobar el estado de las entradas web con
`traduia-config status` (ver sección 3.3).

### 3.8 Cómo decide el servidor el modo de modelos (ct2/marian)

Al arrancar, `traduia_server.py` muestra en consola qué modo usa y por qué:

- **Un solo marcador presente** → es un *override* explícito: `.use_ct2` →
  CT2, `.use_marian` → Marian. Se valida contra el disco; si el set marcado
  no está completo, avisa y **cae al otro set disponible** (fallback).
- **Ambos marcadores presentes** → **prioridad Marian** (con fallback a CT2
  si Marian no está completo).
- **Sin marcadores** → **detección desde disco**; si ambos sets están
  completos, **prioridad Marian**.
- **Sin ningún set completo** → error claro al arrancar indicando la
  ejecución de `install-models-traduia install`.

> **Nota**: el instalador **nunca deja ambos marcadores** (son excluyentes).
> La situación "ambos presentes" solo puede darse si se crean manualmente
> (p.ej. `touch /opt/ai/traduia/models/.use_marian` junto a un `.use_ct2`
> existente) — en ese caso actúa el desempate: prioridad Marian, con fallback
> a CT2 si Marian no está completo en disco.

Cualquier problema al cargar un modelo (Whisper, Marian o CT2) se muestra
como `[WARN]` en la consola. El servidor carga siempre los modelos desde
disco con `local_files_only`/offline, por lo que en ejecución nunca se
descarga nada.

---

## 4. Modos avanzados: crear el repositorio por partes

La sección 2 muestra la forma más sencilla (`full`). Esta sección detalla
cada parte por separado, para los casos en que se quiera controlar cada paso
o partir de material ya existente (p. ej. una máquina con los modelos ya
instalados).

### 4.1 Preparar los modelos en la máquina origen

En una máquina con Internet, los modelos se descargan una sola vez:

```bash
# Modelos originales (Marian, sin cuantizar):
install-models-traduia install

# Modelos optimizados (CTranslate2, más rápidos; experimentales):
install-models-traduia optimized

# Ambos sets en la misma ejecución (Marian primero; prioridad Marian):
install-models-traduia all
```

> Con `all` quedan instalados los dos sets y el marcador efectivo es
> `.use_marian` (prioridad Marian); para usar el modo optimizado hay que
> renombrar a mano el marcador `.use_marian` por `.use_ct2` en
> `/opt/ai/traduia/models` (el instalador lo avisa al terminar). Con
> `all optimized` el marcador queda en `.use_ct2` sin aviso.

> Sin parámetros, `install-models-traduia` muestra la ayuda (y `--help`).
> Se usa `install` (o `install optimized`) para instalar explícitamente.

Los modelos quedan en `/opt/ai/traduia/models` con esta estructura:

```
/opt/ai/traduia/models/
├── .use_ct2 (o .use_marian)   # marcador del modo efectivo — SOLO uno, excluyente
├── whisper-small/              # STT (faster-whisper, formato ct2)
├── ct2/                        # solo si se instaló optimized
│   └── opus-mt-{par}/
└── marian/                     # solo si se instaló sin optimized
    └── opus-mt-{par}/
```

> **Marcadores**: el instalador crea **uno solo** (`.use_ct2` o
> `.use_marian`), el del último modo ejecutado; son excluyentes. Si se
> ejecutan ambos comandos en secuencia, queda el del último.

> Los marcadores **no se publican** en el repositorio: `traduia-make-repo`
> solo copia `whisper-small/` y los sets pedidos más el `manifest.json`. El
> instalador crea el marcador adecuado en cada cliente y el servidor lo
> autodetecta desde el disco si no existe.

### 4.2 Generar el repositorio desde modelos locales

Con los modelos ya presentes en `/opt/ai/traduia/models` (sección 4.1), el
repositorio se genera con `traduia-make-repo` indicando el directorio de
origen:

```bash
# Modo original (Marian):
traduia-make-repo /opt/ai/traduia/models marian /srv/export/traduia

# Modo optimizado (CTranslate2):
traduia-make-repo /opt/ai/traduia/models ct2 /srv/export/traduia

# Ambos sets en una sola ejecución:
traduia-make-repo /opt/ai/traduia/models all /srv/export/traduia
```

- **Validación**: el script comprueba que el/los set(s) pedidos estén
  completos (whisper-small + los 10 pares; con `all`, ambos sets) y se niega
  a generar un repositorio incompleto, listando lo que falta. Para el set
  ct2 acepta ambos layouts de vocabulario: `vocabulary.txt` (conversión
  local) o `vocab.json` (repos pre-convertidos como
  `mijuanlo/opus-mt-*-ct2-int8`).
- **Exclusiones**: los artefactos de HuggingFace (`whisper-small/.cache/…`,
  ficheros no legibles o basura de descarga) y los pesos `tf_model.h5`
  (TensorFlow, no utilizados por el servicio) **no se copian** al
  repositorio ni se listan en el manifest.
- **Aditivo**: se ejecuta una vez por cada set que se quiera llevar,
  apuntando siempre al **mismo** directorio de salida. `whisper-small` solo
  se copia en la primera ejecución — **nunca se duplica**. El `mode` del
  manifest se detecta del contenido (`ct2` | `marian` | `both`). Re-ejecutar
  el mismo modo refresca los ficheros (idempotente, útil al actualizar
  modelos).
- **Hardlink vs copia**: se **autodetecta** comparando el sistema de ficheros
  de origen y destino — mismo filesystem → hardlinks (rápido); distinto
  (p.ej. escribir directo a un USB) → copia automática. `--copy` fuerza la
  copia opcionalmente.

### 4.3 Descarga directa de HuggingFace (`fetch`)

Sin un directorio local de modelos, los modelos se pueden bajar directamente
de HuggingFace (aditivo, par a par); es el mismo mecanismo que emplea
`full`:

```bash
# Solo Marian (whisper-small + los 10 pares marian):
traduia-make-repo fetch marian /srv/export/traduia

# Solo optimizado/CT2 (pre-convertidos, sin conversión local):
traduia-make-repo fetch ct2 /srv/export/traduia

# Ambos sets, marian primero (prioridad):
traduia-make-repo fetch all /srv/export/traduia
```

- **Fuentes**: whisper-small desde `mijuanlo/whisper-small-ct2-int8`
  (fallback `Systran/faster-whisper-small`); marian desde
  `mijuanlo/opus-mt-{par}` (fallback `Helsinki-NLP/opus-mt-{par}`); ct2
  desde los repos **pre-convertidos** `mijuanlo/opus-mt-{par}-ct2-int8`
  (no hay conversión local). Si un repo pre-convertido no existe, se
  informa del par, el `manifest.json` se regenera igualmente (los pares ya
  descargados se conservan) y el comando termina con error: re-ejecutar el
  mismo `fetch` reintenta los pares que faltan.
- **Requisito**: `fetch` necesita el paquete Python `huggingface_hub` en el
  `python3` del sistema (`pip install huggingface_hub`); el resto de
  subcomandos solo usa la librería estándar.
- **Aditivo**: los pares ya completos en el directorio de salida se omiten;
  se puede ejecutar una vez por set (o con `all`) sobre un directorio ya
  generado. Tras el `fetch` se regenera el `manifest.json` (el `mode` se
  detecta del contenido, incluyendo `both`) y se escribe/actualiza el
  verificador `verify-models.py` (sección 2.3), igual que en el resto de
  subcomandos.
- **Combinable**: `fetch` + `wheels` + `debs` sobre el mismo directorio de
  salida producen un repositorio completo (modelos + dependencias Python +
  paquetes del sistema) para una instalación totalmente offline.

### 4.4 Dependencias Python (wheels) — opcional, recomendado

Los pasos anteriores exportan **solo los modelos**: la instalación seguirá
necesitando internet para las dependencias Python del venv (pip, fastapi,
torch, …). Para que el repositorio (HTTP o USB) permita una instalación
**100% offline**, se añaden también los wheels sobre el **mismo** directorio
de salida (aditivo, igual que los sets; re-ejecutar refresca los wheels):

```bash
traduia-make-repo wheels /srv/export/traduia
```

- `pip download` resuelve el **árbol completo de dependencias** (incluidas
  las transitivas) como **wheels binarios** (`--only-binary=:all:`), para
  **jammy (cp310)** y **noble (cp312)**, amd64 (`manylinux*`). La máquina que
  exporta solo necesita pip ≥ 20.3 (jammy/noble lo cumplen).
- **torch CPU** se descarga de su índice oficial
  (`https://download.pytorch.org/whl/cpu`), que ya aloja todas sus
  dependencias (y evita el torch CUDA de PyPI, ~10× mayor).
- La lista incluye explícitamente `exceptiongroup`, necesaria por `anyio` en
  **Python 3.10**: al terminar, el propio comando comprueba su presencia en
  `wheels/` y aborta con error si falta, de modo que no se genera nunca un
  repositorio de wheels (paquetes Python) 3.10 incompleto.
- Si alguna descarga de `pip download` falla, se muestra la salida de pip
  (últimas 60 líneas) junto al error, en lugar de descartarla.
- Los wheels quedan en `wheels/` y se incorporan al `manifest.json`
  (verificables con la sección 2.3, igual que los modelos); el subcomando
  también escribe/actualiza el verificador `verify-models.py`.
- Al instalar desde USB/LAN, `install-models-traduia` los detecta, los
  **valida antes de instalar** (sección 3.6) y los usa con
  `pip install --no-index --find-links` (más `pip check`). Sin wheels, avisa
  con `[WARN]` y las dependencias se toman de internet (comportamiento
  histórico); en cambio, si el repositorio **declara** wheels y estos no se
  pueden descargar ni verificar (caso HTTP), la instalación **aborta** con
  error en lugar de caer a internet.

### 4.5 Paquetes del sistema (debs) — opcional, recomendado

Para una instalación **100% offline** también deben incluirse los paquetes
`traduia` y `zero-lliurex-traduia` (este último proporciona
`traduia-config`). Sin ellos, en un equipo sin red: (1) `traduia-config` no
está disponible y (2) `apt-get install traduia` no puede completarse. Se
añaden sobre el **mismo** directorio de salida (aditivo, igual que los sets
y los wheels; re-ejecutar refresca los debs de la distro pedida):

```bash
# Ambas distribuciones (jammy y noble):
traduia-make-repo debs /srv/export/traduia

# Solo una distribución:
traduia-make-repo debs /srv/export/traduia jammy
traduia-make-repo debs /srv/export/traduia noble

# Apuntando al repositorio con los debs más actualizados:
traduia-make-repo debs /srv/export/traduia all \
    --url-jammy <URL_REPO_JAMMY> \
    --url-noble <URL_REPO_NOBLE>
```

- **Mecanismo independiente del sistema**: los debs se obtienen leyendo los
  **índices apt del repositorio por HTTP**
  (`dists/<suite>/main/binary-amd64/Packages.gz`) con python3 (no usa `apt`
  ni `apt-get download`), así que una sola máquina — sea jammy o noble —
  puede bajar los debs de **ambas** distribuciones. Por cada distro se
  recorren las suites `<s>`, `<s>-updates` y `<s>-security` (las ausentes se
  omiten) y se elige la **versión mayor** disponible de cada paquete,
  verificando el `SHA256` del índice.
- **URLs por distribución**: por defecto se usa `http://lliurex.net/jammy` y
  `http://lliurex.net/noble`. Con `--url-jammy <url>` y `--url-noble <url>`
  se apunta al repositorio desde el que se quieran tomar los debs más
  actualizados (acepta `file://` para pruebas). Ambas opciones se aceptan
  antes o después del resto de argumentos.
- **Layout**: cada distro en su subdirectorio — `debs/jammy/` y
  `debs/noble/`. Al re-ejecutar solo se refresca el subdirectorio de la
  distro pedida.
- Regenera el `manifest.json` (los debs quedan indexados con size+sha256 y
  verificables con la sección 2.3, igual que los modelos) y
  escribe/actualiza el verificador `verify-models.py`.
- En el cliente, con origen **USB (offline total)** se instalan desde el
  subdirectorio de **su** distribución (ver sección 3.2), primero
  `zero-lliurex-traduia` (aporta `traduia-config`) y después `traduia`,
  porque desde la red fallaría. Con origen **LAN** no hace falta: se asume
  red parcial y el repositorio habitual por red sí dispone de `traduia`
  para instalarlo con `apt-get` de forma normal.
- Las dependencias del sistema de estos paquetes (python3-venv, kdialog, jq,
  lliurex-firefox-settings, …) deben estar disponibles en el equipo offline
  (caché apt, repositorios del aula o medios de instalación).

### 4.6 Publicación HTTP: requisitos del servidor

Para distribuir el repositorio por red (sección 3.1) solo se necesita una
máquina **servidor** que pueda servir ficheros estáticos por HTTP (nginx,
Apache, lighttpd, o un contenedor/servidor de ficheros cualquiera); no hace
falta ninguna herramienta de TraduIA en el servidor. Los detalles de la
configuración web y de los clientes están en la sección 3.1 y 3.4.

---

## 5. Apéndice — Referencia de comandos (salida de `--help`)

Las salidas siguientes son las literales de cada comando (en locale `C`) en
el momento de escribir este documento.

### 5.1 `install-models-traduia` (sin parámetros / `--help`)

```text
Usage: install-models-traduia [options] [mode]

  (no parameters)  this help
  install           install the standard (Marian) model set from the
                    configured source (default: internet)
  optimized         install the optimized (CTranslate2) model set
                    (experimental); combinable with "install"
  all               install both model sets (Marian and optimized/CT2)
                    in the same run; Marian takes priority; combinable
                    with "install" and "optimized"
  --url <url>       repository base URL (contains manifest.json)
  --dir <path>      local repository directory (USB, mounted drive)
  --from <url|path> auto-detect: URL or local path
  --detect          print model set state (complete:* / partial / none)
  help, --help, -h  this help
```

### 5.2 `traduia-make-repo` (sin parámetros: usage)

```text
Usage: traduia-make-repo <models_dir> <ct2|marian|all> <output_dir> [--copy]

Generates a static manifest.json (with size+sha256) for a TraduIA model repo.
The output directory is shared: whisper-small/ + one or both model sets + manifest.json
It can be served statically over HTTP or copied to a USB drive.
Mode 'all' assembles both model sets (marian and ct2).

The tool is additive: run it once per set you want in the same output
directory. whisper-small is only copied on the first run (never duplicated).

Hardlinks are used when source and destination are on the same filesystem;
otherwise files are copied automatically (e.g. to a USB drive).

Options:
  --copy    Force copying instead of hardlinking (optional; auto-detected by default)

Or download the models directly from HuggingFace (additive, par a par):
  traduia-make-repo fetch <ct2|marian|all> <output_dir>
Or export the Python wheels for fully offline installs (additive):
  traduia-make-repo wheels <output_dir>
Or download the system packages (traduia, zero-lliurex-traduia) from an apt repository over HTTP, for one or both distributions:
  traduia-make-repo debs <output_dir> [jammy|noble|all] [--url-jammy <url>] [--url-noble <url>]
Or build a fully offline repository in one command (all models from HuggingFace + Python wheels + system debs for jammy and noble):
  traduia-make-repo full <output_dir> [--url-jammy <url>] [--url-noble <url>]
```

### 5.3 `traduia-config help`

```text
Usage: traduia-config [command] [--disable-meta-checks]

  (no parameters)  interactive: detects the traduia package and offers
                    Install or Remove (only Install if not installed)
  install           preinstall + apt-get install traduia + postinstall
  remove            ask about models + apt-get remove + cleanup
  preinstall        Q&A (mode/source/optimization) + markers (zero-center)
  postinstall       model download + web entries (zero-center)
  status            web entries status
  validate <dir|url>  quick models repository validation
  --disable-meta-checks  skip the LliureX metas check (web entries)
  help              this help
```

### 5.4 `traduia-verify-models` / `verify-models.py`

Estas herramientas **no tienen opción `--help`** (su primer argumento, si no
es `--mode`, se interpreta como directorio). Su uso es:

```text
traduia-verify-models [--mode ct2|marian] [directorio]
python3 verify-models.py [--mode ct2|marian] [directorio]
```

- `directorio` por defecto: `/opt/ai/traduia/models` (`traduia-verify-models`)
  o el directorio actual (`verify-models.py`).
- `--mode ct2|marian` verifica solo whisper + ese set; falla si el set pedido
  no está en el manifest.
- Comportamiento y salidas: sección 2.3.
