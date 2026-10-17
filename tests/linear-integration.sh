#!/usr/bin/env bash
# Integración REAL y aislada de la Linear CLI COMUNITARIA fijada (schpet/linear-cli, @schpet/linear-cli@3.0.0).
# Es opt-in (ASB_LINEAR_INTEGRATION=1) y está pensada para un runner efímero con Node 24. USA RED: npm
# descarga el paquete y su postinstall un binario nativo desde GitHub. Escribe solo bajo un directorio
# temporal con HOME propio. Ejecuta únicamente mod_linear de install.sh: sin sudo, sin el módulo cloud
# completo y sin tokens. No ejecuta nunca `linear auth`, config, whoami ni llamadas a la API de Linear.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
BASE=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
BASE=${BASE%/}

if [ "${ASB_LINEAR_INTEGRATION:-}" != 1 ]; then
  printf 'FALLO integración: define ASB_LINEAR_INTEGRATION=1 para ejecutarla a propósito (usa red)\n' >&2
  exit 1
fi

TMP=$(mktemp -d "$BASE/asb-linear-integration.XXXXXX")

# Entorno aislado: HOME propio ANTES de cargar install.sh (calcula sus rutas al cargarse).
export HOME="$TMP/home"
export NPM_CONFIG_PREFIX="$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
unset LINEAR_API_KEY
mkdir -p "$HOME"

# install.sh es parte del repositorio y se carga dinámicamente (no hay main al hacer source).
# shellcheck source=/dev/null
. "$REPO/install.sh"

it_cleanup() {
  case "$TMP" in "$BASE"/asb-linear-integration.*) rm -rf -- "$TMP" ;; esac
}
trap it_cleanup EXIT

# Variables que usan las funciones de install.sh cargadas arriba (ShellCheck no las sigue).
# shellcheck disable=SC2034
APPLY=1 SELECTED="cloud"
cd "$HOME"

fail() { printf 'FALLO integración: %s\n' "$*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

ws="$TOOLS/linear"
pkg_dir="$ws/node_modules/@schpet/linear-cli"

step "precondiciones"
node_ok || fail "se necesita Node>=$NODE_MAJOR con npm ($(node_desc))"
if have linear; then fail "ya hay un 'linear' en el PATH: este test necesita un entorno limpio"; fi

step "primera pasada (instalación fijada)"
mod_linear

[ -x "$ws/node_modules/.bin/linear" ] || fail "falta el launcher $ws/node_modules/.bin/linear"
case "$(command -v linear)" in "$HOME"/.local/bin/linear) ;; *) fail "el wrapper no quedó en $HOME/.local/bin" ;; esac
[ "$(node -p "require('$pkg_dir/package.json').version")" = "$LINEAR_VERSION" ] || fail "versión instalada distinta de $LINEAR_VERSION"
[ "$(node -p "require('$ws/package-lock.json').packages['node_modules/@schpet/linear-cli'].version")" = "$LINEAR_VERSION" ] \
  || fail "package-lock.json no fija $LINEAR_VERSION"
[ "$(node -p "require('$ws/package.json').dependencies['@schpet/linear-cli']")" = "$LINEAR_VERSION" ] \
  || fail "package.json no fija la versión exacta $LINEAR_VERSION"

# Solo la versión: ninguna orden de auth, config, whoami ni de red de la CLI.
out=$(linear --version 2>&1) || fail "linear --version falló"
first=${out%%$'\n'*}; first=${first##* }; first=${first#v}
[ "$first" = "$LINEAR_VERSION" ] || fail "linear --version informa '$first', se esperaba $LINEAR_VERSION"

pkg_sum=$(sha256sum "$ws/package.json")
lock_sum=$(sha256sum "$ws/package-lock.json")
wrapper_sum=$(sha256sum "$HOME/.local/bin/linear")

step "segunda pasada (se omite y no cambia nada)"
second=$(mod_linear)
printf '%s\n' "$second"
printf '%s\n' "$second" | grep -qF "se omite" || fail "la segunda pasada no se omitió"
[ "$(sha256sum "$ws/package.json")" = "$pkg_sum" ] || fail "cambió package.json"
[ "$(sha256sum "$ws/package-lock.json")" = "$lock_sum" ] || fail "cambió package-lock.json"
[ "$(sha256sum "$HOME/.local/bin/linear")" = "$wrapper_sum" ] || fail "cambió el wrapper"

step "sin credenciales ni configuración creadas"
for p in "$HOME/.config/linear" "$HOME/.config/linear-cli" "$HOME/.linear.toml" "$HOME/.linear"; do
  if [ -e "$p" ] || [ -L "$p" ]; then fail "apareció $p: la integración no debe crear credenciales ni configuración"; fi
done

printf 'OK integración real de la Linear CLI comunitaria %s\n' "$LINEAR_VERSION"
