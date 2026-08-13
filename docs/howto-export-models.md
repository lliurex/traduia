# HowTo: exportar los modelos de TraduIA (repo HTTP e instalación offline con USB)

Este documento cubre la **exportación y distribución de los modelos** de
TraduIA en dos casos de uso:

- **Caso A — Repositorio HTTP**: publicar los modelos en una máquina servidor
  para que las instalaciones los descarguen desde una URL propia (sin
  depender de HuggingFace).
- **Caso B — USB / instalación offline**: llevar los modelos en un disco USB
  e instalarlos en equipos sin acceso a Internet.

Ambos casos comparten los pasos comunes de preparación y generación del
repositorio (secciones 1-3); la diferencia está en cómo se distribuye y cómo
se consume (secciones 4 y 5).

---

## 1. Parte común — Preparar los modelos (máquina origen)

En una máquina con Internet, descargue los modelos (una sola vez):

```bash
# Modelos originales (Marian, sin cuantizar):
install-models-traduia

# Modelos optimizados (CTranslate2, más rápidos; experimentales):
install-models-traduia optimized
```

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

## 2. Parte común — Generar el repositorio con `traduia-make-repo`

El repositorio tiene un **único `manifest.json` en la raíz** que cubre todo
el contenido (`whisper-small/` + los sets presentes), con `size` + `sha256`
por fichero:

```bash
# Modo original (Marian):
traduia-make-repo /opt/ai/traduia/models marian /srv/export/traduia

# Modo optimizado (CTranslate2):
traduia-make-repo /opt/ai/traduia/models ct2 /srv/export/traduia
```

- **Validación**: el script comprueba que el set pedido esté completo
  (whisper-small + los 10 pares) y se niega a generar un repositorio
  incompleto, listando lo que falta. Para el set ct2 acepta ambos layouts de
  vocabulario: `vocabulary.txt` (conversión local) o `vocab.json` (repos
  pre-convertidos como `mijuanlo/opus-mt-*-ct2-int8`).
- **Exclusiones**: los artefactos de HuggingFace (`whisper-small/.cache/…`,
  ficheros no legibles o basura de descarga) y los pesos `tf_model.h5`
  (TensorFlow, no utilizados por el servicio) **no se copian** al
  repositorio ni se listan en el manifest.
- **Aditivo**: ejecútelo una vez por cada set que quiera llevar, apuntando
  siempre al **mismo** directorio de salida. `whisper-small` solo se copia
  en la primera ejecución — **nunca se duplica**. El `mode` del manifest se
  detecta del contenido (`ct2` | `marian` | `both`). Re-ejecutar el mismo
  modo refresca los ficheros (idempotente, útil al actualizar modelos).
- **Hardlink vs copia**: se **autodetecta** comparando el sistema de ficheros
  de origen y destino — mismo filesystem → hardlinks (rápido); distinto
  (p.ej. escribir directo a un USB) → copia automática. `--copy` fuerza la
  copia opcionalmente.

Estructura resultante:

```
/srv/export/traduia/
├── manifest.json          # manifest GLOBAL (todo el contenido)
├── whisper-small/…        # UNA sola copia, compartida
├── ct2/opus-mt-{par}/…    # (solo si se añadió el set ct2)
└── marian/opus-mt-{par}/… # (solo si se añadió el set marian)
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

## 3. Parte común — Verificar la integridad

`traduia-make-repo` genera junto al manifest un verificador
(`verify-models.py`). Compruebe que cada fichero coincide con su sha256:

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

(o `scp -r` si prefiere, aunque `rsync` permite reanudar copias grandes).

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
> regenere el manifest y vuelva a sincronizar; la verificación sha256 del
> cliente garantiza consistencia incluso con una caché intermedia.

Para una prueba rápida local (solo verificación, no apta para producción):

```bash
cd /srv/export/traduia && python3 -m http.server 8080
```

### 4.4 Configurar los clientes

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
   install-models-traduia
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

### 5.1 Copiar al USB

Genere el contenido con las secciones 1-3 y cópielo al USB (o genere
directamente sobre él; la autodetección de filesystems hará la copia):

```bash
rsync -a --progress /srv/export/traduia/ /media/usuario/USB/traduia/
sync

# Verificar la copia (el verificador viaja con el repositorio):
python3 /media/usuario/USB/traduia/verify-models.py
```

Estructura en el USB:

```
USB/traduia/
├── manifest.json
├── whisper-small/…
├── ct2/opus-mt-{par}/…    # (si se llevó el set ct2)
└── marian/opus-mt-{par}/… # (si se llevó el set marian)
```

Espacio aproximado (tamaños reales): el modo **ct2 ≈ 1.3 GB** (whisper
~0.45 GB + 10 pares ~0.8 GB) y el modo **marian ≈ 3.7 GB** (los pesos
`tf_model.h5` de TensorFlow no se exportan: no los usa el servicio).
Whisper-small está compartido, no se suma dos veces. Si el USB lleva
**ambos modos** (sección 2, aditivo), la instalación usará solo uno. Use un
USB con espacio suficiente.

> **Nota**: el USB **no** incluye los marcadores de modo (`.use_ct2` /
> `.use_marian`). Los crea el instalador en la máquina destino según el set
> copiado; el servidor, además, los autodetecta desde el disco si no existen.

### 5.2 Instalar en un equipo sin red

**Opción rápida (recomendada)** — sin cp/rsync manual, el instalador copia
desde el directorio:

```bash
sudo install-models-traduia --dir /media/usuario/USB/traduia
sudo install-models-traduia optimized --dir /media/usuario/USB/traduia

# o con autodetección url/ruta local:
sudo install-models-traduia --from /media/usuario/USB/traduia
```

**Opción manual** — copiar ANTES de instalar:

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

> En la **copia manual rsync** (sin `--dir`), puede usar el verificador del
> USB con `--mode` para comprobar el set copiado: si el USB lleva ambos sets
> y solo instaló uno, `--mode` verifica solo el instalado.

A continuación instale el paquete `traduia` (deb o zero-center) de forma
normal. El instalador:

- Comprueba `/opt/ai/traduia/models` **antes** de descargar.
- La descarga es **por-set**: si el set pedido ya está **completo** en disco
  (copiado desde USB o de una instalación anterior) → **skip**; si no, se
  **descarga/completa** lo que falte (desde el repo HTTP si está configurado,
  o desde HuggingFace).
- En el zero-center **siempre se pregunta** el modo: `Marian` (por defecto) u
  `Optimized`/CT2 (experimental); con esa respuesta se ejecuta
  `install-models-traduia [optimized]`.

### 5.3 Limitación importante (leer)

La **no descarga se aplica a los modelos**. El instalador también crea el
entorno virtual (`/opt/ai/traduia/venv`) e instala sus dependencias Python
(fastapi, torch, faster-whisper, transformers…), lo que **sí requiere red**
(o un mirror pip local) en la primera instalación. Para una instalación
100% offline debe disponer además de una caché/mirror de pip, o un equipo
que ya tenga el venv completo para clonarlo.

### 5.4 Verificación tras la instalación

```bash
# Marcadores de modo (los crea el instalador):
#   set ct2    -> existe .use_ct2, no existe .use_marian
#   set marian -> existe .use_marian, no existe .use_ct2
ls -la /opt/ai/traduia/models/.use_ct2 /opt/ai/traduia/models/.use_marian

# El servidor debe arrancar y abrir el navegador sin descargar nada:
/usr/bin/traduia

# Compruebe que no hay tráfico de modelos a huggingface.co:
# (sin configuración TRADUIA_MODELS_URL y con modelos completos, no debe
#  haber conexiones salientes al instalar)
```

### 5.5 Cómo decide el servidor el modo de modelos (ct2/marian)

Al arrancar, `traduia_server.py` muestra en consola qué modo usa y por qué:

- **Un solo marcador presente** → es un *override* explícito: `.use_ct2` →
  CT2, `.use_marian` → Marian. Se valida contra el disco; si el set marcado
  no está completo, avisa y **cae al otro set disponible** (fallback).
- **Ambos marcadores presentes** → **prioridad Marian** (con fallback a CT2
  si Marian no está completo).
- **Sin marcadores** → **detección desde disco**; si ambos sets están
  completos, **prioridad Marian**.
- **Sin ningún set completo** → error claro al arrancar indicando que se
  ejecute `install-models-traduia`.

> **Nota**: el instalador **nunca deja ambos marcadores** (son excluyentes).
> La situación "ambos presentes" solo puede darse si se crean manualmente
> (p.ej. `touch /opt/ai/traduia/models/.use_marian` junto a un `.use_ct2`
> existente) — en ese caso actúa el desempate: prioridad Marian, con fallback
> a CT2 si Marian no está completo en disco.

Cualquier problema al cargar un modelo (Whisper, Marian o CT2) se muestra
como `[WARN]` en la consola. El servidor carga siempre los modelos desde
disco con `local_files_only`/offline, por lo que en ejecución nunca se
descarga nada.
