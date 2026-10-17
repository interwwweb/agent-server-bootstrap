"""Tests de install.sh con comandos simulados: no instalan nada ni usan la red."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
DOCTOR = ROOT / "doctor.sh"
BASH = shutil.which("bash")

# Comandos que un dry-run jamás debe invocar.
FORBIDDEN = ["curl", "wget", "sudo", "apt-get", "npm", "git", "sh"]


EXT_COMMIT = "93d60682e2aeca492d05c19ca3dbc3b46f360241"
EXT_URL = "https://github.com/interwwweb/pi-selection-editor.git"
# Oculta pi hasta que un npm simulado cree FAKEBIN/pi (sin depender de lo que haya en el sistema).
PI_HIDE = 'have() { if [ "$1" = pi ] && [ ! -x "$FAKEBIN/pi" ]; then return 1; fi; command -v "$1" >/dev/null 2>&1; }'


# Oculta tailscale/tailscaled hasta que un apt-get simulado cree FAKEBIN/<nombre>.
TS_HIDE = ('have() { if { [ "$1" = tailscale ] || [ "$1" = tailscaled ]; } && [ ! -x "$FAKEBIN/$1" ]; '
           'then return 1; fi; command -v "$1" >/dev/null 2>&1; }')


def hide(*names):
    """Código bash que redefine `have` para ocultar comandos concretos y delega el resto."""
    cond = " || ".join(f'[ "$1" = {n} ]' for n in names)
    return f'have() {{ if {cond}; then return 1; fi; command -v "$1" >/dev/null 2>&1; }}'


def os_release(id_, version):
    return f'ID={id_}\nVERSION_ID="{version}"\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.mock = self.tmp / "mock"
        self.mock.mkdir()
        self.log = self.tmp / "mock.log"
        for name in FORBIDDEN:
            p = self.mock / name
            p.write_text('#!/bin/sh\necho "$0 $*" >> "$MOCK_LOG"\nexit 97\n')
            p.chmod(p.stat().st_mode | stat.S_IXUSR)

    def release(self, id_="ubuntu", version="24.04"):
        p = self.tmp / "os-release"
        p.write_text(os_release(id_, version))
        return p

    def env(self, **extra):
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.mock}:/usr/bin:/bin",
            "MOCK_LOG": str(self.log),
        }
        env.update(extra)
        return env

    def run_install(self, *args, release=None, euid="1000", arch="x86_64", **extra):
        env = self.env(**extra)
        if release is not False:
            env.update(
                ASB_TEST="1",
                ASB_OS_RELEASE=str(release or self.release()),
                ASB_EUID=euid,
                ASB_ARCH=arch,
            )
        return subprocess.run(
            [BASH, str(INSTALL), *args], env=env, cwd=self.tmp,
            capture_output=True, text=True, timeout=60,
        )

    def assert_untouched(self):
        self.assertEqual(list(self.home.rglob("*")), [], "el dry-run escribió en HOME")
        calls = self.log.read_text() if self.log.exists() else ""
        self.assertEqual(calls, "", f"se invocaron comandos prohibidos:\n{calls}")


class ParsingTests(Base):
    def test_help_works_on_any_os(self):
        r = self.run_install("--help", release=self.tmp / "no-existe")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Uso:", r.stdout)
        self.assert_untouched()

    def test_help_wins_even_after_other_args(self):
        r = self.run_install("--apply", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Uso:", r.stdout)

    def test_unknown_argument_fails_before_changes(self):
        r = self.run_install("--no-existe")
        self.assertEqual(r.returncode, 2)
        self.assertIn("desconocido", r.stderr)
        self.assert_untouched()

    def test_unknown_module(self):
        r = self.run_install("--modules", "base,nada")
        self.assertEqual(r.returncode, 2)
        self.assertIn("módulo desconocido", r.stderr)

    def test_empty_modules_rejected(self):
        self.assertEqual(self.run_install("--modules", "").returncode, 2)

    def test_apply_requires_yes_and_yes_requires_apply(self):
        self.assertEqual(self.run_install("--apply").returncode, 2)
        self.assertEqual(self.run_install("--yes").returncode, 2)
        self.assert_untouched()

    def test_apply_needs_vendor_flag_for_every_third_party_installer(self):
        r = self.run_install("--apply", "--yes")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--vendor-installers", r.stderr)
        for mod in ("python", "agents", "remote", "base,python", "node,agents,remote"):
            with self.subTest(modules=mod):
                r = self.run_install("--apply", "--yes", "--modules", mod)
                self.assertEqual(r.returncode, 2)
                self.assertIn("--vendor-installers", r.stderr)
        self.assert_untouched()

    def test_modules_with_only_empty_items_rejected(self):
        for value in ("", ",", " , "):
            with self.subTest(value=value):
                self.assertEqual(self.run_install("--modules", value).returncode, 2)
        self.assertEqual(self.run_install("--modules", "", "--with-docker").returncode, 2)

    def test_modules_value_is_not_glob_expanded(self):
        (self.tmp / "base").write_text("")
        r = self.run_install("--modules", "ba*")
        self.assertEqual(r.returncode, 2)
        self.assertIn("módulo desconocido", r.stderr)

    def test_with_pi_requires_agents(self):
        r = self.run_install("--with-pi", "--modules", "base")
        self.assertEqual(r.returncode, 2)
        self.assertIn("agents", r.stderr)

    def test_dry_run_conflicts_with_apply(self):
        self.assertEqual(self.run_install("--apply", "--yes", "--dry-run").returncode, 2)


class DryRunTests(Base):
    def test_default_dry_run_writes_nothing_and_uses_no_network(self):
        for version in ("24.04", "22.04"):
            for arch in ("x86_64", "aarch64"):
                with self.subTest(version=version, arch=arch):
                    r = self.run_install(release=self.release(version=version), arch=arch)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("DRY-RUN", r.stdout)
                    for mod in ("base", "node", "python", "agents", "cloud", "remote", "tailscale", "playwright"):
                        self.assertIn(f"== {mod}", r.stdout)
                    self.assertNotIn("== docker", r.stdout)
                    self.assert_untouched()

    def test_module_selection_and_docker_optional(self):
        r = self.run_install("--modules", "docker")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("docker.io", r.stdout)
        self.assertIn("apt-get update", r.stdout)
        self.assertNotIn("== base", r.stdout)
        r = self.run_install("--modules", "python", "--with-docker")
        self.assertIn("== docker", r.stdout)
        self.assert_untouched()

    def test_env_planned_once_for_any_user_cli_module(self):
        r = self.run_install()
        self.assertEqual(r.stdout.count("crear "), 1)
        for mod in ("python", "agents", "cloud", "remote", "playwright"):
            with self.subTest(module=mod):
                r = self.run_install("--modules", mod)
                self.assertEqual(r.stdout.count("crear "), 1)
        for mod in ("base", "docker", "tailscale"):
            with self.subTest(module=mod):
                self.assertNotIn("crear ", self.run_install("--modules", mod).stdout)

    def test_tailscale_is_default_and_dry_run_plans_signed_apt_repo(self):
        for version, codename in (("22.04", "jammy"), ("24.04", "noble")):
            with self.subTest(codename=codename):
                r = self.run_install("--modules", "tailscale", release=self.release(version=version))
                self.assertEqual(r.returncode, 0, r.stderr)
                out = r.stdout
                self.assertIn(f"https://pkgs.tailscale.com/stable/ubuntu/{codename}.noarmor.gpg", out)
                self.assertIn(
                    f"deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
                    f"https://pkgs.tailscale.com/stable/ubuntu {codename} main", out)
                self.assertIn("/etc/apt/sources.list.d/tailscale.list", out)
                self.assertIn("apt-get install -y tailscale", out)
                self.assertNotIn("tailscale up", out)
                self.assertNotIn("== base", out)
                self.assert_untouched()
        self.assertIn("== tailscale", self.run_install().stdout)

    def test_tailscale_apply_does_not_need_vendor_flag(self):
        r = subprocess.run(
            [BASH, "-c", f'set -euo pipefail; . "{INSTALL}"; APPLY=1; YES=1; MODULES_SET=1; MODULES=tailscale; validate_args'],
            env=self.env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_cloud_dry_run_plans_wrangler_workspace_and_wrapper_without_running(self):
        r = self.run_install("--modules", "cloud,node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"npm install --prefix \S+/tools/wrangler --save-exact wrangler@4\.151\.1")
        self.assertRegex(r.stdout, r"wrapper \S+/\.local/bin/wrangler -> \S+/tools/wrangler/node_modules/\.bin/wrangler")
        self.assertNotIn("wrangler login", r.stdout)
        self.assert_untouched()

    def test_cloud_dry_run_plans_pinned_linear_without_running(self):
        r = self.run_install("--modules", "cloud,node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"npm install --prefix \S+/tools/linear --save-exact @schpet/linear-cli@3\.0\.0")
        self.assertRegex(r.stdout, r"wrapper \S+/\.local/bin/linear -> \S+/tools/linear/node_modules/\.bin/linear")
        self.assertNotIn("linear auth", r.stdout)
        self.assert_untouched()

    def test_node_module_plans_pnpm_without_running_npm(self):
        r = self.run_install("--modules", "node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("npm install -g --no-audit --no-fund pnpm@12.14.0", r.stdout)
        self.assert_untouched()

    def test_with_pi_dry_run_plans_pinned_pi_then_extension(self):
        r = self.run_install("--with-pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        for text in ("@earendil-works/pi-coding-agent@0.87.1", "--ignore-scripts", "v0.1.2",
                     EXT_COMMIT, EXT_URL, "scripts/install.sh", "PI_CODING_AGENT_DIR"):
            self.assertIn(text, out)
        self.assertLess(out.index("pi-coding-agent@0.87.1"), out.index("== pi-selection-editor"))
        self.assert_untouched()

    def test_without_pi_flag_no_extension_in_plan(self):
        self.assertNotIn("pi-selection-editor", self.run_install().stdout)

    def test_pi_only_appears_with_flag(self):
        self.assertNotIn("pi-coding-agent", self.run_install().stdout)
        self.assertNotIn("pi →", self.run_install().stdout)

    def test_dry_run_plan_has_no_forbidden_flags_or_sudo_npm(self):
        r = self.run_install("--with-pi", "--vendor-installers")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertNotIn("sudo npm", out)
        self.assertNotIn("dangerously", out.lower())
        self.assertIn("--ignore-scripts", out)
        self.assertIn("SHASUMS256.txt", out)
        self.assertNotIn("install-deps", out)
        self.assertIn("apt-get install -y --no-install-recommends", out)
        self.assertIn("libnss3", out)
        self.assertIn("SHA-256", out)


class RejectionTests(Base):
    def test_rejects_non_ubuntu(self):
        r = self.run_install(release=self.release("debian", "12"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no admitido", r.stderr)
        self.assert_untouched()

    def test_rejects_other_ubuntu_versions(self):
        r = self.run_install(release=self.release("ubuntu", "20.04"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("20.04", r.stderr)

    def test_rejects_unsupported_arch(self):
        r = self.run_install(arch="i686")
        self.assertEqual(r.returncode, 1)
        self.assertIn("arquitectura", r.stderr)

    def test_rejects_root(self):
        r = self.run_install(euid="0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("root", r.stderr)
        self.assert_untouched()

    def test_test_overrides_ignored_without_flag(self):
        env = self.env(ASB_OS_RELEASE=str(self.release()), ASB_EUID="1000")
        r = subprocess.run([BASH, str(INSTALL)], env=env, capture_output=True, text=True, timeout=60)
        # Sin ASB_TEST=1 se usa el sistema real: en este equipo solo debe pasar en Ubuntu.
        if not Path("/etc/os-release").exists() or "ID=ubuntu" not in Path("/etc/os-release").read_text():
            self.assertEqual(r.returncode, 1)


class FunctionTests(Base):
    """Funciones del instalador cargadas con `source` (el script no ejecuta main al ser importado)."""

    def setUp(self):
        super().setUp()
        # Comandos simulados que sí funcionan; van por delante de los que siempre fallan.
        self.bin = self.tmp / "fakebin"
        self.bin.mkdir()

    def fake(self, name, body, directory=None):
        p = (directory or self.bin) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(0o755)
        return p

    def fake_node(self, major):
        self.fake("node", f'case "$1" in -p) echo {major};; --version) echo v{major}.1.0;; esac\n')

    def fake_npm(self):
        # Registra la llamada y crea los binarios del workspace indicado con --prefix.
        self.fake("npm", '''echo "npm $*" >> "$MOCK_LOG"
d=
while [ $# -gt 0 ]; do if [ "$1" = --prefix ]; then d=$2; fi; shift; done
if [ -n "$d" ]; then
  mkdir -p "$d/node_modules/.bin"
  for b in playwright playwright-cli supabase wrangler linear; do
    printf '#!/bin/sh\\necho "BIN %s $*" >> "$MOCK_LOG"\\n' "$b" > "$d/node_modules/.bin/$b"
    chmod 755 "$d/node_modules/.bin/$b"
  done
fi
''')

    def fake_logger(self, name):
        self.fake(name, f'echo "{name} $*" >> "$MOCK_LOG"\n')

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def sh(self, body, **extra):
        script = f'set -euo pipefail; . "{INSTALL}"; APPLY=1; {body}'
        extra.setdefault("PATH", f"{self.bin}:{self.mock}:/usr/bin:/bin")
        return subprocess.run(
            [BASH, "-c", script], env=self.env(**extra), capture_output=True, text=True, timeout=60
        )

    def test_require_node_refuses_low_version_even_without_node_module(self):
        self.fake_npm()
        self.fake_node(22)
        r = self.sh('SELECTED="agents"; require_node agents')
        self.assertEqual(r.returncode, 1)
        self.assertIn(">=24", r.stderr)
        self.assertIn("node v22", r.stderr)

    def test_require_node_refuses_missing_npm_or_node(self):
        self.fake_node(24)
        # Se oculta a propósito con `have`: no se depende de que el sistema carezca de node/npm.
        r = self.sh(f'{hide("npm")}; SELECTED="cloud"; require_node cloud')
        self.assertEqual(r.returncode, 1)
        self.assertIn("sin npm", r.stderr)
        r = self.sh(f'{hide("node", "npm")}; SELECTED="cloud"; require_node cloud')
        self.assertEqual(r.returncode, 1)
        self.assertIn("sin node", r.stderr)

    def test_require_node_accepts_node_24_with_npm(self):
        self.fake_npm()
        self.fake_node(24)
        self.assertEqual(self.sh('SELECTED="playwright"; require_node playwright').returncode, 0)

    def test_require_node_in_dry_run_only_warns(self):
        r = self.sh(f'{hide("node", "npm")}; APPLY=0; SELECTED="agents"; require_node agents')
        self.assertEqual(r.returncode, 0)
        self.assertIn("AVISO", r.stderr)

    # --- Pi fijado + extensión pi-selection-editor -------------------------------------------

    def ext_dir(self):
        return self.home / ".local/share/agent-server-bootstrap/extensions/pi-selection-editor"

    def make_ext(self):
        d = self.ext_dir()
        (d / "scripts").mkdir(parents=True)
        (d / "scripts/install.sh").write_text("#!/bin/sh\n")
        (d / "marker").write_text("no tocar\n")
        return d

    def fake_git(self):
        self.fake("git", f'''echo "git $*" >> "$MOCK_LOG"
if [ "$1" = -C ]; then shift 2; fi
case "$1" in
  clone)
    [ -z "$FAKE_CLONE_FAIL" ] || exit 1
    for a; do dest=$a; done
    mkdir -p "$dest/scripts"
    printf '#!/bin/sh\\n' > "$dest/scripts/install.sh" ;;
  rev-parse) echo "${{FAKE_HEAD:-{EXT_COMMIT}}}" ;;
  remote) echo "${{FAKE_ORIGIN:-{EXT_URL}}}" ;;
  status) printf '%s' "$FAKE_STATUS" ;;
esac
''')

    def fake_bash_logger(self):
        self.fake("bash", 'echo "bash $* PI_CODING_AGENT_DIR=$PI_CODING_AGENT_DIR" >> "$MOCK_LOG"\n')

    def fake_pi(self, version):
        self.fake("pi", f'echo "{version}"\n')

    def fake_agents_env(self):
        self.fake_node(24)
        self.fake("npm", '''echo "npm $*" >> "$MOCK_LOG"
if [ "$1" = prefix ]; then echo "$HOME/.local"; fi
case "$*" in *pi-coding-agent*) printf '#!/bin/sh\\necho 0.87.1\\n' > "$FAKEBIN/pi"; chmod 755 "$FAKEBIN/pi" ;; esac
''')
        for name in ("codex", "claude", "herdr"):
            self.fake(name, "")

    def call_index(self, fragment):
        return next(i for i, c in enumerate(self.calls()) if fragment in c)

    def test_with_pi_installs_pinned_pi_then_extension_then_upstream_installer(self):
        self.fake_agents_env()
        self.fake_git()
        self.fake_bash_logger()
        r = self.sh(f'{PI_HIDE}; SELECTED="agents"; WITH_PI=1; mod_agents', FAKEBIN=str(self.bin))
        self.assertEqual(r.returncode, 0, r.stderr)
        pi_i = self.call_index("pi-coding-agent@0.87.1")
        self.assertIn("--ignore-scripts", self.calls()[pi_i])
        clone_i = self.call_index("clone")
        run_i = self.call_index(f"bash {self.ext_dir()}/scripts/install.sh")
        self.assertLess(pi_i, clone_i)
        self.assertLess(clone_i, run_i)
        self.assertIn(f"--branch v0.1.2 --depth 1 {EXT_URL}", self.calls()[clone_i])
        self.assertEqual([p.name for p in self.ext_dir().parent.iterdir()], ["pi-selection-editor"])

    def test_without_with_pi_mod_agents_ignores_pi_and_extension(self):
        self.fake_agents_env()
        self.fake_git()
        self.fake_bash_logger()
        r = self.sh('SELECTED="agents"; WITH_PI=0; mod_agents', FAKEBIN=str(self.bin))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_existing_compatible_pi_is_kept_but_extension_still_installed(self):
        self.fake_agents_env()
        self.fake_git()
        self.fake_bash_logger()
        self.fake_pi("0.87.2")
        r = self.sh('SELECTED="agents"; WITH_PI=1; mod_agents', FAKEBIN=str(self.bin))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any("pi-coding-agent" in c for c in self.calls()))
        self.call_index(f"bash {self.ext_dir()}/scripts/install.sh")

    def test_existing_incompatible_pi_fails_without_installing_anything(self):
        self.fake_agents_env()
        self.fake_git()
        self.fake_bash_logger()
        self.fake_pi("0.87.0")
        r = self.sh('SELECTED="agents"; WITH_PI=1; mod_agents', FAKEBIN=str(self.bin))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no es compatible", r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith(("npm install", "git clone", "bash"))], [])
        self.assertFalse(self.ext_dir().exists())

    def test_pi_preflight_version_matrix_touches_nothing(self):
        self.fake_git()
        for version, ok in (("0.87.1", True), ("v0.87.5", True), ("pi 0.87.2", True), ("0.87.10", True),
                            ("0.87.0", False), ("0.88.0", False), ("0.86.9", False),
                            ("0.87.2-beta.1", False), ("0.87.", False), ("garbage", False)):
            with self.subTest(version=version):
                self.fake_pi(version)
                r = self.sh('SELECTED="base agents"; pi_preflight')
                self.assertEqual(r.returncode, 0 if ok else 1, r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.home.rglob("*")), [])

    def test_pi_preflight_needs_git_unless_base_selected(self):
        r = self.sh(f'{hide("git", "pi")}; SELECTED="agents"; pi_preflight')
        self.assertEqual(r.returncode, 1)
        self.assertIn("git", r.stderr)
        r = self.sh(f'{hide("git", "pi")}; SELECTED="base agents"; pi_preflight')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.make_ext()
        r = self.sh(f'{hide("git", "pi")}; SELECTED="base agents"; pi_preflight')
        self.assertEqual(r.returncode, 1)

    def test_pi_preflight_rejects_bad_existing_extension(self):
        self.make_ext()
        self.fake_git()
        self.assertEqual(self.sh(f'{hide("pi")}; SELECTED="agents"; pi_preflight').returncode, 0)
        r = self.sh(f'{hide("pi")}; SELECTED="agents"; pi_preflight', FAKE_HEAD="deadbeef")
        self.assertEqual(r.returncode, 1)

    def test_existing_verified_clone_is_reused_and_installer_runs_each_time(self):
        d = self.make_ext()
        self.fake_git()
        self.fake_bash_logger()
        r = self.sh("configure_pi; configure_pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any("clone" in c for c in self.calls()))
        self.assertEqual(len([c for c in self.calls() if c.startswith("bash ")]), 2)
        self.assertTrue((d / "marker").exists())

    def test_wrong_origin_commit_dirty_or_symlink_prevent_installer(self):
        d = self.make_ext()
        self.fake_git()
        self.fake_bash_logger()
        for extra in ({"FAKE_HEAD": "deadbeef"},
                      {"FAKE_ORIGIN": "https://github.com/otro/pi-selection-editor.git"},
                      {"FAKE_STATUS": "?? nuevo.txt\n"}):
            with self.subTest(**extra):
                r = self.sh("configure_pi", **extra)
                self.assertEqual(r.returncode, 1)
                self.assertIn("no se modifica", r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith(("bash ", "git clone"))], [])
        self.assertEqual((d / "marker").read_text(), "no tocar\n")
        other = self.tmp / "otro"
        other.mkdir()
        shutil.rmtree(d)
        d.symlink_to(other)
        self.assertEqual(self.sh("configure_pi").returncode, 1)
        self.assertEqual([c for c in self.calls() if c.startswith("bash ")], [])

    def test_failed_or_mismatched_clone_leaves_no_durable_dir(self):
        self.fake_git()
        self.fake_bash_logger()
        for extra in ({"FAKE_CLONE_FAIL": "1"}, {"FAKE_HEAD": "deadbeef"}):
            with self.subTest(**extra):
                r = self.sh("configure_pi", **extra)
                self.assertEqual(r.returncode, 1)
                self.assertFalse(self.ext_dir().exists())
                parent = self.ext_dir().parent
                self.assertEqual(list(parent.iterdir()) if parent.exists() else [], [])
        self.assertEqual([c for c in self.calls() if c.startswith("bash ")], [])

    def test_installer_inherits_runtime_env_and_settings_are_not_touched(self):
        self.fake_git()
        self.fake_bash_logger()
        agent_dir = self.tmp / "agentdir"
        agent_dir.mkdir()
        settings = agent_dir / "settings.json"
        settings.write_text('{"mio": true}\n')
        r = self.sh("configure_pi", PI_CODING_AGENT_DIR=str(agent_dir))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"PI_CODING_AGENT_DIR={agent_dir}", self.calls()[self.call_index("bash ")])
        self.assertEqual(settings.read_text(), '{"mio": true}\n')
        self.assertEqual(sorted(p.name for p in agent_dir.iterdir()), ["settings.json"])

    # --- Tailscale (repositorio apt oficial firmado) ----------------------------------------

    def ts_paths(self):
        etc = self.tmp / "etc"
        return etc / "keyrings/tailscale-archive-keyring.gpg", etc / "apt/sources.list.d/tailscale.list"

    def ts_state_paths(self):
        st = self.tmp / "st"
        return {"state_dir": st / "lib-tailscale", "defaults": st / "default-tailscaled",
                "unit": st / "tailscaled.service", "dropins": st / "tailscaled.service.d"}

    def ts_run(self, body="mod_tailscale", codename="noble", **extra):
        key, lst = self.ts_paths()
        work = self.tmp / "work"
        work.mkdir(exist_ok=True)
        st = {k: str(v) for k, v in self.ts_state_paths().items()}
        setup = (f'TS_STATE_DIR="{st["state_dir"]}"; TS_DEFAULTS="{st["defaults"]}"; '
                 f'TS_UNIT="{st["unit"]}"; TS_DROPINS="{st["dropins"]}"; '
                 f'TS_KEYRING="{key}"; TS_LIST="{lst}"; TS_SBIN_DAEMON="{self.tmp}/no-existe/tailscaled"; '
                 f'CA_BUNDLE="{self.tmp}/no-existe/ca.crt"; WORK="{work}"; OS_CODENAME={codename}; SELECTED=tailscale')
        return self.sh(f'{TS_HIDE}; {setup}; {body}', FAKEBIN=str(self.bin), **extra)

    def fake_ts_env(self):
        self.fake("curl", '''echo "curl $*" >> "$MOCK_LOG"
while [ $# -gt 0 ]; do if [ "$1" = -o ]; then out=$2; fi; shift; done
printf 'KEYDATA' > "$out"
''')
        self.fake("sudo", 'echo "sudo $*" >> "$MOCK_LOG"\nexec "$@"\n')
        self.fake("apt-get", '''echo "apt-get $*" >> "$MOCK_LOG"
case "$*" in *"install -y tailscale"*)
  for b in tailscale tailscaled; do
    printf '#!/bin/sh\\necho "tailscale-fake $0 $*" >> "$MOCK_LOG"\\n' > "$FAKEBIN/$b"; chmod 755 "$FAKEBIN/$b"
  done ;; esac
''')

    def test_tailscale_constants_are_official_paths(self):
        r = self.sh('printf "%s\\n%s\\n%s\\n" "$TS_BASE" "$TS_KEYRING" "$TS_LIST"')
        self.assertEqual(r.stdout.split(), [
            "https://pkgs.tailscale.com/stable/ubuntu",
            "/usr/share/keyrings/tailscale-archive-keyring.gpg",
            "/etc/apt/sources.list.d/tailscale.list"])

    def test_tailscale_state_constants_are_hardcoded_paths(self):
        r = self.sh('printf "%s\\n%s\\n%s\\n%s\\n" "$TS_STATE_DIR" "$TS_DEFAULTS" "$TS_UNIT" "$TS_DROPINS"')
        self.assertEqual(r.stdout.split(), [
            "/var/lib/tailscale", "/etc/default/tailscaled",
            "/etc/systemd/system/tailscaled.service", "/etc/systemd/system/tailscaled.service.d"])

    def test_tailscale_previous_state_prevents_install_and_is_preserved(self):
        self.fake_ts_env()
        for name, path in self.ts_state_paths().items():
            for kind in ("file", "dir", "broken-symlink"):
                with self.subTest(path=name, kind=kind):
                    shutil.rmtree(self.tmp / "st", ignore_errors=True)
                    path.parent.mkdir(parents=True)
                    if kind == "file":
                        path.write_text("secreto-no-leer\n")
                    elif kind == "dir":
                        path.mkdir()
                        (path / "x").write_text("estado\n")
                    else:
                        path.symlink_to(self.tmp / "no-existe")
                    if self.log.exists():
                        self.log.unlink()
                    for body in ("mod_tailscale", "ts_preflight"):
                        r = self.ts_run(body=body)
                        self.assertEqual(r.returncode, 1)
                        self.assertIn("estado o configuración previa", r.stderr)
                        self.assertIn(str(path), r.stderr)
                        self.assertNotIn("secreto", r.stdout + r.stderr)
                        self.assertEqual(self.calls(), [])
                        self.assertFalse((self.tmp / "etc").exists())
                    if kind == "file":
                        self.assertEqual(path.read_text(), "secreto-no-leer\n")
                    elif kind == "dir":
                        self.assertEqual((path / "x").read_text(), "estado\n")
                    else:
                        self.assertEqual(os.readlink(path), str(self.tmp / "no-existe"))

    def test_tailscale_complete_pair_skips_even_with_previous_state(self):
        self.fake_ts_env()
        self.fake("tailscale", "")
        self.fake("tailscaled", "")
        paths = self.ts_state_paths()
        paths["state_dir"].mkdir(parents=True)
        (paths["state_dir"] / "x").write_text("estado\n")
        paths["defaults"].write_text("FLAGS=1\n")
        paths["unit"].write_text("[Unit]\n")
        paths["dropins"].mkdir()
        for body in ("mod_tailscale", "ts_preflight"):
            r = self.ts_run(body=body)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual((paths["state_dir"] / "x").read_text(), "estado\n")
        self.assertEqual(paths["defaults"].read_text(), "FLAGS=1\n")
        self.assertEqual(paths["unit"].read_text(), "[Unit]\n")
        self.assertFalse((self.tmp / "etc").exists())

    def test_tailscale_skips_existing_pair_before_any_network_or_sudo(self):
        self.fake_ts_env()
        self.fake("tailscale", "")
        self.fake("tailscaled", "")
        r = self.ts_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("se omite", r.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.tmp / "etc").exists())

    def test_tailscale_partial_install_fails_without_changes(self):
        self.fake_ts_env()
        self.fake("tailscale", "")
        r = self.ts_run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("parcial", r.stderr)
        (self.bin / "tailscale").unlink()
        self.fake("tailscaled", "")
        r = self.ts_run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("parcial", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.tmp / "etc").exists())

    def test_tailscale_installs_key_list_then_apt_in_order_without_auth(self):
        self.fake_ts_env()
        for codename in ("jammy", "noble"):
            with self.subTest(codename=codename):
                shutil.rmtree(self.tmp / "etc", ignore_errors=True)
                for b in ("tailscale", "tailscaled"):
                    (self.bin / b).unlink(missing_ok=True)
                if self.log.exists():
                    self.log.unlink()
                r = self.ts_run(codename=codename)
                self.assertEqual(r.returncode, 0, r.stderr)
                key, lst = self.ts_paths()
                self.assertEqual(key.read_text(), "KEYDATA")
                self.assertEqual(
                    lst.read_text().splitlines()[1],
                    f"deb [signed-by={key}] https://pkgs.tailscale.com/stable/ubuntu {codename} main")
                self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE(lst.stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o755)
                calls = self.calls()
                self.assertIn(f"https://pkgs.tailscale.com/stable/ubuntu/{codename}.noarmor.gpg", calls[0])
                order = [self.call_index(f) for f in (f"sudo install -m0644 {self.tmp}/work/tailscale.gpg {key}",
                                                      f"sudo install -m0644 {self.tmp}/work/tailscale.list {lst}",
                                                      "apt-get update", "apt-get install -y tailscale")]
                self.assertEqual(order, sorted(order))
                self.assertEqual([c for c in calls if c.startswith("tailscale-fake")], [])

    def test_tailscale_conflicts_preserve_everything_and_write_nothing(self):
        self.fake_ts_env()
        key, lst = self.ts_paths()
        decoy = self.tmp / "decoy"

        def key_differs():
            key.parent.mkdir(parents=True); key.write_text("otra clave")

        def list_differs():
            lst.parent.mkdir(parents=True); lst.write_text("deb otra cosa\n")

        def key_symlink_same_bytes():
            key.parent.mkdir(parents=True); decoy.write_text("KEYDATA"); key.symlink_to(decoy)

        def key_dangling_symlink():
            key.parent.mkdir(parents=True); key.symlink_to(self.tmp / "no-existe")

        def list_symlink():
            lst.parent.mkdir(parents=True); decoy.write_text("x"); lst.symlink_to(decoy)

        def key_is_directory():
            key.mkdir(parents=True)

        cases = ((key_differs, lst), (list_differs, key), (key_symlink_same_bytes, lst),
                 (key_dangling_symlink, lst), (list_symlink, key), (key_is_directory, lst))
        for setup, other in cases:
            with self.subTest(case=setup.__name__):
                shutil.rmtree(self.tmp / "etc", ignore_errors=True)
                decoy.unlink(missing_ok=True)
                if self.log.exists():
                    self.log.unlink()
                setup()
                r = self.ts_run()
                self.assertEqual(r.returncode, 1)
                self.assertIn("no se modifica ninguno", r.stderr)
                self.assertFalse(os.path.lexists(other), "se escribió el otro archivo")
                self.assertEqual([c for c in self.calls() if c.startswith(("sudo", "apt-get"))], [])
        key_differs_state = (self.tmp / "etc")
        shutil.rmtree(key_differs_state, ignore_errors=True)
        key_differs()
        self.ts_run()
        self.assertEqual(key.read_text(), "otra clave")

    def test_tailscale_second_run_with_identical_files_only_runs_apt(self):
        self.fake_ts_env()
        self.assertEqual(self.ts_run().returncode, 0)
        key, lst = self.ts_paths()
        before = (key.read_bytes(), lst.read_bytes())
        for b in ("tailscale", "tailscaled"):
            (self.bin / b).unlink()
        self.log.unlink()
        r = self.ts_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("sudo install ")], [])
        self.assertTrue(any("apt-get install -y tailscale" in c for c in self.calls()))
        self.assertEqual((key.read_bytes(), lst.read_bytes()), before)

    def test_tailscale_empty_key_download_aborts_before_writing(self):
        self.fake_ts_env()
        self.fake("curl", 'while [ $# -gt 0 ]; do if [ "$1" = -o ]; then : > "$2"; fi; shift; done\n')
        r = self.ts_run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("descarga vacía", r.stderr)
        self.assertFalse((self.tmp / "etc").exists())

    def test_tailscale_refuses_unknown_codename(self):
        self.fake_ts_env()
        r = self.ts_run(codename="evil")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_ts_preflight_requirements(self):
        h_curl = hide("tailscale", "tailscaled", "curl")
        r = self.ts_run(body="ts_preflight")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ca-certificates", r.stderr)
        self.assertEqual(self.ts_run(body=f'{h_curl}; ts_preflight').returncode, 1)
        ca = self.tmp / "ca.crt"
        ca.write_text("")
        self.assertEqual(self.ts_run(body=f'CA_BUNDLE="{ca}"; ts_preflight').returncode, 0)
        r = self.ts_run(body=f'{h_curl}; SELECTED="base tailscale"; ts_preflight')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.fake("tailscale", "")
        r = self.ts_run(body='ts_preflight')  # solo tailscale existe: instalación parcial
        self.assertEqual(r.returncode, 1)
        self.assertIn("parcial", r.stderr)
        self.fake("tailscaled", "")
        self.assertEqual(self.ts_run(body='ts_preflight').returncode, 0)

    def test_mod_node_installs_pnpm_with_npm_global_after_node(self):
        self.fake_node(24)
        self.fake("npm", '''echo "npm $*" >> "$MOCK_LOG"
if [ "$1" = prefix ]; then echo "$HOME/.local"; fi
''')
        r = self.sh(f'{hide("pnpm")}; SELECTED="node"; mod_node')
        self.assertEqual(r.returncode, 0, r.stderr)
        installs = [c for c in self.calls() if c.startswith("npm install")]
        self.assertEqual(len(installs), 1)
        self.assertIn("-g", installs[0])
        self.assertTrue(installs[0].endswith(" pnpm@12.14.0"))
        # Si pnpm ya existe, se omite.
        self.fake("pnpm", "")
        self.log.unlink()
        self.assertEqual(self.sh('SELECTED="node"; mod_node').returncode, 0)
        self.assertEqual([c for c in self.calls() if c.startswith("npm install")], [])

    def test_apply_vendor_consent_parse(self):
        for mod in ("python", "agents", "remote", "base,agents"):
            with self.subTest(modules=mod, vendor=0):
                r = self.sh(f'YES=1; MODULES_SET=1; MODULES={mod}; validate_args')
                self.assertEqual(r.returncode, 2)
                self.assertIn("--vendor-installers", r.stderr)
            with self.subTest(modules=mod, vendor=1):
                r = self.sh(f'YES=1; VENDOR=1; MODULES_SET=1; MODULES={mod}; validate_args')
                self.assertEqual(r.returncode, 0, r.stderr)
        for mod in ("base", "node", "cloud", "playwright", "docker", "base,node,cloud,playwright,docker"):
            with self.subTest(modules=mod, vendor="not needed"):
                r = self.sh(f'YES=1; MODULES_SET=1; MODULES={mod}; validate_args')
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_download_run_refuses_without_vendor_consent_before_any_download(self):
        self.fake_logger("curl")
        r = self.sh('VENDOR=0; download_run uv uv https://example.invalid/install.sh sh')
        self.assertEqual(r.returncode, 1)
        self.assertIn("--vendor-installers", r.stderr)
        self.assertEqual(self.calls(), [])

    # --- Verificación SHA-256 de scripts de terceros (falla cerrado) --------------------------

    VENDOR_URLS = {
        "https://astral.sh/uv/install.sh": "7c482d409673a53f4d9bd34ae95c9166be3b8d89ca82f27dd7bca3cab457afff",
        "https://claude.ai/install.sh": "3a68d3406cf674e17bed1733a4dcf37805e2e47d87417700007d7e1aa766a944",
        "https://herdr.dev/install.sh": "bf83668c944cff30b3365eee5a4fe15ff61a4b749ab0c73b98e7a203f70893dd",
        "https://getmoshi.app/install.sh": "36d6beb7d96ae0100920325bdc601ce398984de99b86f222924c3e6a4b722a80",
    }

    def fake_vendor_curl(self, content):
        self.fake("curl", f'''echo "curl $*" >> "$MOCK_LOG"
while [ $# -gt 0 ]; do if [ "$1" = -o ]; then out=$2; fi; shift; done
printf '%s' '{content}' > "$out"
''')
        self.fake_logger("fakeinterp")

    def vendor_run(self, url="https://astral.sh/uv/install.sh", pre=":"):
        work = self.tmp / "work"
        work.mkdir(exist_ok=True)
        return self.sh(f'{hide("uv")}; VENDOR=1; WORK="{work}"; {pre}; download_run uv uv {url} fakeinterp --flag')

    def test_vendor_hashes_are_pinned_for_exactly_the_four_urls(self):
        for url, digest in self.VENDOR_URLS.items():
            with self.subTest(url=url):
                r = self.sh(f'vendor_expected_sha256 "{url}"')
                self.assertEqual(r.stdout, digest)
        self.assertEqual(self.sh('vendor_expected_sha256 https://example.invalid/install.sh').returncode, 1)

    def test_vendor_hash_mismatch_fails_closed_before_executing(self):
        self.fake_vendor_curl("echo contenido-cambiado")
        r = self.vendor_run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no coincide", r.stderr)
        self.assertIn("no se ejecuta", r.stderr)
        calls = self.calls()
        self.assertTrue(any(c.startswith("curl ") for c in calls))
        self.assertEqual([c for c in calls if c.startswith("fakeinterp")], [])

    def test_vendor_hash_match_executes_verified_file_exactly_once(self):
        import hashlib
        content = "echo verificado"
        self.fake_vendor_curl(content)
        digest = hashlib.sha256(content.encode()).hexdigest()
        r = self.vendor_run(pre=f'VENDOR_SHA256_UV={digest}')
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = [c for c in self.calls() if c.startswith("fakeinterp")]
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].endswith(" --flag"))

    def test_vendor_url_without_pinned_hash_never_downloads(self):
        self.fake_vendor_curl("x")
        r = self.vendor_run(url="https://example.invalid/install.sh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no hay un SHA-256 fijado", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_vendor_hash_has_no_skip_flag(self):
        for flag in ("--skip-verification", "--insecure", "--no-verify"):
            with self.subTest(flag=flag):
                self.assertEqual(self.run_install(flag).returncode, 2)

    def test_fetch_is_https_only_including_redirects(self):
        self.fake_vendor_curl("x")
        out = self.tmp / "out"
        r = self.sh(f'fetch https://example.invalid/x "{out}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        line = next(c for c in self.calls() if c.startswith("curl "))
        self.assertIn("--proto =https", line)
        self.assertIn("--proto-redir =https", line)
        self.assertNotIn("-k", line.split())
        self.assertNotIn("--insecure", line)

    def test_playwright_sudo_runs_only_system_apt_with_fixed_path_and_per_release_lists(self):
        self.fake_npm()
        self.fake_node(24)
        self.fake_logger("sudo")
        packages = {"jammy": ("libasound2 ", "libwayland-client0"), "noble": ("libasound2t64", "libatspi2.0-0t64")}
        for codename, expected in packages.items():
            with self.subTest(codename=codename):
                shutil.rmtree(self.home, ignore_errors=True)
                self.home.mkdir()
                if self.log.exists():
                    self.log.unlink()
                r = self.sh(f'SELECTED="playwright"; OS_CODENAME={codename}; mod_playwright')
                self.assertEqual(r.returncode, 0, r.stderr)
                sudo_calls = [c for c in self.calls() if c.startswith("sudo")]
                self.assertEqual(len(sudo_calls), 2)
                for call in sudo_calls:
                    self.assertIn("env PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive apt-get ", call)
                    for forbidden in ("node_modules", "playwright", "npm", "install-deps", str(self.home)):
                        self.assertNotIn(forbidden, call)
                for fragment in expected:
                    self.assertIn(fragment, sudo_calls[1])
        r = self.sh('SELECTED="playwright"; OS_CODENAME=focal; mod_playwright')
        self.assertEqual(r.returncode, 1)

    def test_install_script_has_no_sudo_with_user_path_or_npm_code(self):
        code = [l for l in INSTALL.read_text().splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if "install-deps" in l], [])
        for line in code:
            if "run sudo" not in line:
                continue
            for forbidden in ('PATH=$PATH', "$pw", "npm", "npx", "node"):
                self.assertNotIn(forbidden, line)

    def test_npm_workspace_preserves_package_json_and_is_idempotent(self):
        self.fake_npm()
        ws = self.home / "ws"
        ws.mkdir()
        (ws / "package.json").write_text('{"name": "mio"}\n')
        self.assertEqual(self.sh(f'npm_workspace "{ws}" pkg-a pkg-b').returncode, 0)
        self.assertEqual((ws / "package.json").read_text(), '{"name": "mio"}\n')
        self.assertTrue(any(c.startswith(f"npm install --prefix {ws}") and c.endswith("pkg-a pkg-b") for c in self.calls()))
        fresh = self.home / "ws2"
        self.assertEqual(self.sh(f'npm_workspace "{fresh}" x; npm_workspace "{fresh}" x').returncode, 0)
        self.assertIn('"private": true', (fresh / "package.json").read_text())

    def test_mod_playwright_installs_once_and_wrappers_are_idempotent(self):
        self.fake_npm()
        self.fake_node(24)
        self.fake_logger("sudo")
        script = 'SELECTED="playwright"; OS_CODENAME=noble; mod_playwright'
        self.assertEqual(self.sh(script).returncode, 0)
        npm_calls = [c for c in self.calls() if c.startswith("npm ")]
        self.assertEqual(len(npm_calls), 1)
        self.assertIn("--save-exact @playwright/test@1.64.1 @playwright/cli@0.1.22", npm_calls[0])
        sudo_calls = [c for c in self.calls() if c.startswith("sudo")]
        self.assertEqual(len(sudo_calls), 2)  # apt-get update + apt-get install; nada más con sudo
        self.assertIn("apt-get update", sudo_calls[0])
        self.assertIn("apt-get install -y --no-install-recommends", sudo_calls[1])
        self.assertIn("libasound2t64", sudo_calls[1])
        self.assertTrue(any(c.endswith("install chromium") for c in self.calls() if c.startswith("BIN")))
        wrappers = [self.home / ".local/bin/playwright", self.home / ".local/bin/playwright-cli"]
        before = [w.read_text() for w in wrappers]
        for w in wrappers:
            self.assertTrue(os.access(w, os.X_OK))
            self.assertIn("exec ", w.read_text())
        self.assertEqual(self.sh(script).returncode, 0)
        self.assertEqual(len([c for c in self.calls() if c.startswith("npm ")]), 1)
        self.assertEqual([w.read_text() for w in wrappers], before)

    def test_mod_cloud_supabase_wrapper_uses_workspace_binary(self):
        self.fake_npm()
        self.fake_node(24)
        for name in ("vercel", "sanity"):
            self.fake(name, "")
        r = self.sh('SELECTED="cloud"; mod_cloud')
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.home / ".local/bin/supabase").read_text()
        self.assertIn(str(self.home / ".local/share/agent-server-bootstrap/tools/supabase/node_modules/.bin/supabase"), text)

    # --- Wrangler (CLI de Cloudflare Workers) ------------------------------------------------

    def wrangler_ws_bin(self):
        return self.home / ".local/share/agent-server-bootstrap/tools/wrangler/node_modules/.bin/wrangler"

    def test_mod_wrangler_installs_in_dedicated_workspace_with_wrapper(self):
        self.fake_npm()
        self.fake_node(24)
        r = self.sh(f'{hide("wrangler")}; SELECTED="cloud"; mod_wrangler')
        self.assertEqual(r.returncode, 0, r.stderr)
        installs = [c for c in self.calls() if c.startswith("npm install")]
        self.assertEqual(len(installs), 1)
        self.assertIn("--prefix", installs[0])
        self.assertIn("agent-server-bootstrap/tools/wrangler", installs[0])
        self.assertTrue(installs[0].endswith(" wrangler@4.151.1"))
        self.assertIn("--save-exact", installs[0])
        self.assertNotIn(" -g ", installs[0])
        self.assertFalse(any(c.startswith("sudo") for c in self.calls()))
        wrapper = self.home / ".local/bin/wrangler"
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn(f"exec {self.wrangler_ws_bin()}", wrapper.read_text())
        self.assertFalse((self.tmp / "package.json").exists())  # nada en el directorio desde el que se invoca

    def test_mod_wrangler_skips_when_command_already_exists(self):
        self.fake_npm()
        self.fake_node(24)
        self.fake("wrangler", "")
        r = self.sh('SELECTED="cloud"; mod_wrangler')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("se omite", r.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.home / ".local").exists())

    def test_mod_wrangler_reuses_workspace_executable_and_keeps_wrapper(self):
        self.fake_npm()
        self.fake_node(24)
        self.assertEqual(self.sh(f'{hide("wrangler")}; mod_wrangler').returncode, 0)
        wrapper = self.home / ".local/bin/wrangler"
        wrapper.write_text("#!/bin/sh\n# mío\n")
        self.log.unlink()
        r = self.sh(f'{hide("wrangler")}; mod_wrangler')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("npm install")], [])
        self.assertEqual(wrapper.read_text(), "#!/bin/sh\n# mío\n")

    def test_mod_wrangler_requires_node_24(self):
        self.fake_npm()
        self.fake_node(22)
        r = self.sh(f'{hide("wrangler")}; mod_wrangler')
        self.assertEqual(r.returncode, 1)
        self.assertIn(">=24", r.stderr)
        self.assertEqual(self.calls(), [])

    # --- Linear CLI comunitaria (schpet/linear-cli) fijada ------------------------------------

    def linear_ws_bin(self):
        return self.home / ".local/share/agent-server-bootstrap/tools/linear/node_modules/.bin/linear"

    def test_mod_linear_installs_pinned_package_in_dedicated_workspace(self):
        self.fake_npm()
        self.fake_node(24)
        r = self.sh(f'{hide("linear")}; SELECTED="cloud"; mod_linear')
        self.assertEqual(r.returncode, 0, r.stderr)
        installs = [c for c in self.calls() if c.startswith("npm install")]
        self.assertEqual(len(installs), 1)
        self.assertIn("agent-server-bootstrap/tools/linear", installs[0])
        self.assertIn("--save-exact", installs[0])
        self.assertTrue(installs[0].endswith(" @schpet/linear-cli@3.0.0"))
        self.assertNotIn(" -g ", installs[0])
        self.assertNotIn("deno", " ".join(self.calls()).lower())
        self.assertFalse(any(c.startswith("sudo") for c in self.calls()))
        wrapper = self.home / ".local/bin/linear"
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn(f"exec {self.linear_ws_bin()}", wrapper.read_text())

    def test_mod_linear_skips_when_command_already_exists(self):
        self.fake_npm()
        self.fake_node(24)
        self.fake("linear", "")
        r = self.sh('SELECTED="cloud"; mod_linear')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("se omite", r.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.home / ".local").exists())

    def test_mod_linear_reuses_workspace_launcher_and_keeps_wrapper(self):
        self.fake_npm()
        self.fake_node(24)
        self.assertEqual(self.sh(f'{hide("linear")}; mod_linear').returncode, 0)
        wrapper = self.home / ".local/bin/linear"
        wrapper.write_text("#!/bin/sh\n# mío\n")
        self.log.unlink()
        r = self.sh(f'{hide("linear")}; mod_linear')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("npm install")], [])
        self.assertEqual(wrapper.read_text(), "#!/bin/sh\n# mío\n")

    def test_mod_linear_requires_node_24(self):
        self.fake_npm()
        self.fake_node(22)
        r = self.sh(f'{hide("linear")}; mod_linear')
        self.assertEqual(r.returncode, 1)
        self.assertIn(">=24", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_mod_linear_never_calls_the_cli(self):
        self.fake_npm()
        self.fake_node(24)
        # El launcher simulado registra cualquier invocación: install.sh no debe ejecutarlo nunca.
        self.sh(f'{hide("linear")}; mod_linear')
        self.assertEqual([c for c in self.calls() if c.startswith("BIN linear")], [])

    def test_mod_docker_alone_updates_apt_before_install(self):
        self.fake_logger("sudo")
        self.assertEqual(self.sh('SELECTED="docker"; mod_docker').returncode, 0)
        sudo = [c for c in self.calls() if c.startswith("sudo")]
        self.assertEqual(len(sudo), 2)
        self.assertIn("apt-get update", sudo[0])
        self.assertIn("apt-get install -y docker.io docker-compose-v2", sudo[1])

    def test_mod_docker_with_base_does_not_update_twice(self):
        self.fake_logger("sudo")
        self.assertEqual(self.sh('SELECTED="base docker"; mod_docker').returncode, 0)
        sudo = [c for c in self.calls() if c.startswith("sudo")]
        self.assertEqual(len(sudo), 1)
        self.assertIn("install -y", sudo[0])

    def fake_curl_shasums(self):
        self.fake("curl", '''while [ $# -gt 0 ]; do if [ "$1" = -o ]; then out=$2; fi; shift; done
printf 'deadbeef  node-v24.1.0-linux-x64.tar.gz\\n' > "$out"
''')

    def test_install_node_fails_early_when_current_points_elsewhere(self):
        self.fake_curl_shasums()
        root = self.home / ".local/share/agent-server-bootstrap/node"
        (root / "v22.0.0").mkdir(parents=True)
        (root / "current").symlink_to(root / "v22.0.0")
        work = self.tmp / "work"
        work.mkdir()
        r = self.sh(f'NODE_ARCH=x64; WORK="{work}"; install_node')
        self.assertEqual(r.returncode, 1)
        self.assertIn("no apunta", r.stderr)
        self.assertEqual(os.readlink(root / "current"), str(root / "v22.0.0"))
        self.assertFalse((root / "v24.1.0").exists())

    def test_install_node_keeps_matching_current_link(self):
        self.fake_curl_shasums()
        root = self.home / ".local/share/agent-server-bootstrap/node"
        (root / "v24.1.0").mkdir(parents=True)
        (root / "current").symlink_to(root / "v24.1.0")
        work = self.tmp / "work"
        work.mkdir()
        r = self.sh(f'NODE_ARCH=x64; WORK="{work}"; install_node')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(root / "current"), str(root / "v24.1.0"))

    def test_profile_block_is_idempotent_and_preserves_content(self):
        profile = self.home / ".profile"
        profile.write_text("# mío\nexport A=1\n")
        r = self.sh("ensure_env; ensure_env; ensure_profile")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = profile.read_text()
        self.assertTrue(text.startswith("# mío\nexport A=1\n"))
        self.assertEqual(text.count(">>> agent-server-bootstrap >>>"), 1)
        self.assertEqual(text.count("<<< agent-server-bootstrap <<<"), 1)
        self.assertIn("if [ -f", text)

    def test_profile_created_when_missing(self):
        self.assertEqual(self.sh("ensure_env").returncode, 0)
        self.assertIn("agent-server-bootstrap", (self.home / ".profile").read_text())

    def test_existing_env_file_not_overwritten(self):
        env_file = self.home / ".local/share/agent-server-bootstrap/env.sh"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("# propio\n")
        self.assertEqual(self.sh("ensure_env").returncode, 0)
        self.assertEqual(env_file.read_text(), "# propio\n")

    def test_new_env_file_contents(self):
        self.sh("ensure_env")
        text = (self.home / ".local/share/agent-server-bootstrap/env.sh").read_text()
        self.assertIn("NPM_CONFIG_PREFIX", text)
        self.assertIn(".local/bin", text)

    def test_wrapper_never_overwrites_existing_binary(self):
        binp = self.home / ".local/bin"
        binp.mkdir(parents=True)
        (binp / "supabase").write_text("original\n")
        self.assertEqual(self.sh("write_wrapper supabase /abs/target").returncode, 0)
        self.assertEqual((binp / "supabase").read_text(), "original\n")

    def test_wrapper_execs_absolute_target(self):
        fake = self.tmp / "fakenode"
        fake.mkdir()
        node = fake / "node"
        node.write_text("#!/bin/sh\n")
        node.chmod(0o755)
        r = self.sh("write_wrapper tool /abs/dir/bin/tool", PATH=f"{fake}:/usr/bin:/bin")
        self.assertEqual(r.returncode, 0, r.stderr)
        w = self.home / ".local/bin/tool"
        self.assertTrue(os.access(w, os.X_OK))
        text = w.read_text()
        self.assertIn("exec /abs/dir/bin/tool", text)
        self.assertIn(str(fake), text)


class SupplyChainTests(Base):
    """Pines y CI comprobados de forma estática (sin red)."""

    PINS = {
        "PNPM": "12.14.0", "CODEX": "0.163.0", "VERCEL": "64.5.0", "SANITY": "8.19.0",
        "SUPABASE": "2.121.0", "WRANGLER": "4.151.1", "PLAYWRIGHT_TEST": "1.64.1",
        "PLAYWRIGHT_CLI": "0.1.22", "LINEAR": "3.0.0", "PI": "0.87.1",
    }
    CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    SETUP_NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
    GITLEAKS_SHA = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"

    def code_lines(self):
        return [l for l in INSTALL.read_text().splitlines() if not l.lstrip().startswith("#")]

    def test_direct_npm_versions_are_central_exact_and_used(self):
        pins = dict(re.findall(r"^([A-Z_]+)_VERSION=(\S+)$", INSTALL.read_text(), re.M))
        for name, version in self.PINS.items():
            self.assertEqual(pins.get(name), version, name)
        code = "\n".join(self.code_lines())
        for name in self.PINS:
            if name in ("PI",):
                continue
            self.assertRegex(code, rf"(npm_global|npm_workspace).*@\${name}_VERSION", name)
        self.assertNotIn("@latest", code)
        for line in code.splitlines():
            if "npm_workspace" in line and "npm_workspace()" not in line and "dir=" not in line:
                self.assertIn("--save-exact", line)

    def test_actions_are_pinned_to_full_commit_sha(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        uses = re.findall(r"uses:\s*(\S+)", text)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
        self.assertIn(self.CHECKOUT, text)
        self.assertIn(self.SETUP_NODE, text)
        self.assertNotIn("@v4\n", text)

    def test_dependabot_updates_github_actions_weekly(self):
        text = (ROOT / ".github/dependabot.yml").read_text()
        self.assertIn('package-ecosystem: "github-actions"', text)
        self.assertIn('interval: "weekly"', text)

    def test_gitleaks_job_uses_verified_official_binary_without_marketplace_action(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn(self.GITLEAKS_SHA, text)
        self.assertIn('GITLEAKS_VERSION: "8.30.1"', text)
        self.assertIn("sha256sum -c -", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("--redact", text)
        self.assertIn("--proto-redir '=https'", text)
        self.assertNotIn("gitleaks-action", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("GITLEAKS_LICENSE", text)

    def test_playwright_integration_refuses_without_explicit_opt_in(self):
        # Sin ASB_EPHEMERAL_RUNNER=1 el script debe salir antes de crear nada o invocar comandos.
        # (Nunca se activa el opt-in en estos tests: en Linux instalaría paquetes de verdad.)
        env = self.env(TMPDIR=str(self.tmp))
        r = subprocess.run([BASH, str(ROOT / "tests/playwright-integration.sh")], env=env, cwd=self.tmp,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ASB_EPHEMERAL_RUNNER=1", r.stderr)
        self.assertEqual(list(self.home.rglob("*")), [])
        self.assertFalse(any(p.name.startswith("asb-playwright") for p in self.tmp.iterdir()))
        self.assertFalse(self.log.exists())

    def test_playwright_integration_guards_come_before_any_write_and_ci_runs_it_opt_in(self):
        script = (ROOT / "tests/playwright-integration.sh").read_text()
        order = [script.index(m) for m in ('"${ASB_EPHEMERAL_RUNNER:-}" = 1', "uname -s", "id -u", "mktemp -d")]
        self.assertEqual(order, sorted(order))
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", script)
        self.assertIn("PLAYWRIGHT_TEST_VERSION", script)
        self.assertIn("title !== 'hello'", script)
        for direct in ("sudo apt", "sudo env", "sudo -", "sudo npm", "sudo install", "run sudo"):
            self.assertNotIn(direct, script)  # el único sudo es el de mod_playwright (install.sh)
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        job = ci[ci.index("  playwright-integration:"):]
        self.assertIn("timeout-minutes: 15", job)
        self.assertIn('ASB_EPHEMERAL_RUNNER: "1"', job)
        self.assertIn("bash tests/playwright-integration.sh", job)
        self.assertIn("ubuntu-24.04, ubuntu-22.04", job)
        self.assertIn(self.CHECKOUT, job)
        self.assertIn(self.SETUP_NODE, job)
        self.assertIn("bash -n tests/playwright-integration.sh", ci)
        self.assertIn("tests/playwright-integration.sh\n", ci.split("- name: ShellCheck")[1])

    def test_playwright_apt_lists_match_pinned_release(self):
        text = INSTALL.read_text()
        self.assertIn("tag v1.64.1", text)
        self.assertEqual(self.PINS["PLAYWRIGHT_TEST"], "1.64.1")
        for arr, needle in (("PW_APT_JAMMY", "libasound2 "), ("PW_APT_NOBLE", "libasound2t64")):
            body = re.search(rf"^{arr}=\((.*?)^\)", text, re.M | re.S).group(1)
            self.assertIn(needle, body)
            self.assertIn("libnss3", body)
            self.assertNotIn("$", body)  # solo literales: nada de expansiones ni salida de código


class DoctorTests(Base):
    def run_doctor(self, *args, path=None):
        extra = {"PATH": path} if path else {}
        return subprocess.run(
            [BASH, str(DOCTOR), *args], env=self.env(**extra), cwd=self.tmp,
            capture_output=True, text=True, timeout=60,
        )

    def pi_env(self, version="0.87.1", head=EXT_COMMIT, ext=True, link=True):
        """PATH con pi y git simulados, y (opcionalmente) extensión y enlace estable en HOME."""
        d = self.tmp / "pibin"
        d.mkdir(exist_ok=True)
        for name, body in (("pi", f'echo "{version}"\n'), ("git", f'echo "{head}"\n')):
            p = d / name
            p.write_text("#!/bin/sh\n" + body)
            p.chmod(0o755)
        extdir = self.home / ".local/share/agent-server-bootstrap/extensions/pi-selection-editor"
        if ext:
            extdir.mkdir(parents=True)
            if link:
                stable = self.home / ".local/share/pi-selection-editor"
                stable.symlink_to(extdir)
        return f"{d}:{self.mock}:/usr/bin:/bin"

    def run_pi_doctor(self, **kw):
        return self.run_doctor("--modules", "agents", "--with-pi", path=self.pi_env(**kw))

    def test_with_pi_checks_version_extension_commit_and_stable_link(self):
        r = self.run_pi_doctor()
        self.assertRegex(r.stdout, r"ok\s+pi \(")
        self.assertRegex(r.stdout, r"ok\s+pi 0\.87\.1 compatible")
        self.assertRegex(r.stdout, r"ok\s+extensión pi-selection-editor")
        self.assertIn(EXT_COMMIT, r.stdout)
        self.assertRegex(r.stdout, r"ok\s+enlace estable")
        self.assertIn("/selection-editor status", r.stdout)
        self.assertNotRegex(r.stdout, r"FALLO\s+(pi|extensión|el enlace)")

    def test_with_pi_reports_incompatible_pi_wrong_commit_and_missing_pieces(self):
        for kw, pattern in (
            ({"version": "0.87.0"}, r"FALLO\s+pi 0\.87\.0 no es compatible"),
            ({"version": "0.88.1"}, r"FALLO\s+pi 0\.88\.1 no es compatible"),
            ({"head": "deadbeef"}, r"FALLO\s+extensión .*deadbeef"),
            ({"link": False}, r"FALLO\s+el enlace estable"),
            ({"ext": False}, r"FALLO\s+extensión pi-selection-editor no encontrada"),
        ):
            with self.subTest(**kw):
                shutil.rmtree(self.home, ignore_errors=True)
                self.home.mkdir()
                r = self.run_pi_doctor(**kw)
                self.assertEqual(r.returncode, 1)
                self.assertRegex(r.stdout, pattern)

    def test_without_with_pi_no_extension_checks(self):
        r = self.run_doctor("--modules", "agents")
        self.assertNotIn("pi-selection-editor", r.stdout)

    def test_wrangler_missing_is_reported_in_cloud_module(self):
        r = self.run_doctor("--modules", "cloud")
        self.assertRegex(r.stdout, r"(?m)^FALTA\s+wrangler$")

    def test_wrangler_version_reported_without_login(self):
        d = self.tmp / "wbin"
        d.mkdir()
        w = d / "wrangler"
        w.write_text('#!/bin/sh\necho "wrangler-fake $*" >> "$MOCK_LOG"\necho "4.0.0"\n')
        w.chmod(0o755)
        r = self.run_doctor("--modules", "cloud", "--versions", path=f"{d}:{self.mock}:/usr/bin:/bin")
        self.assertRegex(r.stdout, r"ok\s+wrangler \(")
        self.assertRegex(r.stdout, r"(?m)^wrangler\s+4\.0\.0$")
        calls = [c for c in self.log.read_text().splitlines() if c.startswith("wrangler-fake")]
        self.assertEqual(calls, ["wrangler-fake --version"])

    def test_linear_missing_is_reported_in_cloud_module(self):
        r = self.run_doctor("--modules", "cloud")
        self.assertRegex(r.stdout, r"(?m)^FALTA\s+linear$")

    def test_linear_version_reported_without_any_auth_call(self):
        d = self.tmp / "lbin"
        d.mkdir()
        p = d / "linear"
        p.write_text('#!/bin/sh\necho "linear-fake $*" >> "$MOCK_LOG"\necho "3.0.0"\n')
        p.chmod(0o755)
        r = self.run_doctor("--modules", "cloud", "--versions", path=f"{d}:{self.mock}:/usr/bin:/bin")
        self.assertRegex(r.stdout, r"ok\s+linear \(")
        self.assertRegex(r.stdout, r"(?m)^linear\s+3\.0\.0$")
        calls = [c for c in self.log.read_text().splitlines() if c.startswith("linear-fake")]
        self.assertEqual(calls, ["linear-fake --version"])

    def test_tailscale_missing_is_reported(self):
        r = self.run_doctor("--modules", "tailscale")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"(?m)^FALTA\s+tailscale$")

    def test_tailscale_checked_by_existence_and_version_subcommand_only(self):
        d = self.tmp / "tsbin"
        d.mkdir()
        for name in ("tailscale", "tailscaled"):
            p = d / name
            p.write_text('#!/bin/sh\necho "ts-fake ' + name + ' $*" >> "$MOCK_LOG"\necho "1.2.3"\n')
            p.chmod(0o755)
        r = self.run_doctor("--modules", "tailscale", "--versions", path=f"{d}:{self.mock}:/usr/bin:/bin")
        self.assertRegex(r.stdout, r"ok\s+tailscale \(")
        self.assertRegex(r.stdout, r"ok\s+tailscaled \(")
        self.assertRegex(r.stdout, r"(?m)^tailscale\s+1\.2\.3$")
        self.assertNotRegex(r.stdout, r"FALLO\s+tailscale")
        # Los mocks prohibidos (git, npm…) también registran sus llamadas: solo importan las de Tailscale.
        ts_calls = [c for c in self.log.read_text().splitlines() if c.startswith("ts-fake")]
        self.assertEqual(ts_calls, ["ts-fake tailscale version"])

    def test_default_modules_include_tailscale(self):
        r = self.run_doctor()
        self.assertRegex(r.stdout, r"(?m)^FALTA\s+tailscale$")

    def test_empty_modules_rejected(self):
        for value in ("", ",", " , "):
            with self.subTest(value=value):
                self.assertEqual(self.run_doctor("--modules", value).returncode, 2)

    def test_modules_are_not_glob_expanded(self):
        (self.tmp / "base").write_text("")
        r = self.run_doctor("--modules", "ba*")
        self.assertEqual(r.returncode, 2)
        self.assertIn("módulo desconocido", r.stderr)

    def test_with_pi_requires_agents(self):
        r = self.run_doctor("--with-pi", "--modules", "base")
        self.assertEqual(r.returncode, 2)
        self.assertIn("agents", r.stderr)

    def test_versions_reports_broken_executable_as_failure(self):
        # El `git` simulado existe pero siempre sale con 97 (dependencias rotas).
        bin2 = self.tmp / "okbin"
        bin2.mkdir()
        jq = bin2 / "jq"
        jq.write_text('#!/bin/sh\necho "jq-1.7"\n')
        jq.chmod(0o755)
        r = self.run_doctor("--modules", "docker", "--versions", path=f"{bin2}:{self.mock}:/usr/bin:/bin")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FALLO\s+git\s+existe pero")
        self.assertIn("97", r.stdout)
        self.assertRegex(r.stdout, r"(?m)^jq\s+jq-1\.7$")
        self.assertNotRegex(r.stdout, r"(?m)^git\s")

    def test_existence_check_is_separate_from_version(self):
        r = self.run_doctor("--modules", "base", "--versions")
        # git existe (aunque su --version falle): la comprobación de existencia dice ok.
        self.assertRegex(r.stdout, r"ok\s+git \(")
        self.assertRegex(r.stdout, r"FALLO\s+git\s+existe pero")

    def test_help_and_unknown_arg(self):
        self.assertEqual(self.run_doctor("--help").returncode, 0)
        self.assertEqual(self.run_doctor("--nope").returncode, 2)

    def test_fails_when_commands_missing(self):
        r = self.run_doctor("--modules", "cloud")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FALTA    vercel", r.stdout)
        self.assertEqual(list(self.home.rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
