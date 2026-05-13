#!/bin/bash

# Configuration
DOMAIN="traduia"
I18N_DIR="i18n"
POT_FILE="${I18N_DIR}/${DOMAIN}.pot"
PO_DIR="${I18N_DIR}/po"
LOCALE_DIR="${I18N_DIR}/locale"

# Ensure we are in the script directory
cd "$(dirname "$0")"

# Source files
PYTHON_SRC="traduia_server.py check-traduia-server"
BASH_SRC="traduia install-models-traduia zero-lliurex-traduia.install-files/usr/share/zero-lliurex-traduia/traduia_script"

# Languages to support
LANGS=("es" "ca" "en")

function show_help() {
    echo "Usage: $0 {update|compile}"
    echo "  update:  Extract strings and update POT/PO files"
    echo "  compile: Generate binary MO files"
}

function update_translations() {
    echo "[INFO] Updating POT file..."
    mkdir -p "${I18N_DIR}"

    # 1. Extract from Python
    # Added keyword _t for the web client strings
    xgettext --language=Python \
             --keyword=_ \
             --keyword=_t \
             --from-code=UTF-8 \
             --force-po \
             --output="${POT_FILE}" \
             ${PYTHON_SRC}
    
    # 2. Extract from Bash and join with existing POT
    xgettext --language=Shell \
             --keyword=_ \
             --keyword=_t \
             --from-code=UTF-8 \
             --join-existing \
             --output="${POT_FILE}" \
             ${BASH_SRC}

    if [ ! -s "${POT_FILE}" ]; then
        echo "[ERROR] POT file is empty. No strings were extracted."
        return 1
    fi

    # Set project info in POT
    sed -i 's/SOME DESCRIPTIVE TITLE/TraduIA Localization/g' "${POT_FILE}"
    sed -i 's/PACKAGE PACKAGE/traduia/g' "${POT_FILE}"
    sed -i 's/CHARSET/UTF-8/g' "${POT_FILE}"

    echo "[INFO] POT file updated successfully."

    for lang in "${LANGS[@]}"; do
        LANG_PO_DIR="${PO_DIR}/${lang}"
        PO_FILE="${LANG_PO_DIR}/${DOMAIN}.po"
        
        mkdir -p "${LANG_PO_DIR}"
        
        if [ ! -f "${PO_FILE}" ]; then
            echo "[INFO] Initializing new PO file for language: ${lang}"
            msginit --no-translator --locale="${lang}" --input="${POT_FILE}" --output="${PO_FILE}"
        else
            echo "[INFO] Merging changes into PO file for language: ${lang}"
            msgmerge --update --no-fuzzy-matching "${PO_FILE}" "${POT_FILE}"
        fi
    done
}

function compile_translations() {
    echo "[INFO] Compiling MO files..."
    
    for lang in "${LANGS[@]}"; do
        PO_FILE="${PO_DIR}/${lang}/${DOMAIN}.po"
        MO_TARGET_DIR="${LOCALE_DIR}/${lang}/LC_MESSAGES"
        MO_FILE="${MO_TARGET_DIR}/${DOMAIN}.mo"
        
        if [ -f "${PO_FILE}" ]; then
            mkdir -p "${MO_TARGET_DIR}"
            echo "[INFO] Compiling ${lang}..."
            msgfmt "${PO_FILE}" -o "${MO_FILE}"
        else
            echo "[WARN] PO file not found for ${lang}: ${PO_FILE}"
        fi
    done
}

# Main logic
case "$1" in
    update)
        update_translations
        ;;
    compile)
        compile_translations
        ;;
    *)
        show_help
        exit 1
        ;;
esac

exit 0
