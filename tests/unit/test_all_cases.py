"""Регрессия по всем кейсам в projects/: строгая валидация и воспроизводимость каждого расчёта C-xxx."""
import json
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = sorted(p.parent for p in (ROOT / "projects").glob("*/state.json"))


def _run_expression(command):
    parts = shlex.split(command)
    assert parts[0] in ("python", "python3") and parts[1] == "-c", f"неподдерживаемая команда: {command}"
    result = subprocess.run([sys.executable, "-I", "-c", parts[2]], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class AllCasesTests(unittest.TestCase):
    def test_cases_found(self):
        names = {case.name for case in CASES}
        self.assertTrue({"demo_mvp", "eval_b2b_roaming", "connect_family_devices"} <= names, names)

    def test_every_case_passes_strict_validation(self):
        for case in CASES:
            with self.subTest(case=case.name):
                result = subprocess.run([sys.executable, str(ROOT / "tools" / "schema_validator.py"),
                                         "--case", str(case), "--strict"], capture_output=True, text=True, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_calculation_is_reproducible(self):
        checked = 0
        for case in CASES:
            graph = json.loads((case / "evidence" / "evidence_graph.json").read_text(encoding="utf-8"))
            for calc in graph["calculations"]:
                with self.subTest(case=case.name, calculation=calc["id"]):
                    output = _run_expression(calc["reproduce_command"])
                    expected = calc["result_value"]
                    if isinstance(expected, (int, float)):
                        self.assertAlmostEqual(float(output), float(expected), places=6)
                    else:
                        self.assertEqual(output, str(expected))
                    checked += 1
        self.assertGreater(checked, 20)

    def test_dashboard_has_no_hardcoded_cost_in_rubles(self):
        # Регрессия: раньше рядом с любой стоимостью выводилось выдуманное «~9.5 руб.»
        for case in CASES:
            dashboard = case / "outputs" / "dashboard.html"
            if dashboard.exists():
                with self.subTest(case=case.name):
                    self.assertNotIn("руб.)", dashboard.read_text(encoding="utf-8").split("Стоимость по журналу")[-1][:200])
                    self.assertNotIn("9.5 руб", dashboard.read_text(encoding="utf-8"))

    def test_sources_with_hash_match_files(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import schema_validator as validator
        for case in CASES:
            graph = json.loads((case / "evidence" / "evidence_graph.json").read_text(encoding="utf-8"))
            for source in graph["sources"]:
                if source.get("content_hash") and not source["location"].startswith("http"):
                    # пути источников записаны либо от корня репозитория, либо от папки кейса
                    path = ROOT / source["location"]
                    if not path.exists():
                        path = case / source["location"]
                    with self.subTest(case=case.name, source=source["id"]):
                        digest = validator.artifact_sha256(path)
                        digest = digest if digest.startswith("sha256:") else "sha256:" + digest
                        self.assertEqual(digest, source["content_hash"])


if __name__ == "__main__":
    unittest.main()
