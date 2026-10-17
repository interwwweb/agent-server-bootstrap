"""Tests de install.sh con comandos simulados: no instalan nada ni usan la red."""
import os
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
                    for mod in ("base", "node", "python", "agents", "cloud", "remote", "playwright"):
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
        for mod in ("base", "docker"):
            with self.subTest(module=mod):
                self.assertNotIn("crear ", self.run_install("--modules", mod).stdout)

    def test_node_module_plans_pnpm_without_running_npm(self):
        r = self.run_install("--modules", "node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("npm install -g --no-audit --no-fund pnpm", r.stdout)
        self.assert_untouched()

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
        self.assertIn("install-deps chromium", out)


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
  for b in playwright playwright-cli supabase; do
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
        self.assertTrue(installs[0].endswith(" pnpm"))
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
        script = 'SELECTED="playwright"; mod_playwright'
        self.assertEqual(self.sh(script).returncode, 0)
        npm_calls = [c for c in self.calls() if c.startswith("npm ")]
        self.assertEqual(len(npm_calls), 1)
        self.assertIn("@playwright/test @playwright/cli", npm_calls[0])
        self.assertTrue(any("install-deps chromium" in c for c in self.calls()))
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


class DoctorTests(Base):
    def run_doctor(self, *args, path=None):
        extra = {"PATH": path} if path else {}
        return subprocess.run(
            [BASH, str(DOCTOR), *args], env=self.env(**extra), cwd=self.tmp,
            capture_output=True, text=True, timeout=60,
        )

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
