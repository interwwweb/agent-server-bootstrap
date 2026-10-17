# Seguridad

## Qué hace y qué no hace este repositorio

- `install.sh` es un dry-run por defecto. Con `--apply --yes` instala software en el servidor del usuario que lo ejecuta.
- **No** cambia SSH, firewall ni usuarios; **no** añade grupos (tampoco `docker`); **no** hace login ni guarda tokens; **no** usa `sudo npm`; **no** activa banderas de agentes que saltan permisos o confirmaciones.
- No se ha auditado ningún servidor real con este código (ver «Estado de las pruebas» en el [README](README.md)).

## Cadena de suministro y versiones

Todo se instala en su versión más reciente (`latest`) en el momento de ejecutar. Por eso:

- **No hay reproducibilidad**: dos ejecuciones en días distintos pueden dar versiones distintas. Guarda `./doctor.sh --versions` como informe de lo que quedó instalado.
- **Node.js**: tarball oficial de `nodejs.org`, verificado con SHA-256 contra `SHASUMS256.txt` descargado del mismo origen por HTTPS. No se verifica la firma GPG de `SHASUMS256.txt`: protege contra descargas corruptas, no contra un compromiso del propio origen.
- **Paquetes npm** (`@openai/codex`, `vercel`, `@sanity/cli`, `supabase`, `@playwright/*`, y `@earendil-works/pi-coding-agent` con `--with-pi`): se instalan sin fijar versión y ejecutan scripts de instalación de sus dependencias (salvo Pi, que usa `--ignore-scripts`). Un paquete o dependencia comprometidos se ejecutarían con tu usuario.
- **Scripts de terceros**: `uv` (`astral.sh`), Claude Code (`claude.ai/install.sh`), Herdr (`herdr.dev/install.sh`) y moshi-hook (`getmoshi.app/install.sh`). Se descargan a un archivo temporal y se ejecutan; **no se muestra su contenido ni se verifica integridad**. Los scripts de Herdr y de moshi-hook **no han sido auditados** por este proyecto. Todos ellos (módulos `python`, `agents` y `remote`) exigen `--vendor-installers` en `--apply`. Léelos antes de aceptarlos.
- **Pi** (opcional, `--with-pi`): el 17/10/2026 se comprobó que `badlogic/pi-mono` redirige a `earendil-works/pi`, cuyo README indica `@earendil-works/pi-coding-agent` por npm, con `--ignore-scripts`, y Node ≥ 22.19. Se asume que es el Pi que el usuario quiere instalar; esa elección es suya.
- **Paquetes de Ubuntu**: `gh` y `docker-compose-v2` vienen del repositorio de Ubuntu y pueden ir por detrás de las versiones del proveedor (p. ej. `gh` 2.4 en 22.04). Esto es una limitación aceptada.
- **GitHub Actions**: el CI usa `actions/checkout@v4` por etiqueta, no fijado a un commit SHA (pendiente), con permisos de solo lectura.

## Agentes y permisos

- Los agentes (Codex, Claude Code, Pi) pueden ejecutar comandos y editar archivos con los permisos de tu usuario, que tiene `sudo`. Trabaja con los modos de aprobación por defecto y no uses banderas que desactiven confirmaciones o sandbox.
- Usa un servidor dedicado, sin secretos de producción, y revisa qué repositorios y credenciales monta.
- `sudo docker` equivale a acceso root: el módulo `docker` es opcional por eso y no añade tu usuario al grupo `docker`.
- Los logins (`gh auth login`, `vercel login`, `supabase login`, `sanity login`, `codex login`, `claude`, y `pi` → `/login` solo con `--with-pi`) son manuales y dejan credenciales en tu HOME. No las subas al repositorio (`.gitignore` cubre las rutas habituales, sin garantía).

## Reportar un problema

Usa un canal privado del equipo de Interwwweb; no publiques la vulnerabilidad en un issue abierto. Contacto específico: Pendiente. No está confirmado que el repositorio tenga activados los avisos privados de seguridad de GitHub.
