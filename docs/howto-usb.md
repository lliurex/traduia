# HowTo: modelos TraduIA en USB — exportación e instalación offline

Este documento cubre el ciclo completo con un disco USB (o disco externo):

1. **Exportar** los modelos desde una máquina con Internet a un USB.
2. **Instalar sin descargas** copiando el contenido del USB a un equipo sin
   acceso a Internet (o sin configurar repositorio HTTP).
3. **Verificar** la instalación y entender cómo el servidor elige el modo
   de modelos.

El mismo USB sirve también para publicar el repositorio HTTP en una red
(ver `howto-repo-http.md`).

## 1. Preparar la máquina origen

En una máquina con Internet, descargue los modelos (una sola vez):

```bash
# Modo original (Marian):
install-models-traduia

# Modo optimizado (CTranslate2):
install-models-traduia optimized
```

Los modelos quedan en `/opt/ai/traduia/models` (`whisper-small/` + `ct2/` o
`marian/` + el marcador correspondiente — `.use_ct2` o `.use_marian`, **solo
uno**, lo crea el instalador según el último modo ejecutado).

## 2. Generar el contenido para el USB

Genere un directorio con el manifest de todo el contenido:

```bash
# Modo original (Marian):
traduia-make-repo /opt/ai/traduia/models marian /srv/usb/traduia

# Modo optimizado (CTranslate2):
traduia-make-repo /opt/ai/traduia/models ct2 /srv/usb/traduia
```

> El script **valida que el set esté completo** (whisper-small + los 10
> pares) y se niega a generar un repositorio incompleto, listando lo que
> falta.

La herramienta **autodetecta** el método de ensamblado comparando el
sistema de ficheros de origen y destino: mismo filesystem → **hardlinks**
(rápido, no duplica GBs); filesystems distintos (p.ej. escribir directamente
en un USB) → **copia automática**. No hay que indicar nada:

```bash
traduia-make-repo /opt/ai/traduia/models ct2 /media/usuario/USB/traduia
```

(Opcionalmente, `--copy` fuerza la copia aunque estén en el mismo filesystem.)

### 2.1 Llevar ambos modos (ct2 y marian) en el mismo USB

La herramienta es **aditiva**: ejecútela una vez por cada set que quiera
llevar, apuntando siempre al **mismo** directorio de salida. `whisper-small`
solo se copia en la primera ejecución — **nunca se duplica**:

```bash
traduia-make-repo /opt/ai/traduia/models ct2    /srv/usb/traduia   # 1ª: whisper + ct2
traduia-make-repo /opt/ai/traduia/models marian /srv/usb/traduia   # 2ª: añade marian
```

Cada ejecución regenera el `manifest.json` cubriendo todo lo que haya en el
directorio (el campo `mode` indica `ct2`, `marian` o `both`). Re-ejecutar el
mismo modo refresca los ficheros (idempotente, útil al actualizar modelos).

> El USB se llena con una sola tipología (ct2 **o** marian) según lo que se
> vaya a instalar en las aulas; llevar ambas es válido (whisper compartido,
> sin duplicación).

> **Nota**: el USB **no** incluye los marcadores de modo (`.use_ct2` /
> `.use_marian`). Los crea el instalador en la máquina destino según el set
> copiado; el servidor, además, los autodetecta desde el disco si no existen
> (ver sección 7).

## 3. Estructura resultante en el USB

```
USB/
└── traduia/
    ├── manifest.json          # manifest GLOBAL (todo el contenido)
    ├── whisper-small/…        # UNA sola copia, compartida
    ├── ct2/opus-mt-{par}/…    # (solo si se añadió el set ct2)
    └── marian/opus-mt-{par}/… # (solo si se añadió el set marian)
```

Espacio aproximado: el modo ct2 ocupa ~4-5 GB y el modo marian ~8-10 GB
(whisper-small compartido, no se suma dos veces). Use un USB con espacio
suficiente.

## 4. Copiar al USB (si se generó en local) y verificar

```bash
rsync -a --progress /srv/usb/traduia/ /media/usuario/USB/traduia/
sync
```

Tras la copia, compruebe que cada fichero del USB coincide con su sha256 del
manifest:

```bash
cd /media/usuario/USB/traduia
python3 - <<'EOF'
import hashlib, json, os
m = json.load(open("manifest.json"))
errors = 0
for f in m["files"]:
    p = f["path"]
    if not os.path.exists(p) or os.path.getsize(p) != f["size"]:
        print("FALTA/TAMAÑO:", p); errors += 1; continue
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h != f["sha256"]:
        print("SHA256 INCORRECTO:", p); errors += 1
print("OK" if errors == 0 else f"{errors} errores")
EOF
```

Si todo es correcto, el USB está listo para la instalación offline (sección
5) o para publicarse como repositorio HTTP (ver `howto-repo-http.md`).

## 5. Instalación offline desde el USB

### 5.1 Copiar los modelos ANTES de instalar

Monte el USB y copie `whisper-small/` **y el set del modo elegido** a
`/opt/ai/traduia/models`:

```bash
sudo mkdir -p /opt/ai/traduia/models
sudo rsync -a --progress /media/usuario/USB/traduia/whisper-small/ /opt/ai/traduia/models/whisper-small/
sudo rsync -a --progress /media/usuario/USB/traduia/ct2/ /opt/ai/traduia/models/ct2/
# (o marian:  sudo rsync -a --progress /media/usuario/USB/traduia/marian/ /opt/ai/traduia/models/marian/)
```

> **Importante**: la estructura destino debe ser la estándar. Para el modo
> ct2:
> `/opt/ai/traduia/models/whisper-small/` + `/opt/ai/traduia/models/ct2/`
> Para el modo marian:
> `/opt/ai/traduia/models/whisper-small/` + `/opt/ai/traduia/models/marian/`

> Si el USB lleva **ambos modos** (sección 2.1), copie solo el que vaya a
> usar. También es válido copiar los dos sets a `/opt/ai/traduia/models` (el
> instalador detecta `complete:both` y el modo lo deciden el flag
> `optimized`/los marcadores, con prioridad Marian en los empates — ver
> sección 7), pero es lo habitual instalar con un solo modo.

Puede verificar la copia con el mismo script de sha256 de la sección 4,
apuntando a `/opt/ai/traduia/models`.

### 5.2 Instalar el paquete

Instale el paquete `traduia` (deb o desde el instalador zero-center) de
forma normal:

- El instalador comprueba `/opt/ai/traduia/models` **antes** de descargar.
- La descarga es **por-set**: si los ficheros del set pedido (ct2 con
  `optimized`, marian sin él) ya están **completos** en disco (copiados desde
  USB o de una instalación anterior), se hace **skip**; si no, se
  **descarga/completa** lo que falte (desde el repo HTTP si está configurado,
  o desde HuggingFace).
- En el instalador zero-center **siempre se pregunta** el modo: `Marian`
  (por defecto) u `Optimized`/CT2 (experimental); con esa respuesta se
  ejecuta `install-models-traduia [optimized]`.

Comandos directos (sin zero-center):

```bash
sudo install-models-traduia          # set marian (skip si ya está en disco)
sudo install-models-traduia optimized # set ct2 (skip si ya está en disco)
```

### 5.3 Si falta algo: el instalador completa la descarga

Si en el disco hay modelos **incompletos** (p.ej. falta un `opus-mt-*` del
set pedido), el instalador **completa la descarga** de lo que falte: con repo
HTTP configurado baja solo los ficheros ausentes (verificando los presentes
por sha256); sin URL, HuggingFace rellena el resto. Solo falla si no hay
ninguna fuente disponible (sin red y sin URL configurada), con el error claro
del origen correspondiente.

> En **tiempo de ejecución** (`traduia`/`traduia_server.py`) nunca se
> descarga: si el modo elegido no está completo, avisa (`[WARN]`) y hace
> fallback al otro set o error al arrancar.

### 5.4 Limitación importante (leer)

La **no descarga se aplica a los modelos**. El instalador también crea el
entorno virtual (`/opt/ai/traduia/venv`) e instala sus dependencias Python
(fastapi, torch, faster-whisper, transformers…), lo que **sí requiere red**
(o un mirror pip local) en la primera instalación. Para una instalación
100% offline debe disponer además de una caché/mirror de pip, o un equipo
que ya tenga el venv completo para clonarlo.

## 6. Verificación tras la instalación

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

## 7. Cómo decide el servidor el modo de modelos (ct2/marian)

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
como `[WARN]` en la consola.

El servidor carga siempre los modelos desde disco con
`local_files_only`/offline, por lo que en ejecución nunca se descarga nada.
