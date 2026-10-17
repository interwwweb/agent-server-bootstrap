#!/usr/bin/env bash
# Integración REAL del módulo playwright (mod_playwright de install.sh) en un runner EFÍMERO de CI
# Ubuntu 22.04/24.04 con usuario no root y sudo sin contraseña. USA RED (npm, apt, descarga de Chromium)
# y ejecuta apt-get con sudo (lista fija de paquetes de sistema): no la ejecutes en un servidor real;
# exige ASB_EPHEMERAL_RUNNER=1 como confirmación explícita. HOME y PLAYWRIGHT_BROWSERS_PATH son temporales.
# No visita ningún sitio externo, no autentica, no ejecuta scripts de terceros ni el bootstrap completo.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
BASE=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
BASE=${BASE%/}

fail() { printf 'FALLO integración: %s\n' "$*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

[ "${ASB_EPHEMERAL_RUNNER:-}" = 1 ] || fail "define ASB_EPHEMERAL_RUNNER=1 solo en un runner efímero (esto instala paquetes del sistema con apt)"
[ "$(uname -s)" = Linux ] || fail "solo Ubuntu 22.04/24.04 (Linux)"
[ "$(id -u)" != 0 ] || fail "ejecuta como usuario no root con sudo"

# os-release es un archivo del sistema que ShellCheck no sigue (SC1091).
# shellcheck source=/dev/null
release=$( . /etc/os-release; printf '%s %s' "${ID:-}" "${VERSION_ID:-}" )
case "$release" in
  "ubuntu 22.04") codename=jammy ;;
  "ubuntu 24.04") codename=noble ;;
  *) fail "sistema no admitido ($release): solo Ubuntu 22.04/24.04" ;;
esac

TMP=$(mktemp -d "$BASE/asb-playwright-integration.XXXXXX")

# Entorno aislado: HOME propio ANTES de cargar install.sh (calcula sus rutas al cargarse).
export HOME="$TMP/home"
export PLAYWRIGHT_BROWSERS_PATH="$TMP/pw-browsers"
export NPM_CONFIG_PREFIX="$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME" "$PLAYWRIGHT_BROWSERS_PATH"

# install.sh es parte del repositorio y se carga dinámicamente (no hay main al hacer source).
# shellcheck source=/dev/null
. "$REPO/install.sh"

it_cleanup() {
  case "$TMP" in "$BASE"/asb-playwright-integration.*) rm -rf -- "$TMP" ;; esac
}
trap it_cleanup EXIT

# Variables que usan las funciones de install.sh cargadas arriba (ShellCheck no las sigue).
# shellcheck disable=SC2034
APPLY=1 SELECTED="playwright" OS_CODENAME="$codename"
cd "$HOME"

ws="$TOOLS/playwright"
pw="$ws/node_modules/.bin/playwright"

node_version_of() { node -p "require('$1').version"; }

check_versions() {
  [ "$(node_version_of "$ws/node_modules/@playwright/test/package.json")" = "$PLAYWRIGHT_TEST_VERSION" ] \
    || fail "@playwright/test instalado distinto de $PLAYWRIGHT_TEST_VERSION"
  [ "$(node_version_of "$ws/node_modules/@playwright/cli/package.json")" = "$PLAYWRIGHT_CLI_VERSION" ] \
    || fail "@playwright/cli instalado distinto de $PLAYWRIGHT_CLI_VERSION"
  # El ejecutable raíz y el núcleo deben ser los de @playwright/test (el CLI trae su propio playwright alfa, anidado).
  [ "$(node_version_of "$ws/node_modules/playwright/package.json")" = "$PLAYWRIGHT_TEST_VERSION" ] \
    || fail "el paquete playwright de la raíz no es $PLAYWRIGHT_TEST_VERSION"
  [ "$(node_version_of "$ws/node_modules/playwright-core/package.json")" = "$PLAYWRIGHT_TEST_VERSION" ] \
    || fail "playwright-core de la raíz no es $PLAYWRIGHT_TEST_VERSION"
  "$pw" --version | grep -qF "$PLAYWRIGHT_TEST_VERSION" || fail "el ejecutable raíz no informa $PLAYWRIGHT_TEST_VERSION"
  playwright --version | grep -qF "$PLAYWRIGHT_TEST_VERSION" || fail "el wrapper playwright no informa $PLAYWRIGHT_TEST_VERSION"
  if ! playwright-cli --version >/dev/null 2>&1; then
    playwright-cli --help >/dev/null 2>&1 || fail "el wrapper playwright-cli no responde a --version ni --help"
  fi
}

# Lanza Chromium sin cabeza con la API de @playwright/test y renderiza HTML local: sin sitios externos.
launch_chromium() {
  cat > "$TMP/smoke.js" <<'JS'
const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.route('**/*', (route) => route.abort());
    await page.setContent('<!doctype html><title>hello</title><h1>hola</h1>');
    const title = await page.title();
    if (title !== 'hello') throw new Error('título inesperado: ' + title);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
JS
  NODE_PATH="$ws/node_modules" node "$TMP/smoke.js" || fail "Chromium no arrancó o el título no es 'hello'"
}

step "precondiciones"
node_ok || fail "se necesita Node>=$NODE_MAJOR con npm ($(node_desc))"
if have playwright || have playwright-cli; then fail "ya hay playwright en el PATH: este test necesita un entorno limpio"; fi

step "primera pasada (npm fijado + apt estático + Chromium)"
mod_playwright
check_versions
launch_chromium

[ "$(node -p "require('$ws/package.json').dependencies['@playwright/test']")" = "$PLAYWRIGHT_TEST_VERSION" ] \
  || fail "package.json no fija la versión exacta de @playwright/test"
pkg_sum=$(sha256sum "$ws/package.json")
lock_sum=$(sha256sum "$ws/package-lock.json")
wrappers_sum=$(sha256sum "$HOME/.local/bin/playwright" "$HOME/.local/bin/playwright-cli")

step "segunda pasada (sin reinstalar npm; apt y navegador pueden repetirse)"
second=$(mod_playwright)
printf '%s\n' "$second"
if printf '%s\n' "$second" | grep -qF "npm install"; then fail "la segunda pasada volvió a ejecutar npm install"; fi
[ "$(sha256sum "$ws/package.json")" = "$pkg_sum" ] || fail "cambió package.json"
[ "$(sha256sum "$ws/package-lock.json")" = "$lock_sum" ] || fail "cambió package-lock.json"
[ "$(sha256sum "$HOME/.local/bin/playwright" "$HOME/.local/bin/playwright-cli")" = "$wrappers_sum" ] || fail "cambiaron los wrappers"
check_versions
launch_chromium

printf 'OK integración real de Playwright %s en Ubuntu %s\n' "$PLAYWRIGHT_TEST_VERSION" "$codename"
