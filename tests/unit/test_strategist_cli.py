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
import copy
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))
import schema_validator as sv  # noqa: E402
import strategist_cli as cli  # noqa: E402
from test_schemas import valid_decision, valid_evidence, valid_state  # noqa: E402


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

    def test_07_render_outputs_metadata_driven_disclaimers(self):
        # 1. Чистый (несинтетический) кейс: не должен содержать упоминаний S-004, F-004, P-001 или Gemini/Claude
        clean_case = self.tmp / "clean_case"
        cli.init_case(
            clean_case,
            raw_request="Оптимизация B2B тарифов",
            clarified_problem="Снижение маржинальности тарифа Про",
            goal="Разработать обновленную линейку",
            recipient="CPO B2B",
        )
        src_dir = clean_case / "sources"
        src_file = src_dir / "clean_report.csv"
        src_file.write_text("a,b\n1,2\n", encoding="utf-8")
        src_hash = "sha256:" + sv.artifact_sha256(src_file)

        ev = {
            "case_id": "clean_case",
            "created_at": "2026-11-10T10:00:00Z",
            "updated_at": "2026-11-10T10:00:00Z",
            "research_questions": [],
            "sources": [
                {
                    "id": "S-101",
                    "title": "Реальный отчёт продаж",
                    "source_type": "csv_table",
                    "location": "sources/clean_report.csv",
                    "content_hash": src_hash,
                    "verification_level": "verified_fact",
                    "trust_boundary": "internal_trusted",
                    "notes": "Официальная выгрузка биллинга",
                }
            ],
            "findings": [
                {
                    "id": "F-101",
                    "statement": "Маржинальность упала на 4%",
                    "source_refs": ["S-101"],
                    "exact_locator": "line 2",
                    "validity_status": "valid",
                }
            ],
            "calculations": [],
            "hypotheses": [],
            "contradictions": [],
            "knowledge_gaps": [],
        }
        cli.write_json(clean_case / sv.CASE_FILES["evidence"], ev)

        dec = valid_decision()
        dec["case_id"] = "clean_case"
        dec["alternatives"][0]["supporting_refs"] = ["F-101"]
        dec["product_strategy"]["selected_option_id"] = "O-001"
        dec["product_strategy"]["evidence_refs"] = ["F-101"]
        dec["product_strategy"]["key_capabilities"] = [
            {"id": "CAP-101", "description": "Автоматический пересчёт лимитов"}
        ]
        dec["product_strategy"]["assumptions_and_limits"] = []
        dec["communication_strategy"]["proof_points"] = [
            {
                "promise": "Автоматизация расчёта экономит время",
                "product_capability_ref": "CAP-101",
                "evidence_refs": ["F-101"],
            }
        ]
        dec["communication_strategy"]["consistency_check"]["explanation"] = "Обещание опирается на свойство CAP-101"
        cli.write_json(clean_case / sv.CASE_FILES["decision"], dec)

        cli.render_outputs(clean_case)
        out01 = (clean_case / "outputs" / "01_research_and_evidence.md").read_text(encoding="utf-8")
        out02 = (clean_case / "outputs" / "02_alternatives_comparison.md").read_text(encoding="utf-8")
        out03 = (clean_case / "outputs" / "03_product_and_comm_strategy.md").read_text(encoding="utf-8")
        out04 = (clean_case / "outputs" / "04_validation_plan_and_governance.md").read_text(encoding="utf-8")

        for doc in (out01, out02, out03, out04):
            self.assertNotIn("Synthetic Benchmark", doc)
            self.assertNotIn("Смоделированные данные", doc)
            self.assertNotIn("S-004", doc)
            self.assertNotIn("F-004", doc)
            self.assertNotIn("P-001", doc)
            self.assertNotIn("Gemini/Claude", doc)
            self.assertNotIn("калиброваны по контрольным прогонам", doc)

        self.assertIn("CAP-101", out03)
        self.assertIn("F-101", out03)

        # 2. Отрицание в notes и синтетика в названии темы не должны ошибочно классифицироваться
        ev_neg = copy.deepcopy(ev)
        ev_neg["sources"][0]["notes"] = "Синтетические данные не использовались в исследовании"
        ev_neg["sources"][0]["title"] = "Аналитический обзор рынка синтетических медиа и ИИ-аватаров"
        ev_neg["sources"][0]["is_synthetic"] = False
        cli.write_json(clean_case / sv.CASE_FILES["evidence"], ev_neg)
        cli.render_outputs(clean_case)
        neg_out01 = (clean_case / "outputs" / "01_research_and_evidence.md").read_text(encoding="utf-8")
        self.assertNotIn("Synthetic Benchmark", neg_out01)
        self.assertNotIn("Смоделированные данные", neg_out01)

        # 3. Реальный кейс + одна гипотеза с синтетическим респондентом (H-201)
        # Должен маркировать ТОЛЬКО H-201 и НЕ объявлять весь кейс учебным или соревновательным MVP
        ev_mixed = copy.deepcopy(ev)
        ev_mixed["hypotheses"] = [
            {
                "id": "H-201",
                "statement": "Семейный пакет увеличит LTV",
                "kind": "synthetic_insight",
                "is_synthetic_respondent": True,
                "depends_on": ["F-101"],
                "confidence": "low",
                "verification_method": "Пилот",
                "validity_status": "valid",
            }
        ]
        cli.write_json(clean_case / sv.CASE_FILES["evidence"], ev_mixed)
        cli.render_outputs(clean_case)
        mixed_out01 = (clean_case / "outputs" / "01_research_and_evidence.md").read_text(encoding="utf-8")
        self.assertIn("Исследование содержит смоделированные данные", mixed_out01)
        self.assertIn("H-201", mixed_out01)
        self.assertNotIn("Synthetic Benchmark", mixed_out01)
        self.assertNotIn("соревновательного MVP", mixed_out01)
        self.assertNotIn("МегаФона", mixed_out01)

        # 4. Проверка различия существующих и проектируемых свойств продукта (Issue C1)
        dec_caps = copy.deepcopy(dec)
        dec_caps["product_strategy"]["key_capabilities"] = [
            {"id": "CAP-101", "description": "Существующий биллинг", "status": "existing"},
            {"id": "CAP-102", "description": "Проектируемый push-дайджест", "status": "planned"},
        ]
        dec_caps["communication_strategy"]["proof_points"][0]["product_capability_ref"] = "CAP-101"
        cli.write_json(clean_case / sv.CASE_FILES["decision"], dec_caps)
        cli.render_outputs(clean_case)
        caps_out03 = (clean_case / "outputs" / "03_product_and_comm_strategy.md").read_text(encoding="utf-8")
        self.assertIn("Подтверждённые возможности (CAP-101) сочетаются с проектируемыми доработками (CAP-102)", caps_out03)

        # 5. Проверка журнала затрат: фактологическое разделение точных и оценочных записей (Issue C2)
        st_ledger = copy.deepcopy(valid_state())
        st_ledger["case_id"] = "clean_case"
        st_ledger["cost_and_usage_ledger"]["entries"] = [
            {
                "step_id": "STEP-01",
                "timestamp": "2026-11-10T10:00:00Z",
                "actor_or_tool": "data-engine",
                "model_tier": "none",
                "duration_sec": 1.5,
                "tokens_in": 0,
                "tokens_out": 0,
                "estimated_cost_usd": 0.0,
                "is_estimated": False,
            },
            {
                "step_id": "STEP-02",
                "timestamp": "2026-11-10T10:01:00Z",
                "actor_or_tool": "llm-strategist",
                "model_tier": "standard",
                "duration_sec": 4.2,
                "tokens_in": 1200,
                "tokens_out": 450,
                "estimated_cost_usd": 0.015,
                "is_estimated": True,
            },
        ]
        st_ledger["cost_and_usage_ledger"]["totals"] = {
            "total_duration_sec": 5.7,
            "total_tokens": 1650,
            "total_estimated_cost_usd": 0.015,
        }
        cli.write_json(clean_case / sv.CASE_FILES["state"], st_ledger)
        cli.render_outputs(clean_case)
        ledger_out04 = (clean_case / "outputs" / "04_validation_plan_and_governance.md").read_text(encoding="utf-8")
        self.assertIn("Журнал содержит как прямые измерения (1 оп.), так и расчётные оценки (1 оп.).", ledger_out04)
        self.assertNotIn("калиброваны по контрольным прогонам", ledger_out04)

        # 6. Полностью учебный демонстрационный кейс (demo_mvp)
        demo_out01 = (ROOT / "projects" / "demo_mvp" / "outputs" / "01_research_and_evidence.md").read_text(encoding="utf-8")
        demo_out03 = (ROOT / "projects" / "demo_mvp" / "outputs" / "03_product_and_comm_strategy.md").read_text(encoding="utf-8")
        self.assertIn("Synthetic Benchmark", demo_out01)
        self.assertIn("S-004", demo_out01)
        self.assertIn("Synthetic Benchmark", demo_out03)
        self.assertIn("P-001", demo_out03)


if __name__ == "__main__":
    unittest.main()
