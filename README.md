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
| `cloud` | sí | `vercel` y `@sanity/cli` (npm de usuario); `supabase`, `wrangler` (CLI de Cloudflare Workers, no `cloudflared`) y `linear` (CLI **comunitaria** `@schpet/linear-cli@3.0.0`, fijada) cada uno en un workspace propio con wrapper (no se admite `npm -g` para estos). |
| `remote` | sí | moshi-hook (script de terceros). `mosh` llega con `base`. |
| `tailscale` | sí | Paquete `tailscale` del repositorio apt oficial firmado `https://pkgs.tailscale.com/stable/ubuntu` (jammy en 22.04, noble en 24.04), sin script de terceros: no exige `--vendor-installers`. Ver «Tailscale» abajo. |
| `playwright` | sí | `@playwright/test@1.64.1` y `@playwright/cli@0.1.22` en un workspace dedicado (`--save-exact`), wrappers `playwright` y `playwright-cli`, dependencias de sistema de Chromium con `apt-get` (lista fija, ver abajo) y Chromium como usuario. No escribe nada en el proyecto desde el que se invoca. |
| `docker` | no | apt: `docker.io` y `docker-compose-v2`. No cambia grupos. `sudo docker` equivale a root. |

Detalles de diseño:

- **Entorno persistente**: con cualquier módulo que instale CLIs de usuario (`node`, `python`, `agents`, `cloud`, `remote`, `playwright`) se crea una vez el archivo de entorno y el bloque en `~/.profile`, antes de los módulos. `base` y `docker` solos no lo tocan.
- **Dependencias antes de cambiar nada**: con `--apply`, `agents`, `cloud` y `playwright` exigen Node ≥ 24 y npm; si no incluyes `node` y no están, el script aborta antes de instalar nada.
- **Node/npm**: prefijo de npm en `~/.local` (`NPM_CONFIG_PREFIX`); nunca `sudo npm`. Se aborta si el prefijo global no está dentro de `$HOME`.
- **Qué no sobrescribe** (alcance concreto, no una garantía general): los wrappers de `~/.local/bin`, el archivo de entorno, los enlaces (`fd`, `current` de Node) y los archivos de apt de Tailscale solo se crean si no existen, y `~/.profile` recibe un bloque que se añade una sola vez. Un comando ya presente en el PATH se omite en los pasos `npm_global` y `download_run`. **No** es una garantía sobre lo que hacen los gestores de paquetes (apt, npm, Playwright) ni los instaladores de terceros (uv, Claude Code, Herdr, moshi-hook), que siguen su propia política y pueden actualizar dependencias o modificar archivos. Detalle en «Qué pasa si ya hay herramientas».
- **Linear CLI** (`cloud`): es la CLI **comunitaria** [schpet/linear-cli](https://github.com/schpet/linear-cli), **no es oficial de Linear**. Se instala `@schpet/linear-cli@3.0.0` con `--save-exact` en `~/.local/share/agent-server-bootstrap/tools/linear` (versión exacta, como el resto de paquetes npm directos): el paquete expone el binario `linear` mediante `run-linear.js` y su **postinstall descarga un binario nativo** (de GitHub); no hace falta Deno. Si ya existe `linear` en el PATH se omite sin validar su versión ni procedencia; el ejecutable del workspace se reutiliza y el wrapper `~/.local/bin/linear` no se sobrescribe. No usa sudo ni `npm -g`, y **nunca** ejecuta `linear auth`, `whoami` ni consultas de cuenta, equipo, proyecto o tareas. La autenticación es manual (`linear auth login`, que solo se imprime) y conviene hacerla **solo con un almacén seguro disponible**: un llavero de Linux exige Secret Service desbloqueado y D-Bus (en un servidor sin escritorio `libsecret-tools` no basta). Mira [docs/secretos.md](docs/secretos.md) (guía orientativa; no activa ningún almacén de secretos). `.gitignore` cubre `.linear.toml`, `.linear/`, `.config/linear/` y `.config/linear-cli/`, pero ignorar archivos **no basta** si ya están seguidos por Git.
- **Wrangler** (`cloud`): si ya existe `wrangler` en el PATH, se omite. Si no, se instala en `~/.local/share/agent-server-bootstrap/tools/wrangler` (reutilizando el ejecutable si ya está) y el wrapper `~/.local/bin/wrangler` no se sobrescribe. Los scripts de npm se ejecutan con normalidad (Wrangler necesita `workerd`). Cloudflare recomienda instalarlo **local por proyecto** (`npm i -D wrangler@latest`): este wrapper es solo una base para la máquina y cada proyecto debería fijar su Wrangler local para ser reproducible. No se toca ningún proyecto, ni se hace login, ni se consulta cuenta, ni se despliega nada ni se tocan DNS o túneles.
- **Supabase**: se instala en `~/.local/share/agent-server-bootstrap/tools/supabase` y el wrapper `~/.local/bin/supabase` ejecuta el binario por ruta absoluta (no se descarga «latest» en cada invocación).
- **Playwright**: ya **no** se ejecuta `playwright install-deps` con sudo (era código de npm con privilegios). `sudo` solo ejecuta `apt-get` con un `PATH` fijo (`/usr/sbin:/usr/bin:/sbin:/bin`) y una lista de paquetes escrita en `install.sh` por versión de Ubuntu (`PW_APT_JAMMY` para 22.04, `PW_APT_NOBLE` para 24.04), copiada de las entradas «tools» + «chromium» de `nativeDeps.ts` en el tag v1.64.1 de Playwright (arm64 usa las mismas que x64); se instala con `--no-install-recommends`. Después se ejecuta como usuario `node_modules/@playwright/test/cli.js install chromium` (la entrada estable de `@playwright/test`, que resuelve su propio `playwright` fijado), para que el navegador quede en tu HOME. **No** se usa `node_modules/.bin/playwright`: `@playwright/cli` trae un `playwright` alfa distinto y npm puede elevarlo a la raíz, así que ese `.bin` es ambiguo. El wrapper `playwright` apunta a esa entrada estable y `playwright-cli` sigue apuntando a su `.bin`; un wrapper `playwright` de una ejecución anterior **no se sobrescribe** (se avisa si no apunta a la entrada estable: revísalo a mano) y un workspace existente sin la entrada estable se completa con los pines pedidos, sin borrarlo. **Al subir `PLAYWRIGHT_TEST_VERSION` hay que volver a copiar esas listas a mano.** Solo ocurre con `--apply`.
- **Tailscale** (módulo propio, separado de `remote`; `--modules tailscale` funciona solo): se descarga únicamente la clave `https://pkgs.tailscale.com/stable/ubuntu/<codename>.noarmor.gpg` a un archivo temporal (no vacío) y se genera localmente una lista con una sola línea `deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/ubuntu <codename> main`. El codename sale de la versión de Ubuntu admitida, no de datos del usuario. Con `sudo install -m0644` se crean `/usr/share/keyrings/tailscale-archive-keyring.gpg` y `/etc/apt/sources.list.d/tailscale.list` (directorios 0755) **solo si no existen**; luego `apt-get update` y `apt-get install -y tailscale`. Sin `apt-key`.
  - Si `tailscale` y `tailscaled` ya existen, se omite el módulo sin tocar nada (ni red ni sudo). Si solo existe uno, falla sin reemplazar nada. Si alguno de los dos archivos de apt existe y es distinto o es un symlink, aborta antes de escribir ninguno y los conserva. Con `base` omitido hacen falta `curl` y `ca-certificates` ya instalados.
  - **Estado previo**: antes de instalar un Tailscale ausente, el script se niega a continuar si existe (archivo, directorio o symlink, incluso roto) `/var/lib/tailscale`, `/etc/default/tailscaled`, `/etc/systemd/system/tailscaled.service` o `/etc/systemd/system/tailscaled.service.d`, porque al instalar el paquete el servicio podría arrancar y reconectar credenciales antiguas aunque no se ejecute `tailscale up`. No lee, imprime ni borra su contenido: revísalo o retíralo tú y vuelve a ejecutar. Una instalación completa ya existente se omite sin tocarla, haya o no estado.
  - **Efectos del paquete**: su script de postinstalación puede arrancar y habilitar el servicio `tailscaled`; este instalador no lo arranca, para ni habilita explícitamente. No se ejecuta `tailscale up/login/set/logout`, ni se usan claves de autenticación, ni se tocan SSH, ACL, DNS, rutas, exit nodes, serve o funnel. Unir el servidor a una tailnet es un paso **manual y aparte** (`sudo tailscale up`, que el script solo imprime) y necesita la aprobación del dueño de la tailnet.
  - La confianza en la clave se apoya en HTTPS contra `pkgs.tailscale.com`; no hay huella ni firma independiente fijada. `doctor.sh` solo comprueba que existen `tailscale` y `tailscaled` y la versión (`tailscale version`); no consulta estado, IP, red ni autenticación.
- **Scripts de terceros** (Claude, uv, Herdr, moshi-hook): se descargan a un archivo temporal por HTTPS (también en redirecciones) y **solo se ejecutan si su SHA-256 coincide con el fijado en `install.sh`** (no `curl | sh`); si no coincide, falla cerrado antes de ejecutar y no hay opción para saltarse la verificación. Los hashes se obtuvieron el 18/10/2026 sobre el contenido final tras las redirecciones: fijan **qué script** se ejecuta, pero no auditan su interior ni lo que descargan después. `uv` y Claude Code se obtienen de URL «latest», así que su hash cambiará con cada versión nueva y habrá que revisarlo y actualizarlo. Todos exigen `--vendor-installers` con `--apply`: uv (`python`), Claude Code y Herdr (`agents`) y moshi-hook (`remote`). Herdr y moshi-hook no están auditados: ver [SECURITY.md](SECURITY.md).
- **Pi** (`--with-pi`, opcional): `@earendil-works/pi-coding-agent@0.87.1` con `--ignore-scripts`, **fijado**, como todos los paquetes npm directos; la versión concreta es la que exige la compatibilidad con la extensión. El 17/10/2026 se comprobó que `badlogic/pi-mono` redirige a `earendil-works/pi`, cuyo README indica ese paquete npm y Node ≥ 22.19. Se asume que es el Pi que quieres usar; esa decisión es tuya.
  - Solo se instala si `pi` falta. Si ya existe, debe ser estable `0.87.x` con x ≥ 1 (compatible: `>=0.87.1 <0.88.0`); si no, `--apply` aborta en la comprobación previa, antes de cambiar nada, y nunca baja ni reemplaza Pi. Con `--with-pi` hace falta `git` (si no incluyes `base`).
  - **Extensión [pi-selection-editor](https://github.com/interwwweb/pi-selection-editor)** `v0.1.2`, commit fijado `93d60682e2aeca492d05c19ca3dbc3b46f360241`: se clona (`--branch v0.1.2 --depth 1`) en un directorio temporal junto a `~/.local/share/agent-server-bootstrap/extensions/pi-selection-editor`, se verifica `git rev-parse HEAD` y solo entonces se renombra (si el destino no existe). Si el destino ya existe, debe tener `origin` exacto, ese commit y worktree limpio (también sin archivos sin seguimiento); si no, falla y no lo toca.
  - Después ejecuta con `bash` el `scripts/install.sh` de la extensión (tras verificarla; lo cubre `--vendor-installers` del módulo `agents`). Ese instalador upstream rechaza Pi 0.87.0 o no 0.87.x, crea el enlace `~/.local/share/pi-selection-editor` (o `$PI_SELECTION_EDITOR_DIR`) y ejecuta `pi install`; respeta `PI_CODING_AGENT_DIR`. Se ejecuta en cada `--apply`, aunque Pi ya exista (es idempotente según upstream; no verificado en un equipo real). Este repositorio no edita JSON de Pi.
  - Ciclo de vida: tras instalar, ejecuta `/reload` en las sesiones de Pi abiertas y comprueba a mano `/selection-editor status`; `doctor.sh` no verifica el editor en ejecución. Si lanzas Pi con `--no-extensions`, hay que pasar la ruta explícitamente con `--extension`; el script no reescribe lanzadores.
  - El mapeo de teclas de Ghostty en Mac es manual y no se cambia aquí.
- **`gh`** y `docker-compose-v2` vienen de apt: la versión puede ser antigua (p. ej. `gh` 2.4 en 22.04). Para la última, usa el repositorio de GitHub CLI por tu cuenta.

## Qué pasa si ya hay herramientas

Resumen basado en el código actual (no se cambia ninguna política; solo se explica). Siempre conviene mirar primero el dry-run (`./install.sh`), que no escribe nada ni usa la red.

- **Comandos npm y scripts de terceros** (`npm_global`, `download_run`): si el comando ya está en el PATH (`command -v`), se omite. Solo se comprueba que existe: no se valida de qué paquete viene ni si su versión es compatible.
- **Node**: con Node ≥ 24 **y** npm, se reutiliza y no se descarga. Si hay un Node más antiguo, se instala el v24 en `~/.local/share/agent-server-bootstrap/node` sin borrar el antiguo, pero el PATH da prioridad al nuevo. Si `current` ya existe y apunta a otro Node incompatible, se aborta. Después `pnpm` se instala con `npm install -g` si falta.
- **apt** (`base`, `docker`): `apt-get install -y` puede actualizar paquetes ya instalados; no hay una omisión general.
- **Workspaces de `cloud`** (supabase, wrangler) y de `playwright`: se reutiliza el ejecutable si existe y los wrappers solo se crean si faltan; pero si el workspace hay que instalarlo, `npm install` puede actualizar sus dependencias. `playwright` además repite el `apt-get install` de sus dependencias de sistema y `install chromium` en cada `--apply`, y apt puede cambiar paquetes aunque las herramientas ya estén.
- **Pi** (`--with-pi`): se acepta un Pi estable `>=0.87.1 <0.88.0`; si no, el preflight aborta sin cambiar nada. De la extensión se comprueban origin fijo, commit fijo y worktree limpio, y se vuelve a ejecutar el registro upstream.
- **Tailscale**: con `tailscale` y `tailscaled` ya instalados se omite; una instalación parcial, o estado/configuración previos, abortan.
- **Entorno y perfil**: no se sobrescriben los archivos existentes, pero se añade un bloque a `~/.profile` que carga el entorno (PATH y prefijo de npm en `~/.local`).
- **Errores**: parar ante un error **no** es una transacción ni hay rollback: los módulos anteriores pueden haber cambiado cosas.
- **Comprobaciones**: `./doctor.sh` y `./doctor.sh --versions` son de lectura, pero ejecutan los comandos instalados (`--version`/`version`) y no se puede garantizar que ninguno tenga efectos propios (comprobar actualizaciones, caché, etc.).

## Después de instalar: logins manuales

El script no hace login ni guarda tokens. Abre una sesión nueva (o `. ~/.profile`) y, según necesites:

```bash
gh auth login
vercel login
supabase login
sanity login
wrangler login    # opcional: Cloudflare; no se ejecuta aquí
linear auth login # opcional: Linear (comunitaria); solo con almacén seguro, sin pasar claves por línea de comandos
codex login
claude          # sigue el flujo de inicio de sesión
pi              # solo con --with-pi: escribe /login
```

## Acceso remoto desde el móvil (opcional)

- Instalar el cliente Moshi en el teléfono es manual y opcional; el módulo `remote` solo prepara los hooks en el servidor (moshi-hook) y `mosh`.
- **SSH vs Mosh**: Mosh abre su sesión por SSH y luego usa UDP (por defecto 60000–61000). Este proyecto **no abre esos puertos UDP ni toca el firewall**: si usas Mosh, ábrelos tú con el criterio de tu proveedor.
- Configurar los hooks de moshi-hook (emparejamiento con la app) es manual.

## Navegador para los agentes

El módulo `playwright` instala **Chromium administrado por Playwright**. No instala Google Chrome ni Brave. Chromium es el predeterminado recomendado para este bootstrap; Chrome se puede evaluar si una prueba o integración lo exige explícitamente. No se añade automáticamente ni se sustituye ningún navegador existente por esta recomendación.

[Referencia oficial de Playwright sobre navegadores](https://playwright.dev/docs/browsers).

## Qué está probado y qué no

Probado (en local, con comandos simulados; ver `tests/`):

- Parseo de argumentos, rechazo de desconocidos y de combinaciones inválidas.
- Dry-run sin escrituras en HOME y sin invocar `curl`, `wget`, `sudo`, `apt-get`, `npm` ni `git`.
- Rechazo de sistemas que no sean Ubuntu 22.04/24.04, de arquitecturas no admitidas y de root.
- Bloque de `~/.profile` idempotente; no sobrescribir el archivo de entorno ni binarios/wrappers existentes.
- Tailscale con `curl`, `sudo` y `apt-get` simulados y rutas temporales: módulo por defecto, solo-tailscale en dry-run sin escrituras ni red ni `--vendor-installers`, codename jammy/noble, omisión del par existente antes de red o sudo, instalación parcial rechazada, orden clave → lista → apt, conflictos y symlinks sin escribir nada, estado previo (archivo, directorio o symlink roto) que impide red, sudo y apt y se conserva intacto, omisión del par completo aunque haya estado, descarga vacía y comprobaciones previas. Nunca se invocan `tailscale up/login/status`.
- Wrangler con `npm` simulado (sin red): instalación en workspace dedicado con wrapper, omisión si ya existe el comando, reutilización del ejecutable sin sobrescribir el wrapper, exigencia de Node ≥ 24, plan de dry-run sin ejecutar, y `doctor` (falta, versión sin login). La instalación real de Wrangler **no** está probada y no tiene job de CI propio.
- Linear CLI con `npm` simulado (sin red): paquete fijado `@schpet/linear-cli@3.0.0` con `--save-exact` en un workspace dedicado y wrapper, omisión si ya existe el comando, reutilización del ejecutable sin sobrescribir el wrapper, Node ≥ 24, ni Deno ni `-g` ni sudo, plan de dry-run sin ejecutar, `doctor` (falta, versión) y ninguna invocación de la CLI desde `install.sh`.
- `tests/linear-integration.sh` (opt-in con `ASB_LINEAR_INTEGRATION=1`, en un `HOME` temporal y con Node 24) instala de verdad solo `mod_linear` (usa red: npm y el binario nativo de GitHub) y comprueba versión, `package-lock.json`, segunda pasada sin cambios y que no se crea ninguna credencial; su job de CI (Ubuntu 22.04 y 24.04, sin tokens) tiene una ejecución verificada por quien coordina el proyecto: [run 39046146479](https://github.com/interwwweb/agent-server-bootstrap/actions/runs/39046146479).
- Endurecimiento de la cadena de suministro (con `curl`, `sudo` y `npm` simulados, sin red): un hash de script de terceros que no coincide falla cerrado y el intérprete no se ejecuta; solo las 4 URL tienen hash fijado y no hay opción para saltarlo; `fetch` usa `--proto =https` y `--proto-redir =https`; `sudo` del módulo `playwright` solo lanza `apt-get` con `PATH` fijo y las listas de 22.04/24.04 (sin `install-deps`, sin código de npm); las versiones npm directas están fijadas y usadas, los workspaces con `--save-exact`; las acciones de CI están fijadas a SHA completo, existe `dependabot.yml` semanal y el job de gitleaks usa el binario oficial con SHA-256 literal (sin acción de marketplace ni secretos).
- Funciones del instalador cargadas con `source` y comandos simulados: rechazo de Node < 24 o sin npm (también sin el módulo `node`), workspaces npm y wrappers idempotentes, `apt-get update` antes de instalar Docker, rechazo de `--apply` sin `--vendor-installers` para `python`/`agents`/`remote`, y fallo temprano si `current` apunta a otro Node.
- `doctor.sh`: sin expansión de globs, `--modules` vacío rechazado, `--with-pi` exige `agents` (y comprueba versión de Pi, clon y commit de la extensión y enlace estable), y `--versions` informa como fallo un ejecutable cuyo `--version` falla.
- Pi y extensión (con `git`, `pi`, `npm` y `bash` simulados): orden Pi → clon → instalador upstream, Pi incompatible aborta sin instalar, clon existente verificado se reutiliza, origin/commit/sucio/symlink impiden el instalador, clon fallido sin directorio roto, `PI_CODING_AGENT_DIR` heredado y settings intactos. La instalación real de Pi y su extensión se verifica por separado en el job de integración de CI.

**Integraciones reales de CI** (runners efímeros Ubuntu 22.04 y 24.04; resultados en [Actions](https://github.com/interwwweb/agent-server-bootstrap/actions)):

- Pi y su extensión: `tests/pi-integration.sh` instala Pi 0.87.1 y la extensión fijada en un HOME temporal, conserva ajustes previos, respeta `PI_CODING_AGENT_DIR`, ejecuta los tests oficiales y repite el registro sin duplicados. No usa sudo ni inicia sesión. La integración anterior fue [aprobada](https://github.com/interwwweb/agent-server-bootstrap/actions/runs/39043499464); sigue ejecutándose junto con las pruebas nuevas.
- Tailscale: `tests/tailscale-integration.sh` ejecuta realmente `install.sh --modules tailscale --apply --yes`, con sudo solo en el runner efímero, y comprueba clave, lista APT, paquete mediante `dpkg`, versiones y segunda ejecución sin cambios. Exige `ASB_EPHEMERAL_RUNNER=1`; no debe ejecutarse en un servidor real. No autentica el dispositivo ni consulta `tailscale status`.

- Linear CLI comunitaria: `tests/linear-integration.sh` (opt-in con `ASB_LINEAR_INTEGRATION=1`), ver arriba.
- Escaneo de secretos: un job `secrets` ejecuta `gitleaks` 8.30.1 (binario oficial, verificado con un SHA-256 literal) sobre todo el historial con `--redact`.
- Playwright: `tests/playwright-integration.sh` (opt-in con `ASB_EPHEMERAL_RUNNER=1`; solo Ubuntu 22.04/24.04 sin root, en un runner efímero) ejecuta `mod_playwright` de verdad con `HOME` y `PLAYWRIGHT_BROWSERS_PATH` temporales: npm con las versiones fijadas, la lista estática de `apt-get` con sudo y Chromium. Comprueba las versiones instaladas de `@playwright/test` y `@playwright/cli`, la versión del `playwright` que `@playwright/test` resuelve de verdad (con `createRequire`) frente a `PLAYWRIGHT_TEST_VERSION`, la entrada estable `@playwright/test/cli.js` y el wrapper `playwright` (no exige que el `playwright` de la raíz sea el estable: puede ser el alfa del CLI), y lanza Chromium sin cabeza con la API de `@playwright/test` para renderizar HTML local y comprobar que el título es `hello` (sin sitios externos ni autenticación). Una segunda pasada comprueba que no se repite `npm install` ni cambian `package.json`, el lockfile ni los wrappers; apt y la instalación del navegador **sí pueden repetirse** (es el comportamiento documentado). La primera ejecución real ([run 39075995944](https://github.com/interwwweb/agent-server-bootstrap/actions/runs/39075995944)) **falló** en ambas versiones de Ubuntu: «el paquete playwright de la raíz no es 1.64.1», porque `.bin/playwright` pertenecía al `playwright` alfa que trae `@playwright/cli` (un fallo real: se instalaba el Chromium del alfa). Se corrigió usando la entrada estable `@playwright/test/cli.js` (ver arriba) y se retiró esa aserción; **la corrección aún no se ha vuelto a ejecutar en CI** y no hay prueba de que funcione hasta que quien coordina el proyecto verifique una ejecución real. El navegador instalado es el que espera la API de `@playwright/test`; el runtime de navegador de `playwright-cli` (alfa) **no** se ha probado con un smoke test y puede necesitar su propio navegador.
- **Aún no hay** integración real para los hashes de los scripts de terceros (solo pruebas simuladas).

**Límites**: estas integraciones no prueban el bootstrap completo con todos los módulos, ningún VPS del usuario, arm64, `doctor.sh --smoke`, Chromium, ni el terminal interactivo Ghostty/Herdr. Tampoco verifican una conexión real a una tailnet ni las políticas de red. Los resultados específicos de cada ejecución están en Actions, no se deducen de las pruebas simuladas.

> Verificación local del 18/10/2026 (macOS): sintaxis Bash y ShellCheck correctos y 114 pruebas con comandos simulados aprobadas (incluido el script de Playwright, que solo se probó en su rechazo sin opt-in). Un `gitleaks` 8.30.1 (binario oficial verificado por SHA-256) ejecutado antes de añadir `tests/playwright-integration.sh` no encontró filtraciones en el historial ni en el árbol de trabajo. Esto no acredita una instalación real. Para repetir:
> `bash -n install.sh doctor.sh tests/*.sh && shellcheck install.sh doctor.sh tests/*.sh && python3 -I -m unittest discover -s tests -v`.

## Versiones y reproducibilidad

Los paquetes npm directos están fijados a una versión exacta en un único bloque de `install.sh` (el `latest` del registro el 18/10/2026): `pnpm` 12.14.0, `@openai/codex` 0.163.0, `vercel` 64.5.0, `@sanity/cli` 8.19.0, `supabase` 2.121.0, `wrangler` 4.151.1, `@playwright/test` 1.64.1, `@playwright/cli` 0.1.22, la Linear CLI comunitaria 3.0.0 y, con `--with-pi`, Pi 0.87.1 y pi-selection-editor v0.1.2 en un commit concreto. Los scripts de terceros se ejecutan solo con el SHA-256 fijado. **Eso no da reproducibilidad completa**: las dependencias transitivas de npm no están bloqueadas (no hay lockfile versionado), Node v24 es la última de su rama y apt instala lo que el repositorio ofrezca ese día. Para dejar constancia de lo que se instaló:

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
- Linear CLI comunitaria (verificado en npm y su README): <https://github.com/schpet/linear-cli> · autenticación: <https://github.com/schpet/linear-cli/blob/main/docs/authentication.md>
- Bitwarden Secrets Manager (solo referencia de [docs/secretos.md](docs/secretos.md); plan y permisos no verificados): <https://bitwarden.com/help/secrets-manager-cli/> · <https://bitwarden.com/help/machine-accounts/>
- Wrangler (Cloudflare Workers; verificado, recomienda instalación local por proyecto): <https://developers.cloudflare.com/workers/wrangler/install-and-update/>
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
.github/workflows/  CI con permisos de repositorio de solo lectura; lint, mocks e integraciones Pi/Tailscale
docs/secretos.md    guía orientativa sobre secretos (no instala ni activa nada)
SECURITY.md         cadena de suministro y permisos de agentes
```
