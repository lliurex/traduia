# HowTo: exportar los modelos de TraduIA (repo HTTP e instalación offline con USB)

Este documento cubre la **exportación y distribución de los modelos** de
TraduIA en dos casos de uso:

- **Caso A — Repositorio HTTP**: la publicación de los modelos en una máquina
  servidor, para que las instalaciones los descarguen desde una URL propia
  (sin depender de HuggingFace).
- **Caso B — USB / instalación offline**: el transporte de los modelos en un
  disco USB y su instalación en equipos sin acceso a Internet.

Ambos casos comparten los pasos comunes de preparación y generación del
repositorio (secciones 1-3); la diferencia está en cómo se distribuye y cómo
se consume (secciones 4 y 5).

---

## 1. Parte común — Preparar los modelos (máquina origen)

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

## 2. Parte común — Generación del repositorio con `traduia-make-repo`

El repositorio tiene un **único `manifest.json` en la raíz** que cubre todo
el contenido (`whisper-small/` + los sets presentes), con `size` + `sha256`
por fichero:

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

### 2.1 Descarga directa de HuggingFace (`fetch`)

Sin un directorio local de modelos, el repositorio se puede generar
descargando los modelos directamente de HuggingFace (aditivo, par a par):

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
  detecta del contenido, incluyendo `both`).
- **Combinable**: `fetch` + `wheels` + `debs` sobre el mismo directorio de
  salida producen un repositorio completo (modelos + dependencias Python +
  paquetes del sistema) para una instalación totalmente offline.

### 2.2 Dependencias Python (wheels) — opcional, recomendado

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
- Los wheels quedan en `wheels/` y se incorporan al `manifest.json`
  (verificables con la sección 3, igual que los modelos).
- Al instalar desde USB/LAN, `install-models-traduia` los detecta y usa
  `pip install --no-index --find-links` (más `pip check` al final). Sin
  wheels, avisa con `[WARN]` y las dependencias se toman de internet
  (comportamiento histórico).

Estructura resultante:

```
/srv/export/traduia/
├── manifest.json          # manifest GLOBAL (todo el contenido)
├── whisper-small/…        # UNA sola copia, compartida
├── ct2/opus-mt-{par}/…    # (solo si se añadió el set ct2)
├── marian/opus-mt-{par}/… # (solo si se añadió el set marian)
├── wheels/…               # (si se ejecutó "wheels": deps Python, offline total)
└── debs/…                 # (si se ejecutó "debs": paquetes traduia y zero-lliurex-traduia)
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

### 2.3 Paquetes del sistema (debs) — opcional, recomendado

Para una instalación **100% offline** también deben incluirse los paquetes
`traduia` y `zero-lliurex-traduia` (este último proporciona
`traduia-config`). Sin ellos, en un equipo sin red: (1) `traduia-config` no
está disponible y (2) `apt-get install traduia` no puede completarse. Se
añaden sobre el **mismo** directorio de salida (aditivo, igual que los sets y
los wheels; re-ejecutar refresca los debs):

```bash
traduia-make-repo debs /srv/export/traduia
```

- Usa `apt-get download` en la máquina origen (no requiere root) para obtener
  **solo** esos dos paquetes desde las fuentes apt configuradas (la máquina
  origen debe tener acceso a ellas: internet o el repositorio de LliureX), y
  los copia a `debs/` del directorio de salida. `apt-get download` no trae
  las dependencias de los paquetes.
- Regenera el `manifest.json` (los debs quedan indexados con size+sha256 y
  verificables con la sección 3, igual que los modelos).
- En el cliente, con origen **USB (offline total)** se instalan desde el
  repositorio, primero `zero-lliurex-traduia` (aporta `traduia-config`) y
  después `traduia`, porque desde la red fallaría (ver sección 5.2). Con
  origen **LAN** no hace falta: se asume red parcial y el repositorio
  habitual por red sí dispone de `traduia` para instalarlo con `apt-get` de
  forma normal.
- Las dependencias del sistema de estos paquetes (python3-venv, kdialog, jq,
  lliurex-firefox-settings, …) deben estar disponibles en el equipo offline
  (caché apt, repositorios del aula o medios de instalación).

## 3. Parte común — Verificación de la integridad

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

## 4. Caso A — Publicar como repositorio HTTP

### 4.1 Requisitos

- La máquina **origen** de las secciones 1-3.
- Una máquina **servidor** que pueda servir ficheros estáticos por HTTP
  (nginx, Apache, lighttpd, o un contenedor/servidor de ficheros cualquiera).

### 4.2 Transferir los ficheros

```bash
rsync -a /srv/export/traduia/ server:/var/www/public/models/traduia/
```

(o `scp -r` si se prefiere, aunque `rsync` permite reanudar copias grandes).

> Si el repositorio se generó con `wheels` (sección 2.2), los clientes
> instalan también las **dependencias Python** desde este mismo repo HTTP
> (`--no-index` automático + `pip check`): despliegues de aula sin salida a
> internet. Sin wheels, las dependencias van a PyPI (aviso `[WARN]`).

> Si el repositorio lleva también `debs/` (sección 2.3), los clientes pueden
> obtener los paquetes `traduia` y `zero-lliurex-traduia` desde el propio
> repo HTTP (útil en equipos sin acceso a los repositorios de LliureX): se
> descargan los `*.deb` y se instalan con `apt install ./…` (o `dpkg -i` +
> `apt -f install`), en el orden de la sección 5.2.

### 4.3 Configurar el servidor web (ejemplo con nginx)

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

Para una prueba rápida local (solo verificación, no apta para producción):

```bash
cd /srv/export/traduia && python3 -m http.server 8080
```

### 4.4 Configuración de los clientes

La URL base del repositorio (la raíz que contiene `manifest.json`) se fija
con cualquiera de estos mecanismos (**prioridad de mayor a menor**):

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

### 4.5 Verificación

```bash
# El manifest debe responder:
curl -fsSL http://servidor:puerto/public/models/traduia/manifest.json

# Prueba de instalación completa en un equipo cliente:
install-models-traduia --url http://servidor:puerto/public/models/traduia
```

---

## 5. Caso B — Instalación offline con USB

### 5.1 Copia al USB

El contenido se genera con las secciones 1-3 y se copia al USB (o se genera
directamente sobre él; la autodetección de filesystems hará la copia):

```bash
rsync -a --progress /srv/export/traduia/ /media/usuario/USB/traduia/
sync

# Verificación de la copia (el verificador viaja con el repositorio):
python3 /media/usuario/USB/traduia/verify-models.py
```

Para una validación rápida del repositorio también se puede usar
`traduia-config validate /media/usuario/USB/traduia` (ver sección 5.2.2).

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
├── whisper-small/…
├── ct2/opus-mt-{par}/…    # (si se llevó el set ct2)
├── marian/opus-mt-{par}/… # (si se llevó el set marian)
├── wheels/…               # (opcional: dependencias Python, offline total)
└── debs/…                 # (opcional: paquetes traduia y zero-lliurex-traduia)
```

Espacio aproximado (tamaños reales): el modo **ct2 ≈ 1.3 GB** (whisper
~0.45 GB + 10 pares ~0.8 GB) y el modo **marian ≈ 3.7 GB** (los pesos
`tf_model.h5` de TensorFlow no se exportan: no los usa el servicio).
Whisper-small está compartido, no se suma dos veces. Si el USB lleva
**ambos modos** (sección 2, aditivo), la instalación usará solo uno. Es
recomendable usar un USB con espacio suficiente.

> **Nota**: el USB **no** incluye los marcadores de modo (`.use_ct2` /
> `.use_marian`). Los crea el instalador en la máquina destino según el set
> copiado; el servidor, además, los autodetecta desde el disco si no existen.

### 5.1b Dependencias Python en el USB (offline total)

Los wheels se generan con la sección **2.2** antes de copiar al USB: quedan
en `wheels/` dentro del mismo repositorio y el instalador los usa
automáticamente (no hay ningún paso adicional en el cliente). Sin wheels, la
instalación avisa con `[WARN]` y las dependencias Python se toman de
internet (comportamiento histórico).

### 5.2 Instalación en un equipo sin red

**Instalación previa de los paquetes del sistema (solo USB / offline total)**:

El equipo debe tener `traduia-config` disponible y el paquete `traduia`
instalado. Con origen **USB** (offline total) se instalan desde el
repositorio, en este orden:

```bash
# 1. zero-lliurex-traduia: proporciona traduia-config
sudo apt install /media/usuario/USB/traduia/debs/zero-lliurex-traduia_*.deb

# 2. traduia: desde la red fallaría; se instala el fichero del repositorio
sudo apt install /media/usuario/USB/traduia/debs/traduia_*.deb
# (o dpkg -i + apt -f install)
```

Con origen **LAN** no es necesario este paso: se asume red parcial y el
repositorio habitual por red sí dispone de `traduia`, que se instala con
`apt-get` de forma normal (sección 5.2.2).

Si el repositorio USB/LAN incluye `debs/traduia_*.deb` (sección 2.3), el
instalador prefiere ese fichero cuando su versión es **superior o igual** a la
disponible por apt (misma versión con build distinta incluida): instala el
fichero con `apt-get install -y <deb>`. Solo se usa `apt-get install -y
traduia` si el deb no existe en el repositorio o su versión es menor.

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

### 5.2.1 Verificación de los ficheros instalados

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

### 5.2.2 Instalación completa desde la terminal (`traduia-config`)

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
   repositorio incluye un deb de `traduia` en `debs/` con versión **superior
   o igual** a la disponible por apt (`apt-cache policy`), se instala ese
   fichero con apt (`apt-get install -y <deb>`); en caso contrario se usa
   `apt-get install -y traduia`. En el flujo de zero-center el apt del
   paquete lo realiza el propio zero-center entre `preInstall` y
   `postInstall`; `traduia-config postinstall` aplica entonces el mismo
   criterio como *override*: si el origen es USB/LAN y el repositorio trae un
   deb de `traduia` con versión **superior o igual** a la instalada, se
   reinstala con ese fichero tras la instalación de zero-center.
3. **Descarga de modelos** desde el origen elegido: con USB/LAN se usa
   `install-models-traduia --from <dir|url>`; con Internet, sin `--from`. Si
   el repositorio lleva wheels (sección 2.2), las dependencias Python se
   instalan offline (sección 5.3). Esta descarga solo se realiza en modo
   Servidor.
4. **Entradas web**: la tarjeta de `lliurex-firefox-settings` se configura en
   ambos modos (Cliente y Servidor) si hay metas instaladas
   (`lliurex-meta-adi` / `lliurex-meta-lab-pro`) o si la comprobación de
   metas se omite (ver la opción `--disable-meta-checks` más abajo). La
   entrada Ainur (`lliurex-www`) solo se crea en modo Servidor y con el
   paquete `lliurex-www` instalado; en un cliente nunca se crea.

El origen USB/LAN se valida como repositorio: debe contener un
`manifest.json` con `files[]` y al menos un set (`ct2/` o `marian/`). En modo
**Cliente** no se descargan modelos: solo se instala el paquete y se
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
> verifica los ficheros, ver sección 5.1) y `preinstall`/`postinstall` (flujo
> interno que usa zero-center). Al completar la instalación, el paquete se
> registra como configurado en zero-center (`set-configured`); al eliminarse,
> se registra como no configurado (`set-non-configured`). El retorno de
> estas notificaciones no es crítico para la operación.

> **Offline total (USB)**: `traduia-config` proviene del paquete
> `zero-lliurex-traduia` y el paquete `traduia` debe estar instalado: se
> instalan antes desde `debs/` del repositorio (ver sección 5.2), porque el
> `apt-get install -y traduia` interno fallaría sin red. Con origen **LAN** se
> asume red parcial: `traduia` se instala con apt de forma normal y este paso
> no es necesario.

### 5.3 Instalación con/sin wheels (lectura recomendada)

La descarga local **se aplica a los modelos**; las dependencias Python del
venv dependen de si el repositorio lleva wheels (sección 2.2):

- **Con wheels**: instalación **100% offline** — el instalador usa
  `pip install --no-index --find-links` contra `wheels/` del USB/repo y
  verifica la consistencia con `pip check` (si faltara algo, error claro:
  sin red de la que echar mano).
- **Sin wheels**: el instalador crea el venv localmente (sin compilación:
  todo son wheels binarios) pero **descarga las dependencias de internet**
  (PyPI + índice CPU de torch), avisando con `[WARN]` antes de empezar.

El venv (`/opt/ai/traduia/venv`) se crea siempre en la máquina destino; con
wheels simplemente no necesita salir a la red.

### 5.4 Verificación tras la instalación

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
`traduia-config status` (ver sección 5.2.2).

### 5.5 Cómo decide el servidor el modo de modelos (ct2/marian)

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