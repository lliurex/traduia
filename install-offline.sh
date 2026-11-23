#!/bin/bash
#
# Instalador offline de TraduIA.
#
# Instala paquetes desde el repositorio apt incluido en este USB/directorio
# usando un entorno apt temporal en /tmp. No modifica /etc/apt, ni
# /var/lib/apt/lists, ni /var/cache/apt. Al terminar elimina el entorno
# temporal.
#
# Uso:
#   sudo ./install-offline.sh [--client|--server|--all]
#                             [--with-piper|--without-piper]
#                             [--run-config|--no-run-config] [--yes]
#
# Modos:
#   --client   TraduIA cliente
#   --server   TraduIA servidor
#   --all      Todo con todas las voces
#
# Sin modo muestra un menú interactivo.
set -uo pipefail

umask 022

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CODENAME="$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-}")"
DEBS_DIR="$SCRIPT_DIR/debs/$CODENAME"
LIST_FILE="$SCRIPT_DIR/debs-$CODENAME.txt"
PACKAGES_FILE="$DEBS_DIR/Packages"

MODE=""
PIPER="ask"          # ask | yes | no
RUN_CONFIG="ask"     # ask | yes | no
ASSUME_YES=false

usage() {
    cat <<EOF
Uso: sudo $0 [opciones]

Instala paquetes desde el repositorio offline de este directorio usando un
entorno apt temporal en /tmp. No modifica los repositorios del sistema.

Opciones:
  --client              TraduIA cliente
  --server              TraduIA servidor
  --all                 Todo con todas las voces
  --with-piper          Instalar Piper TTS y todas las voces
  --without-piper       No instalar Piper TTS
  --run-config          Ejecutar traduia-config al terminar
  --no-run-config       No ejecutar traduia-config
  --configure           Alias de --run-config
  --yes, -y             No pedir confirmación (requiere modo)
  --help, -h            Esta ayuda

Sin modo se muestra un menú interactivo.
EOF
}

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

warn() {
    echo "[WARN] $*" >&2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --server|--client|--all)
            MODE="${1#--}"
            ;;
        --with-piper)
            PIPER="yes"
            ;;
        --without-piper)
            PIPER="no"
            ;;
        --run-config|--configure)
            RUN_CONFIG="yes"
            ;;
        --no-run-config)
            RUN_CONFIG="no"
            ;;
        --yes|-y)
            ASSUME_YES=true
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "[ERROR] Opción desconocida: $1" >&2
            usage
            exit 1
            ;;
    esac
    shift
done

[ "$(id -u)" -eq 0 ] || die "Este instalador debe ejecutarse como root (sudo)."

case "$CODENAME" in
    jammy|noble) ;;
    *) die "Distribución no soportada: ${CODENAME:-desconocida}" ;;
esac

if [ ! -d "$DEBS_DIR" ]; then
    die "No existe el repositorio de paquetes: $DEBS_DIR"
fi

# Menú principal con opción Atrás desde la pregunta de Piper.
while true; do
    if [ -z "$MODE" ]; then
        if $ASSUME_YES; then
            die "Con --yes es necesario indicar --client, --server o --all."
        fi
        cat <<EOF
=== Instalación offline de TraduIA ===
Repositorio: $SCRIPT_DIR
Distribución: $CODENAME

¿Qué quieres instalar?
  1) TraduIA cliente
  2) TraduIA servidor
  3) Todo con todas las voces
  0) Salir
EOF
        read -r -p "Opción [1]: " option
        case "${option:-1}" in
            1) MODE="client" ;;
            2) MODE="server" ;;
            3) MODE="all" ;;
            0) exit 0 ;;
            *) echo "[ERROR] Opción no válida: $option" >&2; continue ;;
        esac
    fi

    if [ "$MODE" = "all" ]; then
        PIPER="yes"
        break
    fi

    if [ "$PIPER" = "ask" ]; then
        if $ASSUME_YES; then
            PIPER="no"
            warn "Con --yes y sin --with-piper/--without-piper se asume --without-piper."
            break
        fi
        cat <<EOF

¿Instalar Piper TTS?
  1) Sí (todas las voces)
  2) No
  9) Atrás
  0) Salir
EOF
        read -r -p "Opción [1]: " option
        case "${option:-1}" in
            1) PIPER="yes"; break ;;
            2) PIPER="no"; break ;;
            9) MODE=""; continue ;;
            0) exit 0 ;;
            *) echo "[ERROR] Opción no válida: $option" >&2; continue ;;
        esac
    fi
    break
done

if $ASSUME_YES && [ "$RUN_CONFIG" = "ask" ]; then
    RUN_CONFIG="no"
    warn "Con --yes y sin --run-config/--no-run-config no se ejecutará traduia-config."
fi

# Lista de paquetes del repositorio (solo nombres).
LIST_PKGS=()
if [ -r "$LIST_FILE" ]; then
    while IFS= read -r line; do
        line="${line%%#*}"
        line="$(echo "$line" | tr -d '[:space:]')"
        [ -n "$line" ] && LIST_PKGS+=("$line")
    done < "$LIST_FILE"
fi

# Fallback: si no hay lista, derivar de Packages.
if [ "${#LIST_PKGS[@]}" -eq 0 ] && [ -r "$PACKAGES_FILE" ]; then
    while IFS= read -r pkg; do
        [ -n "$pkg" ] && LIST_PKGS+=("$pkg")
    done < <(awk '/^Package: /{print $2}' "$PACKAGES_FILE" | sort -u)
fi

# Selección según modo.
SELECTED=()
case "$MODE" in
    client|server)
        SELECTED=(traduia zero-lliurex-traduia zero-lliurex-piper-tts-server)
        if [ "$PIPER" = "yes" ]; then
            for pkg in "${LIST_PKGS[@]}"; do
                case "$pkg" in
                    piper-tts|piper-tts-server|piper-tts-voices-*|python3-onnxruntime|libonnxruntime1.23|libonnxruntime-providers)
                        SELECTED+=("$pkg")
                        ;;
                esac
            done
        fi
        ;;
    all)
        SELECTED=("${LIST_PKGS[@]}")
        ;;
    *)
        die "Modo no válido: $MODE"
        ;;
esac

# Construir argumentos apt: pkg=version desde el Packages local, o rutas
# directas a .deb si no hay índice.
APT_PKGS=()
if [ -r "$PACKAGES_FILE" ]; then
    mapfile -t APT_PKGS < <(python3 - "$PACKAGES_FILE" "${SELECTED[@]}" <<'PY'
import sys

packages_file = sys.argv[1]
wanted = sys.argv[2:]


def version_key(v):
    import re
    key = []
    for part in re.split(r"[.~+:-]", v):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part))
    return key


best = {}
with open(packages_file, encoding="utf-8", errors="replace") as fh:
    stanza = {}
    for line in list(fh) + [""]:
        if line.strip() == "":
            pkg = stanza.get("Package")
            if pkg:
                ver = stanza.get("Version", "")
                if pkg not in best or version_key(ver) > best[pkg][0]:
                    best[pkg] = (version_key(ver), ver)
            stanza = {}
            continue
        if ":" in line:
            field, _, value = line.partition(":")
            stanza[field.strip()] = value.strip()

for pkg in wanted:
    if pkg in best:
        print(f"{pkg}={best[pkg][1]}")
    else:
        print(f"[WARN] Paquete no encontrado en Packages: {pkg}", file=sys.stderr)
PY
    )
else
    warn "No existe $PACKAGES_FILE; se instalarán los .deb directamente."
    for pkg in "${SELECTED[@]}"; do
        shopt -s nullglob
        files=( "$DEBS_DIR/${pkg}_"*.deb )
        shopt -u nullglob
        if [ "${#files[@]}" -eq 0 ]; then
            warn "No se encontró el .deb de: $pkg"
            continue
        fi
        APT_PKGS+=("${files[@]}")
    done
fi

if [ "${#APT_PKGS[@]}" -eq 0 ]; then
    warn "No hay paquetes que instalar."
    exit 0
fi

# Entorno apt temporal.
TMP_APT="$(mktemp -d "${TMPDIR:-/tmp}/traduia-offline.XXXXXX")" || die "No se pudo crear el entorno temporal."
cleanup() {
    rm -rf -- "$TMP_APT"
}
trap cleanup EXIT

mkdir -p "$TMP_APT/etc/apt/sources.list.d" \
         "$TMP_APT/etc/apt/preferences.d" \
         "$TMP_APT/lists/partial" \
         "$TMP_APT/cache/archives/partial" \
         "$TMP_APT/log"

cp -a /etc/apt/sources.list "$TMP_APT/etc/apt/sources.list" 2>/dev/null || :
if [ -d /etc/apt/sources.list.d ]; then
    cp -a /etc/apt/sources.list.d/. "$TMP_APT/etc/apt/sources.list.d/" 2>/dev/null || :
fi
printf 'deb [trusted=yes] file:%s ./\n' "$DEBS_DIR" \
    > "$TMP_APT/etc/apt/sources.list.d/99-traduia-offline.list"

APT_OPTS=(
    -o "Dir::Etc=$TMP_APT/etc/apt"
    -o "Dir::Etc::sourcelist=$TMP_APT/etc/apt/sources.list"
    -o "Dir::Etc::sourceparts=$TMP_APT/etc/apt/sources.list.d"
    -o "Dir::Etc::trusted=/etc/apt/trusted.gpg"
    -o "Dir::Etc::trustedparts=/etc/apt/trusted.gpg.d"
    -o "Dir::Etc::main=/etc/apt/apt.conf"
    -o "Dir::Etc::parts=/etc/apt/apt.conf.d"
    -o "Dir::Etc::preferences=/etc/apt/preferences"
    -o "Dir::Etc::preferencesparts=/etc/apt/preferences.d"
    -o "Dir::State::lists=$TMP_APT/lists"
    -o "Dir::Cache=$TMP_APT/cache"
    -o "Dir::Log=$TMP_APT/log"
    -o "APT::Get::List-Cleanup=0"
    -o "Acquire::http::Timeout=5"
    -o "Acquire::https::Timeout=5"
    -o "Acquire::Retries=0"
)

echo "[INFO] Actualizando índices apt temporales..."
apt-get "${APT_OPTS[@]}" update || true

echo "[INFO] Instalando paquetes..."
DEBIAN_FRONTEND=noninteractive \
    apt-get "${APT_OPTS[@]}" install -y --allow-downgrades "${APT_PKGS[@]}"
rc=$?

if [ "$rc" -ne 0 ]; then
    echo "[ERROR] La instalación de paquetes falló (código $rc)." >&2
    echo "[ERROR] Revisa los mensajes anteriores. No se ha modificado /etc/apt." >&2
    exit "$rc"
fi

echo ""
echo "[INFO] Paquetes instalados."
echo "[INFO] No se han añadido repositorios persistentes al sistema."
echo ""
echo "Siguiente paso:"
echo "  sudo traduia-config"
echo ""
echo "  (o abre zero-center y usa el instalador de TraduIA)"
echo ""

if [ "$RUN_CONFIG" = "ask" ]; then
    read -r -p "¿Ejecutar traduia-config ahora? [S/n]: " ans
    case "${ans:-s}" in
        s|S|y|Y) RUN_CONFIG="yes" ;;
        *) RUN_CONFIG="no" ;;
    esac
fi

if [ "$RUN_CONFIG" = "yes" ]; then
    if [ ! -x /usr/sbin/traduia-config ]; then
        warn "traduia-config no está disponible; no se puede configurar automáticamente."
    elif [ "$MODE" = "all" ]; then
        /usr/sbin/traduia-config
    else
        mode_label="Client"
        [ "$MODE" = "server" ] && mode_label="Server"
        piper_flag="--no-piper"
        [ "$PIPER" = "yes" ] && piper_flag="--piper"
        /usr/sbin/traduia-config configure --mode "$mode_label" --source "$SCRIPT_DIR" "$piper_flag"
    fi
fi
