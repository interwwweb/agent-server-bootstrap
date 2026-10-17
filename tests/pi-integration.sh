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
import json, os, sys
from pathlib import Path

settings, ext, stable = sys.argv[1:4]
base = Path(settings).parent
targets = {Path(ext).resolve(), Path(stable).resolve()}


def local_path(entry):
    """Ruta local de un paquete (cadena u objeto con «source»); None si no es una ruta local.
    Las rutas relativas se resuelven contra el directorio de settings, no contra el cwd."""
    source = entry.get("source") if isinstance(entry, dict) else entry
    if not isinstance(source, str) or "://" in source or source.startswith(("npm:", "git:", "git@", "github:")):
        return None
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def is_ext(entry):
    return local_path(entry) in targets


# Autocomprobación de la normalización (rutas absolutas y relativas a settings, objetos, señuelos).
rel_ext = os.path.relpath(ext, base)
rel_stable = os.path.relpath(stable, base)
assert rel_ext != str(Path(ext)) and not Path(rel_ext).is_absolute(), "fixture relativa inválida"
for good in (ext, stable, rel_ext, rel_stable, {"source": ext}, {"source": rel_ext}):
    assert is_ext(good), "la normalización no reconoce %r" % (good,)
for bad in ("npm:otro-paquete", "git:github.com/x/y", "https://example.com/x.git", str(base / "otro"),
            os.path.join(os.path.dirname(rel_ext), "otro"), {"source": "npm:pi-selection-editor"}, 42):
    assert not is_ext(bad), "la normalización reconoce por error %r" % (bad,)

with open(settings, encoding="utf-8") as f:
    data = json.load(f)
assert data.get("integrationSentinel") == "keep", "se perdió el ajuste previo del usuario"
packages = data.get("packages")
assert isinstance(packages, list), "settings.json no tiene una lista 'packages'"
hits = [p for p in packages if is_ext(p)]
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
