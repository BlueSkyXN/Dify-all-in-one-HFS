import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"
DIFY_VERSION = "1.17.0"


def run_entrypoint_function(script: str, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{ENTRYPOINT}"\n{script}'],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


class PostgresRuntimeFallbackTests(unittest.TestCase):
    def test_recreates_stale_runtime_postgres_without_touching_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_root = root / "runtime"
            runtime_postgres = runtime_root / "postgres"
            persist_root = root / "persist"
            persist_postgres = persist_root / "postgres"

            runtime_postgres.mkdir(parents=True)
            (runtime_postgres / "PG_VERSION").write_text("15\n", encoding="utf-8")
            (runtime_postgres / "stale-wal").write_text("stale\n", encoding="utf-8")
            persist_postgres.mkdir(parents=True)
            sentinel = persist_postgres / "bucket-sentinel"
            sentinel.write_text("keep\n", encoding="utf-8")

            env = os.environ.copy()
            env["RUNTIME_ROOT"] = str(runtime_root)
            env["PERSIST_ROOT"] = str(persist_root)
            result = run_entrypoint_function("recreate_runtime_postgres_fallback_dir", env=env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(runtime_postgres.is_dir())
            self.assertEqual(list(runtime_postgres.iterdir()), [])
            self.assertEqual(runtime_postgres.stat().st_mode & 0o777, 0o700)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_rejects_runtime_postgres_inside_persist_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_root = Path(tmpdir) / "persist"
            runtime_root = persist_root / "runtime"
            runtime_postgres = runtime_root / "postgres"
            runtime_postgres.mkdir(parents=True)
            sentinel = runtime_postgres / "must-not-delete"
            sentinel.write_text("keep\n", encoding="utf-8")

            env = os.environ.copy()
            env["RUNTIME_ROOT"] = str(runtime_root)
            env["PERSIST_ROOT"] = str(persist_root)
            result = run_entrypoint_function("recreate_runtime_postgres_fallback_dir", env=env)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlaps persistent storage", result.stdout + result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_rejects_symlink_runtime_postgres_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_root = root / "runtime"
            persist_root = root / "persist"
            persist_postgres = persist_root / "postgres"
            runtime_root.mkdir(parents=True)
            persist_postgres.mkdir(parents=True)
            sentinel = persist_postgres / "must-not-delete"
            sentinel.write_text("keep\n", encoding="utf-8")
            (runtime_root / "postgres").symlink_to(persist_postgres, target_is_directory=True)

            env = os.environ.copy()
            env["RUNTIME_ROOT"] = str(runtime_root)
            env["PERSIST_ROOT"] = str(persist_root)
            result = run_entrypoint_function("recreate_runtime_postgres_fallback_dir", env=env)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not be a symlink", result.stdout + result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")


class ArtifactRuntimeMetadataTests(unittest.TestCase):
    def test_binds_dify_version_from_validated_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            api_root = runtime_root / "app/api"
            api_root.mkdir(parents=True)
            (api_root / "pyproject.toml").write_text(
                f'[project]\nname = "dify-api"\nversion = "{DIFY_VERSION}"\n',
                encoding="utf-8",
            )
            (runtime_root / "runtime-lock.json").write_text(
                '{"dify_version":"1.17.0"}\n', encoding="utf-8"
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT / "docker")
            result = run_entrypoint_function(
                f'bind_artifact_runtime_metadata "{runtime_root}"\nprintf "%s\\n" "$DIFY_VERSION"',
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), DIFY_VERSION)


if __name__ == "__main__":
    unittest.main()
