#!/usr/bin/env bash
# Integración REAL y aislada de Pi fijado + pi-selection-editor. Es opt-in: la ejecuta quien la invoca
# a propósito (CI en un runner efímero). USA RED, npm y git reales y escribe solo bajo un directorio
# temporal con HOME propio. No ejecuta main/mod_agents: no usa sudo, apt, otros instaladores de
# terceros ni logins; solo pi_install y configure_pi de install.sh.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
BASE=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
BASE=${BASE%/}
TMP=$(mktemp -d "$BASE/asb-pi-integration.XXXXXX")

# Entorno aislado: HOME propio ANTES de cargar install.sh (calcula sus rutas al cargarse).
export HOME="$TMP/home"
export PI_CODING_AGENT_DIR="$HOME/custom-pi-agent" # ejercita la sobrescritura del directorio de Pi
export NPM_CONFIG_PREFIX="$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
unset PI_SELECTION_EDITOR_DIR
mkdir -p "$HOME" "$PI_CODING_AGENT_DIR"

# install.sh es parte del repositorio y se carga dinámicamente (no hay main al hacer source).
# shellcheck source=/dev/null
. "$REPO/install.sh"

it_cleanup() {
  case "$TMP" in "$BASE"/asb-pi-integration.*) rm -rf -- "$TMP" ;; esac
}
trap it_cleanup EXIT

# Variables que usan las funciones de install.sh cargadas arriba (ShellCheck no las sigue).
# shellcheck disable=SC2034
APPLY=1 VENDOR=1 WITH_PI=1 SELECTED="agents"
cd "$HOME"

fail() { printf 'FALLO integración: %s\n' "$*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

settings="$PI_CODING_AGENT_DIR/settings.json"
stable="$HOME/.local/share/pi-selection-editor"

# Python tolerante: `packages` puede contener cadenas u objetos con «source». Imprime los paquetes.
packages_json() {
  python3 -I - "$settings" "$PI_EXT_DIR" "$stable" <<'PY'
import json, sys
settings, ext, stable = sys.argv[1:4]
with open(settings, encoding="utf-8") as f:
    data = json.load(f)
assert data.get("integrationSentinel") == "keep", "se perdió el ajuste previo del usuario"
packages = data.get("packages")
assert isinstance(packages, list), "settings.json no tiene una lista 'packages'"
hits = [p for p in packages if ext in json.dumps(p) or stable in json.dumps(p)]
assert len(hits) == 1, "la extensión debe estar registrada exactamente una vez: %r" % (packages,)
print(json.dumps(packages, sort_keys=True))
PY
}

step "precondiciones"
node_ok || fail "se necesita Node>=$NODE_MAJOR con npm ($(node_desc))"
if have pi; then fail "ya hay un 'pi' en el PATH: este test necesita un entorno limpio"; fi
printf '{"integrationSentinel": "keep"}\n' > "$settings"

step "Pi fijado y extensión (primera pasada)"
pi_preflight
pi_install
configure_pi

[ "$(pi_version)" = "$PI_VERSION" ] || fail "Pi instalado es '$(pi_version)', se esperaba $PI_VERSION"
case "$(command -v pi)" in "$HOME"/.local/bin/pi) ;; *) fail "pi no quedó en $HOME/.local/bin" ;; esac
[ "$(git -C "$PI_EXT_DIR" rev-parse HEAD)" = "$PI_EXT_COMMIT" ] || fail "commit de la extensión distinto del fijado"
[ -L "$stable" ] || fail "falta el enlace estable $stable"
[ "$(cd "$stable" && pwd -P)" = "$(cd "$PI_EXT_DIR" && pwd -P)" ] || fail "el enlace estable no apunta a $PI_EXT_DIR"
[ -f "$settings" ] || fail "no existe $settings (¿se ignoró PI_CODING_AGENT_DIR?)"
first=$(packages_json) || fail "registro de la extensión en $settings incorrecto"

step "tests de la extensión (npm test)"
( cd "$PI_EXT_DIR" && npm test )

step "segunda pasada (idempotencia, sin duplicados)"
configure_pi # ext_verify exige worktree limpio: también comprueba que npm test no ensució el clon
second=$(packages_json) || fail "tras la segunda pasada el registro es incorrecto"
[ "$first" = "$second" ] || fail "los paquetes cambiaron entre pasadas: $first != $second"

printf 'OK integración real de Pi y pi-selection-editor (Pi %s, extensión %s)\n' "$PI_VERSION" "$PI_EXT_TAG"
