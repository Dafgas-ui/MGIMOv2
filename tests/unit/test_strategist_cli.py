"""Модульные и интеграционные тесты единого CLI-инструмента tools/strategist_cli.py (TASK-002).

Проверяет:
  1. init-case -> создание структуры папок и валидных по схемам JSON-реестров.
  2. upsert-node -> добавление источников, фактов, расчётов, гипотез, противоречий и пробелов,
     а также автокаскад при смене content_hash источника.
  3. analyze-csv -> подсчёт пропусков (T04), статистик, конверсий (T02) и обнаружение
     методологического конфликта знаменателей/периодов между двумя таблицами (T03).
  4. advance-stage -> переходы между этапами и блокировку входа в INDEPENDENT_REVIEW / HUMAN_DECISION
     при нарушении бизнес-инвариантов.
  5. log-usage и восстановление -> идемпотентную запись без дублирования при сбое (T09) и
     автоматический пересчёт totals (T11).
  6. render-outputs и status/resume -> генерацию 4 Markdown-витрин в outputs/ (ADR-005) и
     сверку SHA-256 контрольных сумм (T07).
  7. invalidate-source -> транзитивный каскад T08 по цепочке S -> F -> C -> H и автоматический
     перевод strategy_decision.json в needs_reassessment с заполнением affected_by_stale_nodes.
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import schema_validator as sv  # noqa: E402
import strategist_cli as cli  # noqa: E402
from test_schemas import valid_decision, valid_evidence  # noqa: E402


class StrategistCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.case = self.tmp / "demo_mvp"
        src_dir = self.case / "sources"
        src_dir.mkdir(parents=True, exist_ok=True)
        self.s1 = src_dir / "cohorts_q3_2026.csv"
        self.s1.write_text("cohorts data\n", encoding="utf-8")
        self.s2 = src_dir / "market_report.md"
        self.s2.write_text("market report\n", encoding="utf-8")

    def test_01_init_case_creates_valid_structure(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "init-case",
                "--case", str(self.case),
                "--raw-request", "Почему падает удержание подписчиков?",
                "--clarified-problem", "Отток 76% новых платящих подписчиков в первые 30 дней",
                "--goal", "Выбрать стратегию снижения раннего оттока",
                "--recipient", "Руководитель продукта",
                "--constraint", "Срок внедрения 1 спринт",
            ])
        self.assertEqual(rc, 0)
        for sub in ("sources", "evidence", "decisions", "outputs"):
            self.assertTrue((self.case / sub).is_dir())
        self.assertEqual(sv.errors_of(sv.validate_case(self.case)), [])

        status = cli.get_case_status(self.case)
        self.assertEqual(status["current_stage"], "INTAKE")
        self.assertTrue(status["artifacts_integrity_ok"])
        self.assertEqual(status["validation_status"], "PASS")

    def test_02_analyze_csv_detects_missing_values_and_denominator_conflict(self):
        csv1 = self.tmp / "billing_cohorts.csv"
        csv2 = self.tmp / "marketing_report.csv"
        csv1.write_text(
            "cohort,retained_d30,new_paying_users,arpu\n"
            "2026-07,240,1000,500\n"
            "2026-08,250,1000,\n"
            "2026-09,230,1000,520\n",
            encoding="utf-8",
        )
        csv2.write_text(
            "cohort,active_d30,all_free_signups\n"
            "2026-07,410,1000\n"
            "2026-08,400,1000\n"
            "2026-09,420,1000\n",
            encoding="utf-8",
        )
        report = cli.analyze_csv(
            csv1,
            compare_file=csv2,
            numerator_col="retained_d30",
            denominator_col="new_paying_users",
            compare_numerator_col="active_d30",
            compare_denominator_col="all_free_signups",
            denominator_label="Новые платящие пользователи",
            compare_denominator_label="Все бесплатные регистрации",
            period="2026-Q3",
            compare_period="2026-Q3",
            unit="percent",
            compare_unit="percent",
        )
        # T04: пропуск в колонке arpu зафиксирован
        self.assertEqual(report["primary"]["columns"]["arpu"]["missing_count"], 1)
        self.assertTrue(any("arpu" in a for a in report["primary"]["missing_data_alerts"]))
        # T02: агрегированная доля посчитана точно (720 / 3000 = 24%)
        self.assertAlmostEqual(report["primary"]["ratio_analysis"]["aggregated_percent"], 24.0)
        self.assertAlmostEqual(report["comparison"]["ratio_analysis"]["aggregated_percent"], 41.0)
        # T03: конфликт определения знаменателя пойман детерминированно
        conflict_codes = {c["code"] for c in report["conflicts"]}
        self.assertIn("METRIC_DEFINITION_CONFLICT", conflict_codes)

    def test_03_upsert_node_and_hash_change_cascade(self):
        cli.init_case(
            self.case,
            raw_request="Запрос",
            clarified_problem="Проблема",
            goal="Цель",
            recipient="Получатель",
        )
        ev = valid_evidence()
        for s in ev["sources"]:
            cli.upsert_node(self.case, "sources", s)
        for f in ev["findings"]:
            cli.upsert_node(self.case, "findings", f)
        for c in ev["calculations"]:
            cli.upsert_node(self.case, "calculations", c)
        for h in ev["hypotheses"]:
            cli.upsert_node(self.case, "hypotheses", h)
        for x in ev["contradictions"]:
            cli.upsert_node(self.case, "contradictions", x)
        for g in ev["knowledge_gaps"]:
            cli.upsert_node(self.case, "knowledge_gaps", g)
        for q in ev["research_questions"]:
            cli.upsert_node(self.case, "research_questions", q)

        self.assertEqual(sv.errors_of(sv.validate_case(self.case)), [])

        # Обновление S-001 с новым content_hash автоматически каскадирует F-001 -> C-001 -> H-001
        updated_s1 = dict(ev["sources"][0], content_hash="sha256:" + "b" * 64, version="2026-10-15")
        res = cli.upsert_node(self.case, "sources", updated_s1)
        self.assertIn("C-001", res["cascade_updated_nodes"])
        self.assertIn("H-001", res["cascade_updated_nodes"])
        self.assertEqual(sv.errors_of(sv.validate_case(self.case)), [])

    def test_04_t08_invalidate_source_cascades_to_graph_and_approved_decision(self):
        cli.init_case(
            self.case,
            raw_request="Запрос",
            clarified_problem="Проблема",
            goal="Цель",
            recipient="Получатель",
        )
        ev = valid_evidence()
        ev["sources"][0]["content_hash"] = "sha256:" + sv.artifact_sha256(self.s1)
        cli.write_json(self.case / sv.CASE_FILES["evidence"], ev)
        cli.write_json(self.case / sv.CASE_FILES["decision"], valid_decision())
        cli.advance_stage(self.case, "DECISION_MONITORING", note="Решение утверждено")
        cli.refresh_artifacts_integrity(self.case)
        self.assertEqual(sv.errors_of(sv.validate_case(self.case)), [])

        # Отзываем источник S-001 через CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "invalidate-source",
                "--case", str(self.case),
                "--node-id", "S-001",
                "--status", "revoked",
                "--reason", "Обнаружена ошибка выгрузки биллинга за август",
                "--json",
            ])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload["cascade_updated_nodes"]), {"F-001", "C-001", "H-001"})
        self.assertTrue(payload["decision_status_changed"])
        self.assertEqual(set(payload["affected_decision_refs"]), {"F-001", "C-001", "H-001"})

        # Проверяем, что кейс остаётся консистентным (все зависимые узлы и решение в needs_reassessment)
        self.assertEqual(sv.errors_of(sv.validate_case(self.case)), [])
        dec = sv.load_json(self.case / sv.CASE_FILES["decision"])
        self.assertEqual(dec["decision_status"], "needs_reassessment")
        self.assertEqual(
            set(dec["decision_support_and_reassessment"]["affected_by_stale_nodes"]),
            {"F-001", "C-001", "H-001"},
        )

    def test_05_t09_t11_log_usage_idempotency_and_in_progress_recovery(self):
        cli.init_case(
            self.case,
            raw_request="Запрос",
            clarified_problem="Проблема",
            goal="Цель",
            recipient="Получатель",
        )
        cli.start_operation(self.case, "STEP-HEAVY-01", actor="evidence-harvester", is_paid=True)
        st_mid = cli.get_case_status(self.case)
        self.assertIsNotNone(st_mid["recovery"])
        self.assertEqual(st_mid["recovery"]["operation_id"], "STEP-HEAVY-01")

        # Завершаем операцию через log-usage
        r1 = cli.log_usage(
            self.case,
            step_id="STEP-HEAVY-01",
            actor="evidence-harvester",
            model_tier="standard",
            duration_sec=12.5,
            tokens_in=2000,
            tokens_out=1000,
            cost_usd=0.03,
            is_estimated=True,
        )
        self.assertFalse(r1["skipped_duplicate"])
        self.assertEqual(r1["totals"]["total_tokens"], 3000)

        # Повторный вызов с тем же step_id при возобновлении после сбоя не дублирует расходы (T09)
        r2 = cli.log_usage(
            self.case,
            step_id="STEP-HEAVY-01",
            actor="evidence-harvester",
            model_tier="standard",
            duration_sec=12.5,
            tokens_in=2000,
            tokens_out=1000,
            cost_usd=0.03,
            is_estimated=True,
        )
        self.assertTrue(r2["skipped_duplicate"])
        self.assertEqual(r2["totals"]["total_tokens"], 3000)
        self.assertIsNone(cli.get_case_status(self.case)["recovery"])

    def test_06_advance_stage_blocks_invalid_strategy_and_render_outputs_updates_hashes(self):
        cli.init_case(
            self.case,
            raw_request="Запрос",
            clarified_problem="Проблема",
            goal="Цель",
            recipient="Получатель",
        )
        ev = valid_evidence()
        ev["sources"][0]["content_hash"] = "sha256:" + sv.artifact_sha256(self.s1)
        cli.write_json(self.case / sv.CASE_FILES["evidence"], ev)
        bad_dec = valid_decision()
        bad_dec["communication_strategy"]["consistency_check"]["is_consistent"] = False
        cli.write_json(self.case / sv.CASE_FILES["decision"], bad_dec)

        # Попытка перейти в INDEPENDENT_REVIEW с несогласованной коммуникацией блокируется
        with self.assertRaises(ValueError):
            cli.advance_stage(self.case, "INDEPENDENT_REVIEW")

        # Исправляем решение, переходим в HUMAN_DECISION и рендерим Markdown-отчёты
        cli.write_json(self.case / sv.CASE_FILES["decision"], valid_decision())
        cli.advance_stage(self.case, "HUMAN_DECISION", note="Готово к решению человека")
        rendered = cli.render_outputs(self.case)
        self.assertEqual(len(rendered["rendered_files"]), 4)
        for rel in cli.OUTPUT_FILES:
            p = self.case / rel
            self.assertTrue(p.is_file())
            self.assertGreater(len(p.read_text(encoding="utf-8")), 200)

        # Строгая проверка кейса вместе с контрольными суммами всех 6 артефактов проходит
        self.assertEqual(sv.validate_case(self.case, strict=True), [])


if __name__ == "__main__":
    unittest.main()
