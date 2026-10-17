#!/usr/bin/env bash
# agent-server-bootstrap: prepara un servidor Ubuntu para trabajar con agentes de código.
# Por defecto solo muestra el plan (dry-run): no escribe nada ni usa la red.
set -euo pipefail

PROG="agent-server-bootstrap"
DEFAULT_MODULES="base node python agents cloud remote playwright"
KNOWN_MODULES="$DEFAULT_MODULES docker"
NODE_MAJOR=24
NODE_DIST="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"
APT_BASE_PKGS=(git curl wget ca-certificates jq ripgrep fd-find fzf unzip zip build-essential pkg-config python3 python3-venv python3-pip tmux mosh gh)
APT_DOCKER_PKGS=(docker.io docker-compose-v2)
# Pi fijado (excepción a «latest») por compatibilidad con pi-selection-editor (Pi >=0.87.1 <0.88.0).
PI_PKG="@earendil-works/pi-coding-agent"
PI_VERSION=0.87.1
PI_EXT_URL="https://github.com/interwwweb/pi-selection-editor.git"
PI_EXT_TAG=v0.1.2
PI_EXT_COMMIT=93d60682e2aeca492d05c19ca3dbc3b46f360241

ASB_HOME="$HOME/.local/share/$PROG"
LOCAL_BIN="$HOME/.local/bin"
NODE_ROOT="$ASB_HOME/node"
NODE_CUR="$NODE_ROOT/current"
TOOLS="$ASB_HOME/tools"
PI_EXT_DIR="$ASB_HOME/extensions/pi-selection-editor"
ENV_FILE="$ASB_HOME/env.sh"
PROFILE_BEGIN="# >>> $PROG >>>"
PROFILE_END="# <<< $PROG <<<"

APPLY=0 YES=0 DRY=0 WITH_PI=0 WITH_DOCKER=0 VENDOR=0 MODULES="" MODULES_SET=0
SELECTED="" NODE_ARCH="" WORK=""

log() { printf '%s\n' "$*"; }
warn() { printf 'AVISO: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage_error() { printf 'ERROR: %s\nUsa --help para ver las opciones.\n' "$*" >&2; exit 2; }
have() { command -v "$1" >/dev/null 2>&1; }
need() { have "$1" || die "falta el comando requerido: $1"; }
selected() { case " $SELECTED " in *" $1 "*) return 0 ;; esac; return 1; }
# Módulos que descargan y ejecutan scripts de terceros (uv, Claude Code, Herdr, moshi-hook).
vendor_selected() { selected python || selected agents || selected remote; }
# Módulos que instalan CLIs de usuario y necesitan el PATH persistente.
needs_env() { selected node || selected python || selected agents || selected cloud || selected remote || selected playwright; }
needs_npm() { selected agents || selected cloud || selected playwright; }

usage() {
  cat <<'EOF'
agent-server-bootstrap — prepara un servidor Ubuntu 22.04/24.04 (amd64/arm64)
para trabajar con agentes de código. Debe ejecutarlo un usuario NO root con sudo.

Uso:
  ./install.sh [opciones]

Por defecto es un DRY-RUN: muestra el plan, no escribe nada ni usa la red.

Opciones:
  --apply                 Aplica los cambios (requiere también --yes).
  --yes, -y               Confirma --apply.
  --dry-run               Modo por defecto, explícito.
  --modules LISTA         Módulos separados por comas (no puede ir vacía). Por defecto:
                          base,node,python,agents,cloud,remote,playwright
                          Disponibles: base node python agents cloud remote playwright docker
  --with-docker           Añade el módulo docker (opcional).
  --with-pi               Instala también Pi fijado en 0.87.1 (si falta; uno existente debe ser
                          0.87.x con x>=1) y la extensión pi-selection-editor v0.1.2 (commit
                          fijado, con su instalador upstream). Requiere agents.
  --vendor-installers     Autoriza los scripts de terceros que se descargan y ejecutan:
                          uv (python), Claude Code y Herdr (agents), moshi-hook (remote).
                          Obligatorio con --apply si se elige python, agents o remote.
  -h, --help              Muestra esta ayuda (funciona en cualquier sistema).

No toca SSH, firewall, credenciales ni grupos de usuario. Los logins son manuales.
Documentación: README.md y SECURITY.md.
EOF
}

parse_args() {
  local a
  for a in "$@"; do case "$a" in -h|--help) usage; exit 0 ;; esac; done
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply) APPLY=1 ;;
      --yes|-y) YES=1 ;;
      --dry-run) DRY=1 ;;
      --modules)
        [ $# -ge 2 ] || usage_error "--modules requiere un valor"
        MODULES=$2; MODULES_SET=1; shift ;;
      --modules=*) MODULES=${1#*=}; MODULES_SET=1 ;;
      --with-docker) WITH_DOCKER=1 ;;
      --with-pi) WITH_PI=1 ;;
      --vendor-installers) VENDOR=1 ;;
      *) usage_error "argumento desconocido: $1" ;;
    esac
    shift
  done
}

normalize_modules() {
  local list m sel=""
  if [ "$MODULES_SET" = 1 ]; then list=${MODULES//,/ }; else list=$DEFAULT_MODULES; fi
  case "$list" in *[![:space:]]*) ;; *) usage_error "--modules no puede estar vacío" ;; esac
  if [ "$WITH_DOCKER" = 1 ]; then list="$list docker"; fi
  set -f
  for m in $list; do
    case " $KNOWN_MODULES " in *" $m "*) ;; *) set +f; usage_error "módulo desconocido: $m" ;; esac
    case " $sel " in *" $m "*) ;; *) sel="$sel $m" ;; esac
  done
  set +f
  SELECTED=""
  for m in $KNOWN_MODULES; do
    case " $sel " in *" $m "*) SELECTED="$SELECTED $m" ;; esac
  done
  SELECTED=${SELECTED# }
}

validate_args() {
  if [ "$APPLY" = 1 ] && [ "$DRY" = 1 ]; then usage_error "--apply y --dry-run son incompatibles"; fi
  if [ "$APPLY" = 1 ] && [ "$YES" != 1 ]; then usage_error "--apply requiere confirmar con --yes"; fi
  if [ "$APPLY" != 1 ] && [ "$YES" = 1 ]; then usage_error "--yes solo se usa junto con --apply"; fi
  normalize_modules
  if [ "$WITH_PI" = 1 ] && ! selected agents; then usage_error "--with-pi requiere el módulo agents"; fi
  if [ "$APPLY" = 1 ] && [ "$VENDOR" != 1 ] && vendor_selected; then
    usage_error "los módulos python/agents/remote ejecutan scripts de terceros (uv, Claude Code, Herdr, moshi-hook): añade --vendor-installers o quita esos módulos"
  fi
}

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

# Node >= NODE_MAJOR y npm disponibles.
node_ok() {
  local major
  have node && have npm || return 1
  major=$(node_major)
  case "$major" in ''|*[!0-9]*) return 1 ;; esac
  [ "$major" -ge "$NODE_MAJOR" ]
}

node_desc() {
  if ! have node; then printf 'sin node'; return 0; fi
  printf 'node %s' "$(node --version 2>/dev/null || echo desconocido)"
  if ! have npm; then printf ', sin npm'; fi
}

preflight() {
  local osr=/etc/os-release uname_m euid id ver
  euid=$(id -u); uname_m=$(uname -m)
  # Solo en dry-run y con ASB_TEST=1 se pueden simular el sistema, el arco y el uid (tests).
  if [ "${ASB_TEST:-}" = 1 ] && [ "$APPLY" != 1 ]; then
    osr=${ASB_OS_RELEASE:-$osr}; euid=${ASB_EUID:-$euid}; uname_m=${ASB_ARCH:-$uname_m}
  fi
  [ -r "$osr" ] || die "no se puede leer $osr: solo se admite Ubuntu 22.04/24.04"
  # os-release es un archivo externo elegido en ejecución: ShellCheck no puede seguirlo (SC1090/SC1091).
  # shellcheck source=/dev/null
  id=$( . "$osr" >/dev/null 2>&1; printf '%s' "${ID:-}" )
  # shellcheck source=/dev/null
  ver=$( . "$osr" >/dev/null 2>&1; printf '%s' "${VERSION_ID:-}" )
  [ "$id" = ubuntu ] || die "sistema no admitido ($id): solo Ubuntu 22.04/24.04"
  case "$ver" in 22.04|24.04) ;; *) die "Ubuntu $ver no admitido: solo 22.04 y 24.04" ;; esac
  case "$uname_m" in
    x86_64|amd64) NODE_ARCH=x64 ;;
    aarch64|arm64) NODE_ARCH=arm64 ;;
    *) die "arquitectura no admitida ($uname_m): solo amd64/arm64" ;;
  esac
  [ "$euid" != 0 ] || die "no ejecutes como root ni con sudo: usa un usuario normal con sudo (el script invoca sudo solo donde hace falta)"
  if [ "$APPLY" = 1 ]; then
    local c
    for c in tar sha256sum mktemp; do need "$c"; done
    if ! selected base && { selected node || vendor_selected; }; then need curl; fi
    if selected base || selected docker; then need apt-get; fi
    if selected base || selected docker || selected playwright; then
      need sudo
      sudo -v || die "este usuario no puede usar sudo"
    fi
    if [ "$WITH_PI" = 1 ]; then pi_preflight; fi
    # Dependencias comprobadas antes de cambiar nada.
    if needs_npm && ! selected node && ! node_ok; then
      die "los módulos agents/cloud/playwright necesitan Node>=$NODE_MAJOR y npm (hay: $(node_desc)): incluye el módulo node"
    fi
    if selected node && ! node_ok && { [ -e "$NODE_CUR" ] || [ -L "$NODE_CUR" ]; }; then
      die "$NODE_CUR ya existe pero su Node no es >=$NODE_MAJOR con npm: revísalo o elimina ese enlace a mano"
    fi
  fi
}

cleanup() { if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf -- "$WORK"; fi; }

run() {
  if [ "$APPLY" = 1 ]; then log "+ $*"; "$@"; else log "[dry-run] $*"; fi
}

fetch() { curl -fsSL --proto '=https' --tlsv1.2 --retry 3 -o "$2" "$1"; }

# Descarga a un archivo temporal y lo ejecuta con el intérprete indicado (nunca curl | sh).
download_run() { # nombre binario url intérprete [args...]
  local name=$1 bin=$2 url=$3 interp=$4 f; shift 4
  if have "$bin"; then log "  $name: '$bin' ya existe, se omite"; return 0; fi
  if [ "$APPLY" = 1 ] && [ "$VENDOR" != 1 ]; then die "$name es un script de terceros: requiere --vendor-installers"; fi
  if [ "$APPLY" != 1 ]; then
    log "[dry-run] $name: descargar $url a un archivo temporal y ejecutar '$interp <archivo> $*'"
    return 0
  fi
  f=$(mktemp "$WORK/dl.XXXXXX")
  log "+ curl $url -> $f"
  fetch "$url" "$f"
  [ -s "$f" ] || die "descarga vacía: $url"
  log "+ $interp <archivo> $*"
  ( cd "$HOME" && "$interp" "$f" "$@" )
}

require_node() { # módulo
  if node_ok; then return 0; fi
  if [ "$APPLY" = 1 ]; then die "el módulo $1 necesita Node>=$NODE_MAJOR y npm (hay: $(node_desc)): incluye el módulo node"; fi
  selected node || warn "el módulo $1 necesita Node>=$NODE_MAJOR y npm (hay: $(node_desc)); incluye el módulo node"
}

check_npm_prefix() {
  local p; p=$(npm prefix -g)
  case "$p" in "$HOME"/*) ;; *) die "el prefijo global de npm ($p) no está en tu HOME; no se usa sudo con npm" ;; esac
}

npm_global() { # binario paquete [flags...]
  local bin=$1 pkg=$2; shift 2
  if have "$bin"; then log "  $pkg: '$bin' ya existe, se omite"; return 0; fi
  if [ "$APPLY" = 1 ]; then need npm; check_npm_prefix; fi
  run npm install -g --no-audit --no-fund "$@" "$pkg"
}

# Versión de Pi: última palabra de la primera línea de `pi --version`, sin «v» inicial.
pi_version() {
  local out
  out=$(pi --version 2>&1) || return 1
  out=${out%%$'\n'*}; out=${out##* }
  printf '%s' "${out#v}"
}

# Pi estable 0.87.N con N>=1 (compatible con pi-selection-editor: >=0.87.1 <0.88.0).
pi_version_ok() {
  local patch
  case "$1" in 0.87.*) ;; *) return 1 ;; esac
  patch=${1#0.87.}
  case "$patch" in ''|*[!0-9]*) return 1 ;; esac
  [ "$patch" -ge 1 ]
}

pi_check_version() {
  local v
  v=$(pi_version) || die "no se pudo ejecutar 'pi --version': no se reemplaza ni se toca el Pi existente"
  pi_version_ok "$v" || die "Pi $v no es compatible con pi-selection-editor (se requiere >=0.87.1 <0.88.0 estable); no se reemplaza ni se baja de versión"
}

# Comprueba un clon existente de la extensión: origin exacto, commit fijado, worktree limpio.
ext_verify() { # directorio
  local d=$1 origin head dirty
  if [ -L "$d" ] || [ ! -d "$d" ]; then die "$d existe y no es un directorio real: no se modifica"; fi
  origin=$(git -C "$d" remote get-url origin 2>/dev/null) || die "$d no es un clon de $PI_EXT_URL: no se modifica"
  [ "$origin" = "$PI_EXT_URL" ] || die "$d tiene origin $origin (se esperaba $PI_EXT_URL): no se modifica"
  head=$(git -C "$d" rev-parse HEAD 2>/dev/null) || die "no se pudo leer el commit de $d: no se modifica"
  [ "$head" = "$PI_EXT_COMMIT" ] || die "$d está en $head (se esperaba $PI_EXT_COMMIT): no se modifica"
  dirty=$(git -C "$d" status --porcelain --untracked-files=all 2>/dev/null) || die "no se pudo comprobar el estado de $d: no se modifica"
  [ -z "$dirty" ] || die "$d tiene cambios locales o archivos sin seguimiento: no se modifica"
  [ -f "$d/scripts/install.sh" ] || die "falta $d/scripts/install.sh"
}

# Solo con --apply, antes de cualquier cambio.
pi_preflight() {
  if [ -e "$PI_EXT_DIR" ] || [ -L "$PI_EXT_DIR" ]; then
    need git
    ext_verify "$PI_EXT_DIR"
  elif ! selected base; then
    need git
  fi
  need bash
  if have pi; then pi_check_version; fi
}

pi_install() {
  log "  Pi: fijado en $PI_PKG@$PI_VERSION (excepción a «latest»); uno existente debe ser 0.87.x con x>=1 y no se reemplaza"
  npm_global pi "$PI_PKG@$PI_VERSION" --ignore-scripts
  if [ "$APPLY" = 1 ]; then
    have pi || die "pi no quedó disponible tras instalar $PI_PKG@$PI_VERSION"
    pi_check_version
  fi
}

ext_clone() {
  local parent tmp
  parent=$(dirname "$PI_EXT_DIR")
  mkdir -p "$parent"
  tmp=$(mktemp -d "$parent/.tmp.XXXXXX")
  log "+ git clone --branch $PI_EXT_TAG --depth 1 $PI_EXT_URL"
  if ! git clone --quiet --branch "$PI_EXT_TAG" --depth 1 "$PI_EXT_URL" "$tmp/repo"; then
    rm -rf -- "$tmp"; die "falló git clone de $PI_EXT_URL ($PI_EXT_TAG)"
  fi
  if ! ( ext_verify "$tmp/repo" ); then
    rm -rf -- "$tmp"; die "el clon descargado no coincide con el commit fijado $PI_EXT_COMMIT: no se instala"
  fi
  if [ -e "$PI_EXT_DIR" ] || [ -L "$PI_EXT_DIR" ]; then
    rm -rf -- "$tmp"; die "$PI_EXT_DIR apareció durante la clonación: no se sobrescribe"
  fi
  mv "$tmp/repo" "$PI_EXT_DIR"
  rmdir "$tmp"
}

# Extensión pi-selection-editor: clon fijado + instalador upstream (pi install). No edita JSON de Pi.
configure_pi() {
  log "== pi-selection-editor $PI_EXT_TAG =="
  if [ "$APPLY" != 1 ]; then
    log "[dry-run] git clone --branch $PI_EXT_TAG --depth 1 $PI_EXT_URL a un directorio temporal junto a $PI_EXT_DIR"
    log "[dry-run] verificar git rev-parse HEAD = $PI_EXT_COMMIT y renombrar solo si $PI_EXT_DIR no existe"
    log "[dry-run] si $PI_EXT_DIR existe: exigir origin $PI_EXT_URL, ese commit y worktree limpio (con untracked); si no, falla sin tocarlo"
    log "[dry-run] bash $PI_EXT_DIR/scripts/install.sh (instalador upstream: pi install; respeta PI_CODING_AGENT_DIR)"
    return 0
  fi
  if [ -e "$PI_EXT_DIR" ] || [ -L "$PI_EXT_DIR" ]; then
    ext_verify "$PI_EXT_DIR"
    log "  $PI_EXT_DIR ya existe y coincide con el commit fijado; se reutiliza"
  else
    ext_clone
  fi
  # El instalador upstream es idempotente y hereda PI_CODING_AGENT_DIR / PI_SELECTION_EDITOR_DIR del entorno.
  run bash "$PI_EXT_DIR/scripts/install.sh"
}

npm_workspace() { # directorio paquetes...
  local dir=$1; shift
  if [ "$APPLY" != 1 ]; then
    log "[dry-run] mkdir -p $dir; npm install --prefix $dir $*"
    return 0
  fi
  need npm
  mkdir -p "$dir"
  [ -e "$dir/package.json" ] || printf '{\n  "private": true\n}\n' > "$dir/package.json"
  log "+ npm install --prefix $dir $*"
  npm install --prefix "$dir" --no-audit --no-fund "$@"
}

# Wrapper en ~/.local/bin que ejecuta un binario con ruta absoluta; nunca sobrescribe.
write_wrapper() { # nombre destino
  local w=$LOCAL_BIN/$1 t=$2 nodebin=""
  if [ "$APPLY" != 1 ]; then log "[dry-run] wrapper $w -> $t (si no existe)"; return 0; fi
  if [ -e "$w" ] || [ -L "$w" ]; then log "  $w ya existe, no se sobrescribe"; return 0; fi
  mkdir -p "$LOCAL_BIN"
  if have node; then nodebin=$(dirname "$(command -v node)"); fi
  # Las comillas simples son intencionadas: el wrapper generado expande $PATH al ejecutarse (SC2016).
  # shellcheck disable=SC2016
  {
    printf '#!/usr/bin/env bash\n'
    if [ -n "$nodebin" ]; then printf 'export PATH=%q:"$PATH"\n' "$nodebin"; fi
    printf 'exec %q "$@"\n' "$t"
  } > "$w"
  chmod 755 "$w"
  log "  wrapper creado: $w"
}

ensure_profile() {
  local p=$HOME/.profile
  if [ -f "$p" ] && grep -qF "$PROFILE_BEGIN" "$p"; then
    log "  ~/.profile ya contiene el bloque de $PROG"; return 0
  fi
  # Las comillas simples son intencionadas: ~/.profile debe expandir $HOME al cargarse (SC2016).
  # shellcheck disable=SC2016
  {
    printf '\n%s\n' "$PROFILE_BEGIN"
    printf 'if [ -f "$HOME/.local/share/%s/env.sh" ]; then\n' "$PROG"
    printf '  . "$HOME/.local/share/%s/env.sh"\n' "$PROG"
    printf 'fi\n%s\n' "$PROFILE_END"
  } >> "$p"
  log "  bloque añadido a ~/.profile"
}

# Se ejecuta una sola vez, antes de los módulos, si alguno instala CLIs de usuario.
ensure_env() {
  if [ "$APPLY" != 1 ]; then
    log "[dry-run] crear $ENV_FILE (si no existe) y añadir un bloque guardado a ~/.profile"
    return 0
  fi
  mkdir -p "$ASB_HOME" "$LOCAL_BIN"
  if [ -e "$ENV_FILE" ]; then
    log "  $ENV_FILE ya existe, no se sobrescribe"
  else
    cat > "$ENV_FILE" <<'EOF'
# Generado por agent-server-bootstrap. Se carga desde ~/.profile.
export PATH="$HOME/.local/share/agent-server-bootstrap/node/current/bin:$HOME/.local/bin:$PATH"
export NPM_CONFIG_PREFIX="$HOME/.local"
EOF
    log "  creado $ENV_FILE"
  fi
  ensure_profile
}

install_node() {
  local sums="$WORK/SHASUMS256.txt" line file ver dest tmp
  fetch "$NODE_DIST/SHASUMS256.txt" "$sums"
  line=$(awk -v a="$NODE_ARCH" -v m="$NODE_MAJOR" \
    '$2 ~ ("^node-v" m "\\.[0-9]+\\.[0-9]+-linux-" a "\\.tar\\.gz$")' "$sums")
  if [ -z "$line" ] || [ "$(printf '%s\n' "$line" | wc -l)" -ne 1 ]; then
    die "no se encontró un único tarball de Node v$NODE_MAJOR para $NODE_ARCH en SHASUMS256.txt"
  fi
  file=$(printf '%s\n' "$line" | awk '{print $2}')
  ver=${file#node-}; ver=${ver%-linux-*}
  dest=$NODE_ROOT/$ver
  # Falla antes de extraer nada si el enlace «current» ya apunta a otro Node.
  if [ -e "$NODE_CUR" ] || [ -L "$NODE_CUR" ]; then
    [ "$(readlink "$NODE_CUR" 2>/dev/null || true)" = "$dest" ] \
      || die "$NODE_CUR ya existe y no apunta a $dest: no se modifica y su Node no es compatible; revísalo o elimina ese enlace a mano"
  fi
  if [ -e "$dest" ]; then
    log "  $dest ya existe, no se vuelve a extraer"
  else
    fetch "$NODE_DIST/$file" "$WORK/$file"
    ( cd "$WORK" && printf '%s\n' "$line" | sha256sum -c - ) || die "checksum SHA-256 de $file no coincide"
    mkdir -p "$NODE_ROOT"
    tmp=$(mktemp -d "$NODE_ROOT/.tmp.XXXXXX")
    tar -xzf "$WORK/$file" -C "$tmp" --strip-components=1
    mv -n "$tmp" "$dest"
    log "  Node $ver instalado en $dest"
  fi
  if [ ! -e "$NODE_CUR" ] && [ ! -L "$NODE_CUR" ]; then ln -s "$dest" "$NODE_CUR"; fi
}

mod_base() {
  log "== base: paquetes apt =="
  run sudo env DEBIAN_FRONTEND=noninteractive apt-get update
  run sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_BASE_PKGS[@]}"
  if [ "$APPLY" != 1 ]; then
    log "[dry-run] enlace $LOCAL_BIN/fd -> fdfind (si fd no existe)"
  elif ! have fd && have fdfind && [ ! -e "$LOCAL_BIN/fd" ] && [ ! -L "$LOCAL_BIN/fd" ]; then
    mkdir -p "$LOCAL_BIN"; ln -s "$(command -v fdfind)" "$LOCAL_BIN/fd"
  fi
}

mod_node() {
  log "== node: Node v$NODE_MAJOR (tarball oficial) =="
  if node_ok; then
    log "  node $(node --version) ya es compatible (>=$NODE_MAJOR, con npm), se omite la descarga"
  elif [ "$APPLY" != 1 ]; then
    log "[dry-run] descargar $NODE_DIST/SHASUMS256.txt y el tarball linux-$NODE_ARCH más reciente de v$NODE_MAJOR"
    log "[dry-run] verificar SHA-256, extraer en $NODE_ROOT/<versión> y enlazar $NODE_CUR (sin sobrescribir)"
  else
    install_node
    node_ok || die "tras la instalación, node no es >= $NODE_MAJOR con npm"
  fi
  npm_global pnpm pnpm
}

mod_python() {
  log "== python: uv (script de terceros) =="
  download_run uv uv https://astral.sh/uv/install.sh sh
}

mod_agents() {
  log "== agents: Codex, Claude Code, Herdr (Pi opcional) =="
  require_node agents
  npm_global codex @openai/codex
  download_run "Claude Code" claude https://claude.ai/install.sh bash stable
  if [ "$WITH_PI" = 1 ]; then pi_install; configure_pi; fi
  download_run Herdr herdr https://herdr.dev/install.sh sh
}

mod_cloud() {
  log "== cloud: vercel, sanity, supabase =="
  require_node cloud
  npm_global vercel vercel
  npm_global sanity @sanity/cli
  if have supabase; then
    log "  supabase: 'supabase' ya existe, se omite"
  else
    local ws=$TOOLS/supabase
    if [ ! -x "$ws/node_modules/.bin/supabase" ] || [ "$APPLY" != 1 ]; then npm_workspace "$ws" supabase; fi
    write_wrapper supabase "$ws/node_modules/.bin/supabase"
  fi
}

mod_remote() {
  log "== remote: moshi-hook (mosh viene en base) =="
  download_run moshi-hook moshi-hook https://getmoshi.app/install.sh sh
  have mosh || warn "mosh no está instalado: incluye el módulo base"
}

mod_playwright() {
  log "== playwright: @playwright/test y @playwright/cli en un workspace dedicado =="
  require_node playwright
  local ws=$TOOLS/playwright pw
  pw=$ws/node_modules/.bin/playwright
  if [ ! -x "$pw" ] || [ "$APPLY" != 1 ]; then npm_workspace "$ws" @playwright/test @playwright/cli; fi
  write_wrapper playwright "$pw"
  write_wrapper playwright-cli "$ws/node_modules/.bin/playwright-cli"
  # Equivalente a «install --with-deps»: dependencias del sistema con sudo y navegador como usuario.
  run sudo env "PATH=$PATH" "$pw" install-deps chromium
  run "$pw" install chromium
}

mod_docker() {
  log "== docker (opcional): docker.io y docker-compose-v2 =="
  # Sin el módulo base nadie ha refrescado el índice de apt todavía.
  selected base || run sudo env DEBIAN_FRONTEND=noninteractive apt-get update
  run sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_DOCKER_PKGS[@]}"
  log "  No se modifican grupos. Usa 'sudo docker': equivale a acceso root."
}

banner() {
  if [ "$APPLY" = 1 ]; then log "$PROG: APLICANDO cambios (módulos: $SELECTED)"
  else
    log "$PROG: DRY-RUN, no se escribe nada ni se usa la red (módulos: $SELECTED)"
    if [ "$VENDOR" != 1 ] && vendor_selected; then
      log "NOTA: con --apply, python/agents/remote exigirán --vendor-installers (scripts de terceros)."
    fi
  fi
}

summary() {
  local logins="gh auth login, vercel login, supabase login, sanity login, codex login, claude"
  log
  if [ "$APPLY" != 1 ]; then log "Dry-run terminado. Para aplicar: ./install.sh --apply --yes [--vendor-installers]"; return 0; fi
  if [ "$WITH_PI" = 1 ]; then logins="$logins, pi → /login"; fi
  log "Listo. Abre una sesión nueva (o ejecuta: . ~/.profile) y comprueba con ./doctor.sh"
  if [ "$WITH_PI" = 1 ]; then
    log "Pi: ejecuta /reload en las sesiones abiertas y comprueba a mano con /selection-editor status."
  fi
  log "Logins manuales (no se hacen aquí): $logins"
}

main() {
  parse_args "$@"
  validate_args
  export PATH="$NODE_CUR/bin:$LOCAL_BIN:$PATH"
  export NPM_CONFIG_PREFIX="$HOME/.local"
  export UV_NO_MODIFY_PATH=1
  preflight
  if [ "$APPLY" = 1 ]; then
    WORK=$(mktemp -d)
    trap cleanup EXIT
    cd "$HOME"
  fi
  banner
  if needs_env; then ensure_env; fi
  local m
  for m in $SELECTED; do "mod_$m"; done
  summary
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
