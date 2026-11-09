import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import session_recovery_hook as hook  # noqa: E402
import strategist_cli as sc  # noqa: E402


class SessionRecoveryHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_01_hooks_json_structure_is_valid(self):
        hooks_path = ROOT / ".agents" / "hooks.json"
        self.assertTrue(hooks_path.is_file(), "Файл .agents/hooks.json должен существовать")

        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("session-state-recovery", data)
        cfg = data["session-state-recovery"]
        self.assertTrue(cfg.get("enabled"), "session-state-recovery должен быть enabled=True")
        self.assertIn("SessionStart", cfg)
        self.assertIsInstance(cfg["SessionStart"], list)
        self.assertGreaterEqual(len(cfg["SessionStart"]), 1)

        step = cfg["SessionStart"][0]
        self.assertEqual(step.get("type"), "command")
        self.assertIn("session_recovery_hook.py", step.get("command", ""))
        self.assertGreater(step.get("timeout", 0), 0)

    def test_02_hook_returns_empty_when_no_active_cases(self):
        # 1. Вызов функции на пустом рабочем каталоге
        payload = hook.generate_recovery_payload(root_dir=self.tmp)
        self.assertEqual(payload, {})

        # 2. Subprocess вызов с изолированным кейсом
        hook_script = ROOT / "tools" / "session_recovery_hook.py"
        empty_case = self.tmp / "nonexistent_empty_case"
        res = subprocess.run(
            [sys.executable, str(hook_script), "--test-case", str(empty_case)],
            cwd=str(self.tmp),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(res.returncode, 0)
        out = json.loads(res.stdout)
        self.assertEqual(out, {})

    def test_03_hook_reports_status_and_t08_reassessment_on_initialized_case(self):
        case_dir = self.tmp / "projects" / "test_case_t07"
        sc.init_case(case_dir, "test_case_t07", "Тестовый сегмент", "Проверить гипотезу ценности")

        # Проверяем базовый payload
        payload = hook.generate_recovery_payload(root_dir=self.tmp)
        self.assertIn("injectSteps", payload)
        self.assertEqual(len(payload["injectSteps"]), 1)
        msg_obj = payload["injectSteps"][0].get("systemMessage", {})
        self.assertIn("systemMessage", msg_obj)
        msg = msg_obj["systemMessage"]

        self.assertIn("test_case_t07", msg)
        self.assertIn("Current stage: INTAKE", msg)
        self.assertIn("Artifacts integrity (T07): OK", msg)
        self.assertIn("Awaiting human approval: NO", msg)
        self.assertIn("In-progress operation (T09): NONE", msg)
        self.assertIn("Usage & cost totals (T11):", msg)
        self.assertIn("Resume command:", msg)
        self.assertIn("Needs reassessment / stale nodes (T08): NONE", msg)

        # Добавляем валидный источник и факт, зависящий от источника
        sc.upsert_node(
            case_dir,
            "sources",
            {
                "id": "S-001",
                "title": "Отчёт за Q3 2026",
                "source_type": "spreadsheet",
                "location": "sources/cohorts_q3_2026.csv",
                "trust_boundary": "untrusted_data",
                "verification_level": "content_verified",
                "content_hash": "sha256:" + "a" * 64,
            },
        )
        sc.upsert_node(
            case_dir,
            "findings",
            {
                "id": "F-001",
                "statement": "Удержание 24%",
                "source_refs": ["S-001"],
                "exact_locator": "строка 14, колонка D",
                "validity_status": "valid",
            },
        )

        # Инвалидируем источник S-001 (T08)
        sc.invalidate_source(
            case_dir,
            "S-001",
            status="revoked",
            reason="Данные отчёта признаны недействительными",
        )

        # Проверяем, что хук теперь отражает needs_reassessment / stale nodes
        payload2 = hook.generate_recovery_payload(root_dir=self.tmp)
        msg2 = payload2["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("Needs reassessment / stale nodes (T08):", msg2)
        self.assertTrue("S-001" in msg2 or "F-001" in msg2)

    def test_04_hook_execution_from_agents_directory(self):
        case_dir = self.tmp / "projects" / "test_case_agents_cwd"
        sc.init_case(case_dir, "test_case_agents_cwd", "Сегмент B2B", "Оценить готовность")

        # Имитируем запуск хука из каталога .agents/ с переходом на уровень выше к tools/
        agents_dir = ROOT / ".agents"
        res = subprocess.run(
            [sys.executable, "../tools/session_recovery_hook.py", "--test-case", str(case_dir)],
            cwd=str(agents_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("injectSteps", data)
        msg = data["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("test_case_agents_cwd", msg)
        self.assertIn("INTAKE", msg)
        self.assertIn("T07", msg)


if __name__ == "__main__":
    unittest.main()
