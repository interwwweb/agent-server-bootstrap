#!/usr/bin/env bash
# Comprueba que los comandos de cada módulo existen. No hace login ni modifica nada.
# La existencia (check) y la versión (--versions) son comprobaciones distintas.
set -euo pipefail
set -f # sin expansión de globs al procesar la lista de módulos

PROG="agent-server-bootstrap"
ASB_HOME="$HOME/.local/share/$PROG"
DEFAULT_MODULES="base node python agents cloud remote playwright"
KNOWN_MODULES="$DEFAULT_MODULES docker"
NODE_MAJOR=24
MODULES="" MODULES_SET=0 SMOKE=0 VERSIONS=0 WITH_PI=0 MISSING=0

usage() {
  cat <<'EOF'
Uso: ./doctor.sh [opciones]

  --modules LISTA   Módulos a comprobar (no puede ir vacía; por defecto los mismos
                    que install.sh, sin docker).
                    Disponibles: base node python agents cloud remote playwright docker
  --with-pi         Comprueba también el comando pi; requiere el módulo agents.
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
if selected agents; then check codex; check claude; check herdr; if [ "$WITH_PI" = 1 ]; then check pi; fi; fi
selected cloud && for c in vercel sanity supabase; do check "$c"; done
selected remote && { check moshi-hook; check mosh; }
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
  for c in git node npm pnpm python3 uv jq rg tmux mosh gh codex claude herdr pi vercel sanity supabase playwright docker; do
    if have "$c"; then
      rc=0
      out=$("$c" --version 2>&1) || rc=$?
      if [ "$rc" -eq 0 ]; then
        printf '%-12s %s\n' "$c" "${out%%$'\n'*}"
      else
        printf 'FALLO    %-12s existe pero "--version" terminó con código %s: %s\n' "$c" "$rc" "${out%%$'\n'*}"
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
