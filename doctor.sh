#!/usr/bin/env bash
# Comprueba que los comandos de cada módulo existen. No hace login ni modifica nada.
# La existencia (check) y la versión (--versions) son comprobaciones distintas.
set -euo pipefail
set -f # sin expansión de globs al procesar la lista de módulos

PROG="agent-server-bootstrap"
ASB_HOME="$HOME/.local/share/$PROG"
DEFAULT_MODULES="base node python agents cloud remote tailscale playwright"
KNOWN_MODULES="$DEFAULT_MODULES docker"
NODE_MAJOR=24
MODULES="" MODULES_SET=0 SMOKE=0 VERSIONS=0 WITH_PI=0 MISSING=0

usage() {
  cat <<'EOF'
Uso: ./doctor.sh [opciones]

  --modules LISTA   Módulos a comprobar (no puede ir vacía; por defecto los mismos
                    que install.sh, sin docker).
                    Disponibles: base node python agents cloud remote tailscale playwright docker
  --with-pi         Comprueba también pi (versión >=0.87.1 <0.88.0) y la extensión
                    pi-selection-editor (clon, commit fijado y enlace estable);
                    requiere el módulo agents.
  --versions        Imprime las versiones instaladas (para guardar en un informe).
                    Un comando que existe pero no puede ejecutar --version se
                    informa como FALLO y cuenta como comprobación fallida.
  --smoke           Lanza Chromium con Playwright y renderiza HTML local (setContent);
                    no hace llamadas web externas.
  -h, --help        Muestra esta ayuda.

Sale con código 1 si falta algún comando o falla alguna comprobación.
EOF
}

usage_error() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

a_help=0
for a in "$@"; do case "$a" in -h|--help) a_help=1 ;; esac; done
if [ "$a_help" = 1 ]; then usage; exit 0; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --modules) [ $# -ge 2 ] || usage_error "--modules requiere un valor"; MODULES=$2; MODULES_SET=1; shift ;;
    --modules=*) MODULES=${1#*=}; MODULES_SET=1 ;;
    --with-pi) WITH_PI=1 ;;
    --versions) VERSIONS=1 ;;
    --smoke) SMOKE=1 ;;
    *) usage_error "argumento desconocido: $1" ;;
  esac
  shift
done
if [ "$MODULES_SET" = 1 ]; then MODULES=${MODULES//,/ }; else MODULES=$DEFAULT_MODULES; fi
case "$MODULES" in *[![:space:]]*) ;; *) usage_error "--modules no puede estar vacío" ;; esac
for m in $MODULES; do
  case " $KNOWN_MODULES " in *" $m "*) ;; *) usage_error "módulo desconocido: $m" ;; esac
done

export PATH="$ASB_HOME/node/current/bin:$HOME/.local/bin:$PATH"
have() { command -v "$1" >/dev/null 2>&1; }
selected() { case " $MODULES " in *" $1 "*) return 0 ;; esac; return 1; }

if [ "$WITH_PI" = 1 ] && ! selected agents; then usage_error "--with-pi requiere el módulo agents"; fi

check() { # comando [alternativa]
  local c
  for c in "$@"; do
    if have "$c"; then printf 'ok       %s (%s)\n' "$1" "$(command -v "$c")"; return 0; fi
  done
  printf 'FALTA    %s\n' "$1"; MISSING=$((MISSING + 1))
}

PI_EXT_COMMIT=93d60682e2aeca492d05c19ca3dbc3b46f360241
PI_EXT_DIR="$ASB_HOME/extensions/pi-selection-editor"

fail() { printf 'FALLO    %s\n' "$*"; MISSING=$((MISSING + 1)); }

# Pi estable 0.87.N con N>=1 (compatible con pi-selection-editor: >=0.87.1 <0.88.0).
check_pi_version() {
  local out rc=0 v patch=""
  out=$(pi --version 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then fail "pi --version terminó con código $rc"; return 0; fi
  v=${out%%$'\n'*}; v=${v##* }; v=${v#v}
  case "$v" in 0.87.*) patch=${v#0.87.} ;; esac
  case "$patch" in
    ''|*[!0-9]*) fail "pi $v no es compatible con pi-selection-editor (se requiere >=0.87.1 <0.88.0)" ;;
    *) if [ "$patch" -ge 1 ]; then printf 'ok       pi %s compatible (>=0.87.1 <0.88.0)\n' "$v"
       else fail "pi $v no es compatible con pi-selection-editor (se requiere >=0.87.1 <0.88.0)"; fi ;;
  esac
}

# Solo sistema de archivos y git en lectura: no comprueba el registro en Pi ni el editor en ejecución.
check_pi_extension() {
  local head stable
  if [ ! -d "$PI_EXT_DIR" ]; then fail "extensión pi-selection-editor no encontrada en $PI_EXT_DIR"; return 0; fi
  if ! have git; then fail "no se puede comprobar el commit de la extensión: falta git"; return 0; fi
  head=$(git -C "$PI_EXT_DIR" rev-parse HEAD 2>/dev/null) || head=""
  if [ "$head" = "$PI_EXT_COMMIT" ]; then printf 'ok       extensión pi-selection-editor en %s (%s)\n' "$PI_EXT_DIR" "$head"
  else fail "extensión en $PI_EXT_DIR está en '${head:-desconocido}' (se esperaba $PI_EXT_COMMIT)"; fi
  stable=${PI_SELECTION_EDITOR_DIR:-$HOME/.local/share/pi-selection-editor}
  if [ -d "$stable" ] && [ "$(cd "$stable" && pwd -P)" = "$(cd "$PI_EXT_DIR" && pwd -P)" ]; then
    printf 'ok       enlace estable %s\n' "$stable"
  else
    fail "el enlace estable $stable no apunta a $PI_EXT_DIR"
  fi
  echo "nota     comprueba a mano en Pi: /reload y /selection-editor status (doctor no lo verifica)"
}

selected base && for c in git curl wget jq rg fzf unzip zip gcc pkg-config python3 tmux mosh gh; do check "$c"; done
selected base && check fd fdfind
if selected node; then
  check node; check npm; check pnpm
  if have node; then
    major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
    nver=$(node --version 2>/dev/null || echo desconocida)
    case "$major" in ''|*[!0-9]*) major=0 ;; esac
    if [ "$major" -ge "$NODE_MAJOR" ]; then printf 'ok       node >= %s (%s)\n' "$NODE_MAJOR" "$nver"
    else printf 'FALTA    node >= %s (hay %s)\n' "$NODE_MAJOR" "$nver"; MISSING=$((MISSING + 1)); fi
  fi
fi
selected python && check uv
if selected agents; then check codex; check claude; check herdr; if [ "$WITH_PI" = 1 ]; then check pi; if have pi; then check_pi_version; fi; check_pi_extension; fi; fi
selected cloud && for c in vercel sanity supabase wrangler linear; do check "$c"; done
selected remote && { check moshi-hook; check mosh; }
# Solo existencia: no se consulta estado, IP, red ni autenticación de Tailscale. tailscaled vive en /usr/sbin.
selected tailscale && { check tailscale; check tailscaled /usr/sbin/tailscaled; }
selected playwright && { check playwright; check playwright-cli; }
selected docker && check docker

if [ "$VERSIONS" = 1 ]; then
  echo
  echo "Versiones (informe; las dependencias son «latest», no hay reproducibilidad garantizada):"
  echo "fecha: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ -r /etc/os-release ]; then
    # os-release es un archivo del sistema que ShellCheck no sigue (SC1091).
    # shellcheck source=/dev/null
    ( . /etc/os-release; echo "so: ${PRETTY_NAME:-desconocido}" )
  fi
  echo "arquitectura: $(uname -m)"
  for c in git node npm pnpm python3 uv jq rg tmux mosh gh codex claude herdr pi vercel sanity supabase wrangler linear playwright docker tailscale; do
    if have "$c"; then
      rc=0
      vflag=--version
      # Tailscale documenta el subcomando `version`; no se consulta estado ni red.
      if [ "$c" = tailscale ]; then vflag=version; fi
      out=$("$c" "$vflag" 2>&1) || rc=$?
      if [ "$rc" -eq 0 ]; then
        printf '%-12s %s\n' "$c" "${out%%$'\n'*}"
      else
        printf 'FALLO    %-12s existe pero "%s" terminó con código %s: %s\n' "$c" "$vflag" "$rc" "${out%%$'\n'*}"
        MISSING=$((MISSING + 1))
      fi
    fi
  done
fi

if [ "$SMOKE" = 1 ]; then
  echo
  ws="$ASB_HOME/tools/playwright"
  if [ ! -d "$ws/node_modules/@playwright/test" ] || ! have node; then
    echo "FALLO    smoke test: falta el workspace de Playwright o Node"; MISSING=$((MISSING + 1))
  else
    tmp=$(mktemp -d)
    cat > "$tmp/smoke.js" <<'EOF'
const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route('**/*', (route) => route.abort());
    await page.setContent('<h1 id="t">ok</h1>');
    const text = await page.textContent('#t');
    if (text !== 'ok') throw new Error('contenido inesperado: ' + text);
    console.log('ok       smoke test de Chromium');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FALLO    smoke test: ' + e.message); process.exit(1); });
EOF
    if ! ( cd "$HOME" && NODE_PATH="$ws/node_modules" node "$tmp/smoke.js" ); then MISSING=$((MISSING + 1)); fi
    rm -rf -- "$tmp"
  fi
fi

echo
if [ "$MISSING" -gt 0 ]; then echo "doctor: $MISSING comprobación(es) fallida(s)"; exit 1; fi
echo "doctor: todo correcto (no se comprobó ninguna sesión autenticada)"
