# Secretos en el VPS: guía orientativa

> **Solo consejo.** El usuario **no** ha aprobado activar ningún almacén de secretos. Este repositorio **no instala, activa ni conecta** Bitwarden (`bws`/`bw`), Vault, ningún servicio de llavero ni D-Bus, y **no genera, guarda ni lee** claves. Esta guía solo describe opciones y riesgos para que decidas tú.

## ¿Debe el VPS tener un almacén de claves?

Recomendación: **no** montes un almacén maestro en el mismo VPS que ejecuta los agentes, y **no** copies tu gestor de contraseñas personal al servidor. Si necesitas secretos, usa un gestor **externo** y entrega a cada proceso solo lo que necesita.

- Un almacén local puede proteger secretos cifrados en reposo, pero **no aísla al agente de una clave que ya se le entregó**. Root y, según los permisos del sistema, otros procesos del mismo usuario pueden acceder a credenciales disponibles en archivos, entorno o memoria.
- Un agente con `sudo` amplio o como root puede romper la separación entre usuarios y procesos dentro del VPS. Evita agentes root y credenciales compartidas entre proyectos.
- Una credencial por proyecto y por servidor, con los permisos mínimos, y de vida corta y revocable **cuando el proveedor lo permita** (no todos lo permiten).

## Opción de ejemplo: gestor de secretos externo (Bitwarden Secrets Manager)

Distingue dos productos distintos:

- **Gestor de contraseñas** (`bw`): para personas. No lo uses en el VPS de agentes.
- **Secrets Manager** (`bws`): para máquinas, con *machine accounts*. Una cuenta de máquina por VPS o por proyecto, con acceso solo a los secretos que necesita.

Fuentes (consultadas por quien coordina el proyecto el 17/10/2026; el plan, la cuenta y los permisos concretos **no** están verificados, y esto es una recomendación, no una decisión activada):

- <https://bitwarden.com/help/secrets-manager-cli/>
- <https://bitwarden.com/help/machine-accounts/>

Límites que debes asumir:

- El **token de la cuenta de máquina sigue siendo un secreto** y tiene que llegar al VPS de alguna forma («secret zero»). Un gestor externo no elimina ese problema, solo lo reduce a una credencial.
- Hay que planificar **rotación y revocación** (qué haces si el token se filtra) y qué ocurre si el proveedor **no está disponible**.
- No uses `eval` ni cargues sin validar un archivo de entorno generado a partir de un gestor: un valor malicioso se ejecutaría como código.

## Qué NO hacer

- No guardes claves en `.env`, en `.linear.toml` ni en ningún archivo del repositorio. `.gitignore` ayuda pero **no basta**: no protege archivos ya seguidos por Git.
- No pases claves por línea de comandos (por ejemplo, con una opción `--api-key`): quedan en el historial del shell y son visibles en la lista de procesos.
- No imprimas tokens (por ejemplo, la salida de una orden que muestre el token) ni listes el contenido de secretos en logs. No actives trazas de shell (`set -x`, `bash -x`) en scripts que manejen secretos.
- Un archivo con permisos `0600` es un **respaldo en texto plano**, **no** un almacén cifrado. No lo presentes como tal.
- No uses un entorno global por defecto (`export` en `~/.profile`) para credenciales: da acceso a todo proceso. Mejor por proyecto y por proceso.

## Llavero local de Linux (Secret Service)

Un llavero de escritorio solo funciona con un **Secret Service realmente desbloqueado y un bus D-Bus de sesión**. En un servidor sin escritorio (headless), instalar `libsecret-tools` **no es suficiente** por sí solo. Este repositorio no instala ni configura ninguno de esos componentes.

Las herramientas de autenticación locales varían: algunas usan el llavero nativo, otras guardan texto plano o cachés de sesión. **No existe cifrado central automático** de lo que dejan las CLIs en tu HOME.

## Linear CLI comunitaria (`schpet/linear-cli`)

El módulo `cloud` instala la CLI **comunitaria** (no es oficial de Linear) `@schpet/linear-cli@3.0.0`, fijada. Documentación de autenticación (verificada por quien coordina el proyecto):
<https://github.com/schpet/linear-cli/blob/main/docs/authentication.md>

Lo que describe esa documentación:

- `linear auth login`: flujo interactivo con una API key, guardada en el llavero nativo (en Linux, `secret-tool`).
- Variable `LINEAR_API_KEY` como alternativa limitada al proceso que la necesita.
- Metadatos en `~/.config/linear/credentials.toml`.
- Clientes más antiguos podían guardar la clave en texto plano.

Recomendación:

- Usa `linear auth login` **solo cuando ya tengas un almacén seguro disponible** (ver arriba). No hay inicio de sesión automático ni migración de tokens en este repositorio.
- Si usas la variable de entorno, limítala a un proceso concreto y obtén el valor de tu gestor externo. No pegues valores reales ni de aspecto real en documentación, scripts o historial.
- Comprobar que funciona es manual y es cosa tuya: ni `install.sh` ni `doctor.sh` ejecutan jamás `linear auth`, `whoami` ni consultas a cuentas, equipos o proyectos.

La única orden de autenticación que este repositorio muestra, y solo la imprime sin ejecutarla, es:

```bash
linear auth login
```

## Resumen

| Pregunta | Respuesta corta |
| --- | --- |
| ¿Almacén maestro en el VPS de agentes? | No por defecto. |
| ¿Copiar mi gestor personal al VPS? | No. |
| ¿Un gestor externo basta? | Reduce el problema a un token de máquina que sigue siendo secreto. |
| ¿Es un aislamiento? | No: el mismo usuario o root puede leer lo inyectado. |
| ¿Archivo `0600`? | Texto plano, no cifrado. |
| ¿Llavero en un servidor sin escritorio? | Requiere Secret Service desbloqueado y D-Bus; no basta con `libsecret-tools`. |
