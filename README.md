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
- **Pi** (`--with-pi`, opcional): `@earendil-works/pi-coding-agent` con `--ignore-scripts`. El 17/10/2026 se comprobó que `badlogic/pi-mono` redirige a `earendil-works/pi`, cuyo README indica ese paquete npm y Node ≥ 22.19. Se asume que es el Pi que quieres usar; esa decisión es tuya.
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
- `doctor.sh`: sin expansión de globs, `--modules` vacío rechazado, `--with-pi` exige `agents`, y `--versions` informa como fallo un ejecutable cuyo `--version` falla.

**No probado**: ninguna instalación real (`--apply`), ni en Ubuntu 22.04/24.04, ni en amd64/arm64, ni en un VPS. Tampoco `doctor.sh --smoke`, la descarga de Node/uv/Claude/Herdr/moshi-hook, la compatibilidad de los paquetes npm en cada arquitectura ni que Chromium arranque (p. ej. con las restricciones de usuario sin privilegios de Ubuntu 24.04). El CI no instala nada: solo `bash -n`, ShellCheck y los tests, en Ubuntu 24.04 y 22.04.

> Verificación local del 17/10/2026 (macOS): sintaxis Bash y ShellCheck correctos; **49 tests con comandos simulados aprobados**. Esto no acredita una instalación real en Ubuntu. Para repetir:
> `bash -n install.sh doctor.sh && shellcheck install.sh doctor.sh && python3 -I -m unittest discover -s tests -v`.

## Versiones y reproducibilidad

Todas las dependencias se instalan en «latest» (Node v24 más reciente, paquetes npm sin fijar, instaladores de terceros en su estado actual). **No se garantiza reproducibilidad.** Para dejar constancia de lo que se instaló:

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
.github/workflows/  CI de solo lectura (lint y tests, sin instalar)
SECURITY.md         cadena de suministro y permisos de agentes
```
