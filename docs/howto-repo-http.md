# HowTo: exportar modelos a un repositorio HTTP y publicarlo en otra máquina

Este procedimiento permite que las instalaciones de TraduIA descarguen los
modelos desde un repositorio HTTP propio (servido estáticamente) en lugar de
descargarlos desde HuggingFace, evitando depender de Internet pública y
aprovechando cualquier proxy cache de la red.

## 1. Requisitos

- Una máquina **origen** con acceso a Internet donde esté instalado `traduia`
  (o al menos disponible el script `/usr/sbin/install-models-traduia`).
- Una máquina **servidor** que pueda servir ficheros estáticos por HTTP
  (nginx, Apache, lighttpd, o un contenedor/servidor de ficheros cualquiera).

## 2. Descargar los modelos en la máquina origen

```bash
# Modelos originales (Marian, sin cuantizar):
install-models-traduia

# Modelos optimizados (CTranslate2, más rápidos; experimentales):
install-models-traduia optimized
```

> Los dos comandos son **alternativos**. Si se ejecutan ambos en secuencia,
> el marcador queda el del **último** modo ejecutado (el instalador crea uno
> y elimina el otro — son excluyentes).

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

> Los marcadores de modo **no se publican** en el repositorio: `traduia-make-repo`
> solo copia `whisper-small/` y los sets pedidos más el `manifest.json`. El
> instalador crea el marcador adecuado en cada cliente y el servidor lo
> autodetecta desde el disco si no existe.

## 3. Generar el repositorio (manifest + ficheros)

El repositorio tiene un único `manifest.json` en la raíz que cubre **todo**
el contenido (`whisper-small/` + los sets presentes), con `size` + `sha256`
por fichero:

```bash
# Modo original (Marian):
traduia-make-repo /opt/ai/traduia/models marian /srv/repo/traduia

# Modo optimizado (CTranslate2):
traduia-make-repo /opt/ai/traduia/models ct2 /srv/repo/traduia
```

- **Hardlinks si origen y destino están en el mismo filesystem** (rápido, no
  duplica GBs); si están en filesystems distintos (p.ej. un USB conectado) se
  **copian automáticamente**. No hay que especificar nada; `--copy` fuerza
  la copia opcionalmente.
- Si falta cualquier fichero requerido, el script **se niega** a generar un
  repositorio incompleto y lista lo que falta.

Resultado:

```
/srv/repo/traduia/
├── manifest.json
├── whisper-small/…
└── marian/opus-mt-{par}/…    (o ct2/opus-mt-{par}/…)
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

### 3.1 Publicar ambos modos (ct2 y marian) en el mismo servidor

La herramienta es **aditiva**: ejecútela una vez por cada set que quiera
publicar, apuntando siempre al **mismo** directorio. `whisper-small` solo se
copia en la primera ejecución — **nunca se duplica**:

```bash
traduia-make-repo /opt/ai/traduia/models ct2    /srv/repo/traduia   # 1ª: whisper + ct2
traduia-make-repo /opt/ai/traduia/models marian /srv/repo/traduia   # 2ª: añade marian

rsync -a /srv/repo/traduia/ server:/var/www/public/models/traduia/
```

Estructura publicada:

```
http://servidor:puerto/public/models/traduia/
├── manifest.json          # manifest GLOBAL (whisper + ct2 + marian)
├── whisper-small/…        # UNA sola copia, compartida
├── ct2/opus-mt-{par}/…
└── marian/opus-mt-{par}/…
```

Cada cliente descarga solo lo que necesita de su modo: siempre
`whisper-small/` + (`ct2/` o `marian/`) según su instalación. El instalador
**valida contra el manifest** que el repo contiene el set pedido completo y,
si no lo contiene, falla con la lista de pares ausentes **antes de
descargar**.

## 4. Publicar en la máquina servidor

### 4.1 Transferir los ficheros

```bash
rsync -a /srv/repo/traduia/ server:/var/www/public/models/traduia/
```

(o `scp -r` si prefiere, aunque `rsync` permite reanudar copias grandes).

### 4.2 Configurar el servidor web (ejemplo con nginx)

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
cd /srv/repo/traduia && python3 -m http.server 8080
```

## 5. Configurar los clientes

La URL base del repositorio (la raíz que contiene `manifest.json`) se fija
con cualquiera de estos mecanismos (**prioridad de mayor a menor**):

### 5.1 Parámetro CLI

```bash
install-models-traduia --url http://servidor:puerto/public/models/traduia
install-models-traduia optimized --url http://servidor:puerto/public/models/traduia
```

> El instalador descarga del manifest global solo `whisper-small/` + el set
> de su modo (`ct2` si `optimized`, si no `marian`).

### 5.2 Variable de entorno

```bash
export TRADUIA_MODELS_URL=http://servidor:puerto/public/models/traduia
install-models-traduia
```

### 5.3 Fichero de configuración (recomendado para despliegues)

Crear `/etc/traduia/models-repo.conf`:

```bash
# /etc/traduia/models-repo.conf
TRADUIA_MODELS_URL=http://servidor:puerto/public/models/traduia
```

Este fichero puede sembrarse con puppet/ansible o por otro paquete.

### 5.4 Sin ninguna configuración

Si no se fija ninguna URL, el instalador usa HuggingFace como siempre.

## 6. Verificación

```bash
# El manifest debe responder:
curl -fsSL http://servidor:puerto/public/models/traduia/manifest.json

# Prueba de instalación completa en un equipo cliente:
install-models-traduia --url http://servidor:puerto/public/models/traduia
```

Durante la descarga el instalador verifica **tamaño y sha256** de cada
fichero. Un fallo de verificación produce un error claro (posible caché
obsoleta o repositorio corrupto) y detiene la instalación.
