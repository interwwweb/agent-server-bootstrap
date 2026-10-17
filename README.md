# agent-server-bootstrap

Instalador en bash para preparar un servidor Ubuntu con las herramientas habituales para trabajar con agentes de código (Codex, Claude Code, Playwright, CLIs de nube y acceso remoto).

> **Estado: sin probar en un VPS real.** Ver [Qué está probado y qué no](#qué-está-probado-y-qué-no). Este repositorio no ha tocado ningún servidor.

Licencia: Pendiente.

## Requisitos previos

- Ubuntu **22.04 o 24.04**, **amd64 o arm64**.
- Una cuenta **no root con `sudo`** ya creada (el script se niega a ejecutarse como root). Crearla y asegurar SSH es tu tarea previa; este proyecto **no** toca usuarios, SSH ni firewall.
- Git instalado para clonar este repositorio (si falta en la imagen del VPS, instalarlo antes).
- Acceso a internet solo para `--apply` (el dry-run no usa red).

## Clonar de forma segura

```bash
git clone https://github.com/interwwweb/agent-server-bootstrap.git
cd agent-server-bootstrap
less install.sh doctor.sh        # léelos antes de ejecutar nada
./install.sh --help
./install.sh                     # dry-run: solo muestra el plan, no escribe ni usa la red
```

Evita `curl ... | bash` sobre este repositorio: clona, lee y ejecuta.

## Uso

```bash
# 1. Plan (por defecto, no cambia nada)
./install.sh

# 2. Aplicar: exige --apply y --yes; python/agents/remote exigen además --vendor-installers
./install.sh --apply --yes --vendor-installers

# Seleccionar módulos (sin scripts de terceros no hace falta --vendor-installers)
./install.sh --modules base,node,playwright --apply --yes
./install.sh --with-docker --apply --yes --vendor-installers

# Opcional: Pi (solo con --with-pi; requiere agents)
./install.sh --with-pi --apply --yes --vendor-installers

# 3. Comprobar
./doctor.sh                      # falla (código 1) si falta algún comando
./doctor.sh --smoke              # lanza Chromium y renderiza HTML local, sin web externa
./doctor.sh --versions           # informe de versiones
```

Los argumentos desconocidos se rechazan antes de cualquier cambio. `--help` funciona en cualquier sistema.

## Módulos

| Módulo | Por defecto | Qué instala |
| --- | --- | --- |
| `base` | sí | apt: git curl wget ca-certificates jq ripgrep fd-find fzf unzip zip build-essential pkg-config python3 python3-venv python3-pip tmux mosh gh. Enlace `~/.local/bin/fd` → `fdfind` si no existe. |
| `node` | sí | Node v24 (última de la rama) desde el tarball oficial de nodejs.org, verificado con SHASUMS256, en `~/.local/share/agent-server-bootstrap/node`. Incluye npm y, tras Node, instala `pnpm` con `npm install -g` en el prefijo de usuario (se omite si ya existe). Archivo de entorno + bloque guardado en `~/.profile`. Si ya hay Node ≥ 24 **con npm**, no se descarga; si `current` ya apunta a otro Node, se aborta sin tocar nada. |
| `python` | sí | `uv` con su instalador (script de terceros, requiere `--vendor-installers`; sin que modifique el PATH). |
| `agents` | sí | Codex (`@openai/codex`, npm de usuario), Claude Code (instalador oficial, canal `stable`), Herdr (script de terceros). Pi solo con `--with-pi`. |
| `cloud` | sí | `vercel` y `@sanity/cli` (npm de usuario); `supabase` en un workspace propio con wrapper (no se admite `npm -g`). |
| `remote` | sí | moshi-hook (script de terceros). `mosh` llega con `base`. |
| `playwright` | sí | `@playwright/test` y `@playwright/cli` en un workspace dedicado, wrappers `playwright` y `playwright-cli`, y Chromium. No escribe nada en el proyecto desde el que se invoca. |
| `docker` | no | apt: `docker.io` y `docker-compose-v2`. No cambia grupos. `sudo docker` equivale a root. |

Detalles de diseño:

- **Entorno persistente**: con cualquier módulo que instale CLIs de usuario (`node`, `python`, `agents`, `cloud`, `remote`, `playwright`) se crea una vez el archivo de entorno y el bloque en `~/.profile`, antes de los módulos. `base` y `docker` solos no lo tocan.
- **Dependencias antes de cambiar nada**: con `--apply`, `agents`, `cloud` y `playwright` exigen Node ≥ 24 y npm; si no incluyes `node` y no están, el script aborta antes de instalar nada.
- **Node/npm**: prefijo de npm en `~/.local` (`NPM_CONFIG_PREFIX`); nunca `sudo npm`. Se aborta si el prefijo global no está dentro de `$HOME`.
- **Nunca sobrescribe** (garantía de los scripts de este repositorio): si un comando ya existe en el PATH se omite; wrappers, archivo de entorno y enlaces solo se crean si no existen; `~/.profile` solo recibe un bloque añadido una vez. Los instaladores de terceros (uv, Claude Code, Herdr, moshi-hook) siguen su propia política y pueden actualizar o modificar archivos por su cuenta.
- **Supabase**: se instala en `~/.local/share/agent-server-bootstrap/tools/supabase` y el wrapper `~/.local/bin/supabase` ejecuta el binario por ruta absoluta (no se descarga «latest» en cada invocación).
- **Playwright**: `install --with-deps chromium` se ejecuta en dos pasos equivalentes: `sudo … install-deps chromium` (apt) y `install chromium` como usuario, para que el navegador quede en tu HOME y no en el de root. Solo ocurre con `--apply`.
- **Scripts de terceros** (Claude, uv, Herdr, moshi-hook): se descargan a un archivo temporal y se ejecutan (no `curl | sh`). Todos exigen `--vendor-installers` con `--apply`: uv (`python`), Claude Code y Herdr (`agents`) y moshi-hook (`remote`). Herdr y moshi-hook no están auditados: ver [SECURITY.md](SECURITY.md).
- **Pi** (`--with-pi`, opcional): `@earendil-works/pi-coding-agent@0.87.1` con `--ignore-scripts`, **fijado** (excepción a «latest») por compatibilidad con la extensión. El 17/10/2026 se comprobó que `badlogic/pi-mono` redirige a `earendil-works/pi`, cuyo README indica ese paquete npm y Node ≥ 22.19. Se asume que es el Pi que quieres usar; esa decisión es tuya.
  - Solo se instala si `pi` falta. Si ya existe, debe ser estable `0.87.x` con x ≥ 1 (compatible: `>=0.87.1 <0.88.0`); si no, `--apply` aborta en la comprobación previa, antes de cambiar nada, y nunca baja ni reemplaza Pi. Con `--with-pi` hace falta `git` (si no incluyes `base`).
  - **Extensión [pi-selection-editor](https://github.com/interwwweb/pi-selection-editor)** `v0.1.2`, commit fijado `93d60682e2aeca492d05c19ca3dbc3b46f360241`: se clona (`--branch v0.1.2 --depth 1`) en un directorio temporal junto a `~/.local/share/agent-server-bootstrap/extensions/pi-selection-editor`, se verifica `git rev-parse HEAD` y solo entonces se renombra (si el destino no existe). Si el destino ya existe, debe tener `origin` exacto, ese commit y worktree limpio (también sin archivos sin seguimiento); si no, falla y no lo toca.
  - Después ejecuta con `bash` el `scripts/install.sh` de la extensión (tras verificarla; lo cubre `--vendor-installers` del módulo `agents`). Ese instalador upstream rechaza Pi 0.87.0 o no 0.87.x, crea el enlace `~/.local/share/pi-selection-editor` (o `$PI_SELECTION_EDITOR_DIR`) y ejecuta `pi install`; respeta `PI_CODING_AGENT_DIR`. Se ejecuta en cada `--apply`, aunque Pi ya exista (es idempotente según upstream; no verificado en un equipo real). Este repositorio no edita JSON de Pi.
  - Ciclo de vida: tras instalar, ejecuta `/reload` en las sesiones de Pi abiertas y comprueba a mano `/selection-editor status`; `doctor.sh` no verifica el editor en ejecución. Si lanzas Pi con `--no-extensions`, hay que pasar la ruta explícitamente con `--extension`; el script no reescribe lanzadores.
  - El mapeo de teclas de Ghostty en Mac es manual y no se cambia aquí.
- **`gh`** y `docker-compose-v2` vienen de apt: la versión puede ser antigua (p. ej. `gh` 2.4 en 22.04). Para la última, usa el repositorio de GitHub CLI por tu cuenta.

## Después de instalar: logins manuales

El script no hace login ni guarda tokens. Abre una sesión nueva (o `. ~/.profile`) y, según necesites:

```bash
gh auth login
vercel login
supabase login
sanity login
codex login
claude          # sigue el flujo de inicio de sesión
pi              # solo con --with-pi: escribe /login
```

## Acceso remoto desde el móvil (opcional)

- Instalar el cliente Moshi en el teléfono es manual y opcional; el módulo `remote` solo prepara los hooks en el servidor (moshi-hook) y `mosh`.
- **SSH vs Mosh**: Mosh abre su sesión por SSH y luego usa UDP (por defecto 60000–61000). Este proyecto **no abre esos puertos UDP ni toca el firewall**: si usas Mosh, ábrelos tú con el criterio de tu proveedor.
- Configurar los hooks de moshi-hook (emparejamiento con la app) es manual.

## Qué está probado y qué no

Probado (en local, con comandos simulados; ver `tests/`):

- Parseo de argumentos, rechazo de desconocidos y de combinaciones inválidas.
- Dry-run sin escrituras en HOME y sin invocar `curl`, `wget`, `sudo`, `apt-get`, `npm` ni `git`.
- Rechazo de sistemas que no sean Ubuntu 22.04/24.04, de arquitecturas no admitidas y de root.
- Bloque de `~/.profile` idempotente; no sobrescribir el archivo de entorno ni binarios/wrappers existentes.
- Funciones del instalador cargadas con `source` y comandos simulados: rechazo de Node < 24 o sin npm (también sin el módulo `node`), workspaces npm y wrappers idempotentes, `apt-get update` antes de instalar Docker, rechazo de `--apply` sin `--vendor-installers` para `python`/`agents`/`remote`, y fallo temprano si `current` apunta a otro Node.
- `doctor.sh`: sin expansión de globs, `--modules` vacío rechazado, `--with-pi` exige `agents` (y comprueba versión de Pi, clon y commit de la extensión y enlace estable), y `--versions` informa como fallo un ejecutable cuyo `--version` falla.
- Pi y extensión (con `git`, `pi`, `npm` y `bash` simulados): orden Pi → clon → instalador upstream, Pi incompatible aborta sin instalar, clon existente verificado se reutiliza, origin/commit/sucio/symlink impiden el instalador, clon fallido sin directorio roto, `PI_CODING_AGENT_DIR` heredado y settings intactos. La instalación real de Pi y su extensión se verifica por separado en el job de integración de CI.

**No probado**: ninguna instalación real (`--apply`), ni en Ubuntu 22.04/24.04, ni en amd64/arm64, ni en un VPS. Tampoco `doctor.sh --smoke`, la descarga de Node/uv/Claude/Herdr/moshi-hook, la compatibilidad de los paquetes npm en cada arquitectura ni que Chromium arranque (p. ej. con las restricciones de usuario sin privilegios de Ubuntu 24.04). El CI tiene dos trabajos en Ubuntu 24.04 y 22.04: lint y tests con comandos simulados (`bash -n`, ShellCheck, unittest), y una **integración real solo de Pi** (`tests/pi-integration.sh`). Esta última usa red, npm y git reales en un runner efímero con `HOME` temporal propio y `PI_CODING_AGENT_DIR=$HOME/custom-pi-agent`: carga `install.sh` y ejecuta solo `pi_install` y `configure_pi` (Pi 0.87.1, clon fijado, enlace estable, registro en los settings sin duplicados en una segunda pasada y `npm test` de la extensión). **No es** el bootstrap completo de Ubuntu: no ejecuta `main`, `base`, sudo, otros instaladores, ni logins, y sigue sin probarse un VPS completo, Chromium ni el terminal interactivo. Hasta que ese CI pase, no hay prueba de que funcione.

> Verificación local del 17/10/2026 (macOS): sintaxis Bash y ShellCheck correctos; **65 pruebas con comandos simulados aprobadas**. La integración real de Pi se ejecuta aparte en CI; esto no acredita el bootstrap completo de un VPS. Para repetir:
> `bash -n install.sh doctor.sh && shellcheck install.sh doctor.sh && python3 -I -m unittest discover -s tests -v`.

## Versiones y reproducibilidad

Las dependencias se instalan en «latest» salvo Pi y su extensión, fijados con `--with-pi` (Pi 0.87.1, pi-selection-editor v0.1.2 en un commit concreto). Node v24 más reciente, paquetes npm sin fijar, instaladores de terceros en su estado actual). **No se garantiza reproducibilidad.** Para dejar constancia de lo que se instaló:

```bash
./doctor.sh --versions > informe-versiones-$(date +%F).txt
```

Guarda ese informe fuera del repositorio si contiene datos de tu equipo.

## Fuentes de documentación

Comprobadas en los sitios oficiales el 17/10/2026 (por quien coordina el proyecto, no desde este repositorio): Herdr y moshi-hook (getmoshi/herdr), Claude Code, Codex CLI, Supabase CLI, Vercel CLI, Sanity CLI, Playwright CLI y Pi. Los enlaces de las demás entradas no se han verificado: comprueba que siguen vigentes.

- Node.js: <https://nodejs.org/en/download> · <https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt>
- uv: <https://docs.astral.sh/uv/getting-started/installation/>
- Claude Code (verificado): <https://code.claude.com/docs/en/setup> · instalador: <https://claude.ai/install.sh>
- Codex CLI (verificado): <https://learn.chatgpt.com/docs/codex/cli>
- Pi (verificado; `badlogic/pi-mono` redirige aquí): <https://github.com/earendil-works/pi>
- Herdr (verificado): <https://herdr.dev/>
- Moshi (verificado): <https://getmoshi.app/>
- Mosh: <https://mosh.org/>
- Vercel CLI (verificado): <https://vercel.com/docs/cli>
- Sanity CLI (verificado): <https://www.sanity.io/docs/apis-and-sdks/cli>
- Supabase CLI (verificado; guía de CLI): <https://supabase.com/docs/guides/local-development/cli/getting-started>
- Playwright (verificado): <https://playwright.dev/docs/browsers> · <https://playwright.dev/docs/intro> · <https://playwright.dev/agent-cli/installation>
- GitHub CLI: <https://cli.github.com/>
- Docker en Ubuntu: <https://docs.docker.com/engine/install/ubuntu/>

## Estructura

```
install.sh          instalador (dry-run por defecto)
doctor.sh           comprobación de comandos, versiones y smoke test
tests/              tests unittest con comandos simulados
.github/workflows/  CI de solo lectura (lint, tests simulados e integración real de Pi)
SECURITY.md         cadena de suministro y permisos de agentes
```
