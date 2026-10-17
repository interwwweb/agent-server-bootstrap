#!/usr/bin/env bash
# Integración REAL del módulo tailscale en un runner EFÍMERO de CI (Ubuntu 22.04/24.04, usuario no root
# con sudo sin contraseña). USA RED y escribe en /etc y /usr (clave y lista de apt, paquete). No la
# ejecutes en un servidor real: exige ASB_EPHEMERAL_RUNNER=1 como confirmación explícita.
# No ejecuta tailscale up/login/status ni usa credenciales; no llama a sudo directamente (solo install.sh).
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
KEYRING=/usr/share/keyrings/tailscale-archive-keyring.gpg
LIST=/etc/apt/sources.list.d/tailscale.list

fail() { printf 'FALLO integración: %s\n' "$*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

[ "${ASB_EPHEMERAL_RUNNER:-}" = 1 ] || fail "define ASB_EPHEMERAL_RUNNER=1 solo en un runner efímero (esto instala paquetes del sistema)"
[ "$(id -u)" != 0 ] || fail "ejecuta como usuario no root con sudo"
if command -v tailscale >/dev/null 2>&1 || command -v tailscaled >/dev/null 2>&1; then
  fail "Tailscale ya está presente: este test necesita un runner limpio"
fi
if [ -e "$KEYRING" ] || [ -e "$LIST" ]; then fail "ya existen $KEYRING o $LIST"; fi

daemon() {
  if command -v tailscaled >/dev/null 2>&1; then command -v tailscaled; else printf '/usr/sbin/tailscaled'; fi
}

step "primera instalación (--modules tailscale --apply --yes)"
bash "$REPO/install.sh" --modules tailscale --apply --yes

[ -s "$KEYRING" ] || fail "falta la clave $KEYRING"
# os-release es un archivo del sistema que ShellCheck no sigue (SC1091).
# shellcheck source=/dev/null
codename=$( . /etc/os-release; printf '%s' "$VERSION_CODENAME" )
grep -qxF "deb [signed-by=$KEYRING] https://pkgs.tailscale.com/stable/ubuntu $codename main" "$LIST" \
  || fail "la lista $LIST no contiene la línea firmada esperada"
status=$(dpkg-query -W -f='${Status}' tailscale) || fail "dpkg no conoce el paquete tailscale"
[ "$status" = "install ok installed" ] || fail "estado de dpkg inesperado: $status"
cli_version=$(tailscale version | head -n 1)
[ -n "$cli_version" ] || fail "tailscale version no devolvió nada"
daemon_version=$("$(daemon)" --version | head -n 1)
[ -n "$daemon_version" ] || fail "tailscaled --version no devolvió nada"
printf 'cliente: %s\ndemonio: %s\n' "$cli_version" "$daemon_version"

key_sum=$(sha256sum "$KEYRING")
list_sum=$(sha256sum "$LIST")
pkg_version=$(dpkg-query -W -f='${Version}' tailscale)

step "segunda ejecución (debe omitirse sin tocar nada)"
out=$(bash "$REPO/install.sh" --modules tailscale --apply --yes)
printf '%s\n' "$out"
printf '%s\n' "$out" | grep -qF "se omite" || fail "la segunda ejecución no se omitió"
if printf '%s\n' "$out" | grep -qE '^\+ (sudo|curl)'; then fail "la segunda ejecución invocó sudo o curl"; fi
[ "$(sha256sum "$KEYRING")" = "$key_sum" ] || fail "cambió la clave"
[ "$(sha256sum "$LIST")" = "$list_sum" ] || fail "cambió la lista"
[ "$(dpkg-query -W -f='${Version}' tailscale)" = "$pkg_version" ] || fail "cambió la versión del paquete"

printf 'OK integración real del módulo tailscale\n'
