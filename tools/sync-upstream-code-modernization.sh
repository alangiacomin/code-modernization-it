#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
TEMP_DIR=""

cleanup() {
    if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
        rm -rf "${TEMP_DIR}"
    fi
}

trap cleanup EXIT

cd "${REPO_ROOT}"

echo "==> Verifica repository locale"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERRORE: il working tree non è pulito."
    echo "       Il sync è stato interrotto senza modificare il repository."
    exit 1
fi

if ! git remote get-url upstream >/dev/null 2>&1; then
    echo "ERRORE: il remote 'upstream' non esiste."
    exit 1
fi

if ! command -v git-filter-repo >/dev/null 2>&1; then
    echo "ERRORE: git-filter-repo non è installato."
    exit 1
fi

UPSTREAM_URL="$(git remote get-url upstream)"

echo "    Repository : ${REPO_ROOT}"
echo "    Upstream   : ${UPSTREAM_URL}"

echo
echo "==> Aggiornamento riferimento upstream"

git fetch upstream main

UPSTREAM_COMMIT="$(git rev-parse upstream/main)"

echo "    upstream/main = ${UPSTREAM_COMMIT}"

echo
echo "==> Creazione repository temporaneo"

TEMP_DIR="$(mktemp -d)"

echo "    Directory temporanea: ${TEMP_DIR}"

echo
echo "==> Clonazione upstream"

git clone --quiet "${UPSTREAM_URL}" "${TEMP_DIR}/upstream"

cd "${TEMP_DIR}/upstream"

echo
echo "==> Estrazione di plugins/code-modernization"

git filter-repo \
    --path plugins/code-modernization/ \
    --path-rename plugins/code-modernization/:

FILTERED_COMMIT="$(git rev-parse HEAD)"

echo
echo "==> Risultato"

echo "    Commit upstream originale : ${UPSTREAM_COMMIT}"
echo "    Commit upstream filtrato  : ${FILTERED_COMMIT}"

echo
echo "==> Ultimi commit filtrati"

git log --oneline -5

echo
echo "==> Contenuto della root filtrata (verrà riallineato a plugins/code-modernization/ con -Xsubtree)"

git ls-tree --name-only HEAD

echo
echo "==> Sync di sola lettura completato."
echo "    Nessun merge, commit o push è stato eseguito."

