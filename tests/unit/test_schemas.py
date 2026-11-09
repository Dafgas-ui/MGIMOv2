"""Модульные тесты JSON-схем и детерминированного валидатора (TASK-001).

Покрывает:
  - самопроверку schemas/*.schema.json и валидные документы кейса;
  - структурные проверки JSON Schema (required, additionalProperties, enum, const, pattern,
    format, minItems, uniqueItems, minimum, дубли ключей JSON);
  - бизнес-инварианты ТЗ: T01 (постановка задачи), T03 (конфликт определений метрик и знаменателей),
    T05 (альтернативы, status_quo, sunset_or_close, strong_objections), T06 (согласованность
    коммуникации и обещаний), T08 (каскадный пересмотр при устаревании/отзыве источника),
    T09 (безопасное восстановление без повтора платного шага), T11 (итоги журнала затрат),
    а также запрет выдавать ответы синтетических респондентов за доказательство спроса;
  - проверку каталога кейса на диске и CLI-интерфейс tools/schema_validator.py.
"""
import copy
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


def valid_evidence():
    return {
        "case_id": "demo_mvp",
        "schema_version": "1.0",
        "updated_at": "2026-11-09T10:30:00+03:00",
        "research_questions": [
            {
                "id": "Q-001",
                "question": "В каком сегменте сосредоточен отток в первые 30 дней?",
                "decision_impact": "Определяет, чинить ли онбординг или закрывать направление.",
                "status": "answered",
                "answer_refs": ["F-001", "C-001"],
            },
            {
                "id": "Q-002",
                "question": "Какова чувствительность к цене в сегменте семейных подписок?",
                "decision_impact": "Влияет на выбор тарифа.",
                "status": "blocked_by_gap",
                "blocking_gap_refs": ["G-001"],
            },
        ],
        "sources": [
            {
                "id": "S-001",
                "title": "Выгрузка когорт удержания за Q3 2026",
                "source_type": "spreadsheet",
                "location": "sources/cohorts_q3_2026.csv",
                "trust_boundary": "untrusted_data",
                "verification_level": "content_verified",
                "content_hash": "sha256:" + "a" * 64,
                "version": "2026-10-01",
                "retrieved_at": "2026-11-09T10:00:00+03:00",
                "notes": "Открытый учебный набор данных",
            },
            {
                "id": "S-002",
                "title": "Маркетинговый отчёт по рынку",
                "source_type": "document",
                "location": "sources/market_report.md",
                "trust_boundary": "untrusted_data",
                "verification_level": "accessible",
                "content_hash": None,
                "version": "1.0",
                "notes": None,
            },
        ],
        "findings": [
            {
                "id": "F-001",
                "statement": "Удержание 30-го дня среди новых платящих пользователей составляет 24%.",
                "source_refs": ["S-001"],
                "exact_locator": "лист cohorts, строка 14, колонка D",
                "metric_definition": {
                    "metric_name": "Retention D30",
                    "numerator": "Активные платящие пользователи на 30-й день",
                    "denominator": "Новые платящие пользователи когорты",
                    "period": "2026-Q3",
                    "unit": "percent",
                    "value": 24.0,
                },
                "validity_status": "valid",
            },
            {
                "id": "F-002",
                "statement": "В маркетинговом отчёте указано удержание 30-го дня 41% от всех регистраций.",
                "source_refs": ["S-002"],
                "exact_locator": "раздел 2, абзац 3",
                "metric_definition": {
                    "metric_name": "Retention D30",
                    "numerator": "Зашедшие в приложение на 30-й день",
                    "denominator": "Все бесплатные регистрации",
                    "period": "2026-Q3",
                    "unit": "percent",
                    "value": 41.0,
                },
                "validity_status": "valid",
            },
        ],
        "calculations": [
            {
                "id": "C-001",
                "description": "Потери выручки из-за оттока первого месяца",
                "formula": "cohort_size * (1 - retention_d30 / 100) * arpu",
                "depends_on": ["F-001"],
                "result_value": 1520000,
                "unit": "RUB/month",
                "reproduce_command": "python tools/strategist_cli.py calc --case projects/demo_mvp --id C-001",
                "validity_status": "valid",
            }
        ],
        "hypotheses": [
            {
                "id": "H-001",
                "statement": "Упрощение первого экрана сократит отток первого месяца на 5 п.п.",
                "kind": "hypothesis",
                "is_synthetic_respondent": False,
                "depends_on": ["F-001", "C-001"],
                "confidence": "medium",
                "verification_method": "A/B-тест на новых платящих пользователях в течение 4 недель",
                "validity_status": "valid",
            },
            {
                "id": "H-002",
                "statement": "Синтетический респондент путает условия пробного периода.",
                "kind": "synthetic_insight",
                "is_synthetic_respondent": True,
                "depends_on": ["S-002"],
                "confidence": "low",
                "verification_method": "5 глубинных интервью с реальными пользователями",
                "validity_status": "valid",
            },
        ],
        "contradictions": [
            {
                "id": "X-001",
                "description": "Разные значения Retention D30 (24% и 41%) из-за разных знаменателей.",
                "conflicting_refs": ["F-001", "F-002"],
                "resolution_status": "explained_by_methodology",
                "resolution_note": "Для решений по монетизации используем F-001 (платящая когорта).",
            }
        ],
        "knowledge_gaps": [
            {
                "id": "G-001",
                "missing_info": "Распределение причин отмены подписки по данным опроса оттока",
                "why_unknown": "Выгрузка из CRM за Q3 не передана в открытый контур",
                "impact_on_decision": "Без этого нельзя точно выбрать между доработкой онбординга и сменой тарифа",
                "mitigation_or_next_step": "Запустить короткий опрос при отмене подписки на 2 недели",
            }
        ],
    }


def valid_decision():
    return {
        "case_id": "demo_mvp",
        "schema_version": "1.0",
        "updated_at": "2026-11-09T10:35:00+03:00",
        "decision_status": "approved_by_human",
        "alternatives": [
            {
                "id": "O-001",
                "title": "Оставить как есть",
                "option_type": "status_quo",
                "summary": "Сохранить текущий онбординг и тарифную сетку без изменений.",
                "supporting_refs": ["F-001"],
                "strong_objections": ["Продолжается потеря ~1,52 млн руб./мес. на оттоке первого месяца."],
                "expected_economics": "0 руб. затрат на разработку; сохранение текущих потерь C-001.",
                "verdict": "rejected",
            },
            {
                "id": "O-002",
                "title": "Закрыть направление",
                "option_type": "sunset_or_close",
                "summary": "Прекратить привлечение в продукт и перевести команду на смежный сервис.",
                "supporting_refs": ["F-001", "C-001"],
                "strong_objections": ["Потеря действующей платящей базы и репутационные издержки при закрытии."],
                "expected_economics": "Экономия ФОТ и маркетинга, списание выручки продукта.",
                "verdict": "rejected",
            },
            {
                "id": "O-003",
                "title": "Перестроить онбординг первых 7 дней вокруг одной ключевой задачи",
                "option_type": "strategic_direction",
                "summary": "Убрать второстепенные сценарии из первого входа и показать прозрачные условия подписки.",
                "supporting_refs": ["F-001", "C-001", "H-001"],
                "strong_objections": [
                    "Если причина оттока в цене (пробел G-001), редизайн онбординга не даст окупаемости."
                ],
                "expected_economics": "Затраты 1 спринт команды; целевой возврат по C-001 при подтверждении H-001.",
                "verdict": "selected",
            },
        ],
        "product_strategy": {
            "selected_option_id": "O-003",
            "target_audience": "Новые платящие подписчики цифрового сервиса в первые 30 дней",
            "user_job_to_be_done": "Быстро получить первую ощутимую пользу от подписки без чтения инструкций",
            "competing_alternatives": [
                {
                    "name": "Бесплатные разрозненные инструменты и ручные напоминания",
                    "alternative_type": "habitual_free_workaround",
                    "notes": "Привычный бесплатный способ обходиться без подписки",
                },
                {
                    "name": "Прямой конкурент на рынке экосистемных подписок",
                    "alternative_type": "direct_competitor",
                    "notes": None,
                },
            ],
            "chosen_direction": "Фокус на пошаговом запуске одной главной функции в день подключения",
            "key_capabilities": [
                {"id": "P-001", "description": "Пошаговый запуск ключевого сценария за 2 минуты"},
                {"id": "P-002", "description": "Прозрачный экран условий подписки и даты списания"},
            ],
            "explicit_refusals": [
                "Не делаем программу лояльности и кэшбэк в этом квартале",
                "Не обещаем автоматическую экономию без настройки сценария пользователем",
            ],
            "cost_drivers": ["Разработка и тестирование нового потока первого входа (1 спринт)"],
            "revenue_or_value_logic": "Снижение раннего оттока увеличивает LTV платящей когорты",
            "unit_economics_link": "Опирается на F-001 и расчёт потерь C-001.",
            "evidence_refs": ["F-001", "C-001", "H-001"],
            "assumptions_and_limits": [
                {
                    "kind": "hypothesis_basis",
                    "statement": "Величина эффекта (+5 п.п.) является гипотезой H-001 до завершения A/B-теста.",
                    "related_refs": ["H-001"],
                },
                {
                    "kind": "knowledge_gap",
                    "statement": "Точные причины отмены подписки неизвестны (G-001).",
                    "related_refs": ["G-001"],
                },
            ],
        },
        "communication_strategy": {
            "target_audience_and_context": "Новые пользователи в момент первой оплаты и первого входа в сервис",
            "comprehension_or_choice_barrier": "Пользователь не понимает, с чего начать и за что спишутся деньги",
            "key_message": "Настройте главный сценарий за 2 минуты и контролируйте условия подписки на одном экране",
            "proof_points": [
                {
                    "promise": "Запуск за 2 минуты по готовому шаблону",
                    "product_capability_ref": "P-001",
                    "evidence_refs": ["F-001", "H-001"],
                },
                {
                    "promise": "Понятная дата следующего списания и отмена в один экран",
                    "product_capability_ref": "P-002",
                    "evidence_refs": ["F-001"],
                },
            ],
            "channels_and_roles": [
                {"channel": "Экран после оплаты в приложении", "funnel_role": "onboarding", "notes": None},
                {"channel": "Push-уведомление на 3-й день", "funnel_role": "retention", "notes": None},
            ],
            "consistency_check": {
                "is_consistent": True,
                "explanation": "Коммуникация опирается только на P-001 и P-002 и не обещает кэшбэк или автоэкономию.",
            },
        },
        "validation_plan": {
            "expected_change": "Рост Retention D30 платящей когорты с 24% до 29%",
            "primary_metrics": [
                {
                    "metric_name": "Retention D30",
                    "definition": "Доля новых платящих пользователей, активных на 30-й день",
                    "target": ">= 29%",
                    "unit": "percent",
                }
            ],
            "baseline_comparison": "Контрольная группа A/B-теста со старым онбордингом (база 24% по F-001)",
            "observation_period": "35 календарных дней с момента запуска теста",
            "guardrail_and_negative_consequences": [
                {
                    "consequence": "Рост обращений в поддержку из-за изменения привычного экрана",
                    "guardrail_metric": "Доля тикетов по онбордингу",
                    "threshold": "<= +10% к контрольной группе",
                }
            ],
        },
        "decision_support_and_reassessment": {
            "commitments": [
                {
                    "id": "K-001",
                    "owner_role": "Product Manager",
                    "action": "Запустить A/B-тест нового онбординга и опрос причин отмены",
                    "due_date": "2026-11-25",
                    "checkpoint": "Проверка промежуточной конверсии первого шага через 7 дней",
                    "status": "planned",
                }
            ],
            "reassessment_triggers": [
                {
                    "id": "R-001",
                    "condition": "Retention D30 в тестовой группе ниже 26% по итогам 30 дней или обновление S-001",
                    "metric_name": "Retention D30",
                    "threshold": "< 26%",
                    "watched_refs": ["S-001", "F-001", "G-001"],
                }
            ],
            "affected_by_stale_nodes": [],
        },
    }


def valid_state():
    return {
        "case_id": "demo_mvp",
        "schema_version": "1.0",
        "created_at": "2026-11-09T10:00:00+03:00",
        "updated_at": "2026-11-09T10:40:00+03:00",
        "problem_framing": {
            "raw_request": "Падает удержание в сервисе, нужно понять что делать.",
            "clarified_problem": "Низкое удержание 30-го дня (24%) среди новых платящих подписчиков.",
            "goal": "Выбрать и обосновать стратегию снижения раннего оттока на Q4.",
            "decision_recipient": "Руководитель продукта и инвестиционный комитет Фабрики продуктов",
            "constraints": ["Горизонт внедрения — 1 спринт", "Только открытые и собственные данные"],
            "available_data_summary": "Когортная выгрузка S-001 и маркетинговый отчёт S-002.",
            "pending_clarifying_questions": [],
        },
        "workflow": {
            "current_stage": "DECISION_MONITORING",
            "completed_stages": list(sv.STAGES[:-1]),
            "stage_history": [
                {
                    "from_stage": None,
                    "to_stage": "INTAKE",
                    "timestamp": "2026-11-09T10:00:00+03:00",
                    "transition_type": "start",
                    "reason": "Получен исходный запрос",
                },
                {
                    "from_stage": "INTAKE",
                    "to_stage": "HUMAN_DECISION",
                    "timestamp": "2026-11-09T10:30:00+03:00",
                    "transition_type": "forward",
                    "reason": "Стратегия прошла независимое ревью",
                },
                {
                    "from_stage": "HUMAN_DECISION",
                    "to_stage": "DECISION_MONITORING",
                    "timestamp": "2026-11-09T10:40:00+03:00",
                    "transition_type": "forward",
                    "reason": "Руководитель продукта утвердил вариант O-003",
                },
            ],
            "awaiting_human_approval": {"is_awaiting": False, "reason": None},
        },
        "checkpoints_and_recovery": {
            "last_completed_operation_id": "STEP-002",
            "in_progress_operation": None,
            "artifacts_integrity": [],
        },
        "cost_and_usage_ledger": {
            "entries": [
                {
                    "step_id": "STEP-001",
                    "timestamp": "2026-11-09T10:10:00+03:00",
                    "actor_or_tool": "tools/schema_validator.py",
                    "model_tier": "none",
                    "duration_sec": 0.4,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "estimated_cost_usd": 0.0,
                    "is_estimated": False,
                    "notes": "Детерминированная проверка",
                },
                {
                    "step_id": "STEP-002",
                    "timestamp": "2026-11-09T10:25:00+03:00",
                    "actor_or_tool": "strategy-synthesis",
                    "model_tier": "standard",
                    "duration_sec": 14.6,
                    "tokens_in": 3200,
                    "tokens_out": 1800,
                    "estimated_cost_usd": 0.045,
                    "is_estimated": True,
                    "notes": "Синтез вариантов и стратегии",
                },
            ],
            "totals": {
                "total_duration_sec": 15.0,
                "total_tokens": 5000,
                "total_estimated_cost_usd": 0.045,
            },
        },
    }


class SchemaValidatorTest(unittest.TestCase):
    def test_01_schemas_self_check_passes(self):
        self.assertEqual(sv.check_schemas(), [])

    def test_02_valid_documents_pass_without_issues(self):
        issues = sv.validate_documents(valid_state(), valid_evidence(), valid_decision())
        self.assertEqual(issues, [])

    def test_03_schema_structural_constraints(self):
        graph = valid_evidence()
        graph["unexpected_field"] = 123
        graph["sources"][0]["id"] = "SRC-1"
        graph["sources"][0]["trust_boundary"] = "trusted"
        graph["updated_at"] = "2026-11-09 10:30:00"
        del graph["knowledge_gaps"]
        errs = sv.schema_issues(graph, "evidence")
        self.assertEqual(len(errs), 5)
        self.assertTrue(all(e.code == "SCHEMA" for e in errs))

        with self.assertRaises(sv.JsonLoadError):
            sv.parse_json_text('{"a": 1, "a": 2}')

    def test_04_broken_and_wrong_type_references_caught(self):
        graph = valid_evidence()
        graph["findings"][0]["source_refs"] = ["S-999"]
        graph["calculations"][0]["depends_on"] = ["S-001"]  # расчёт может зависеть только от F/C
        c = sv.codes(sv.validate_evidence_graph(graph))
        self.assertIn("REF_MISSING", c)
        self.assertIn("REF_WRONG_TYPE", c)

    def test_05_t03_conflicting_metric_denominators_require_contradiction(self):
        graph = valid_evidence()
        graph["contradictions"] = []
        self.assertIn("T03_UNRECORDED_METRIC_CONFLICT", sv.codes(sv.validate_evidence_graph(graph)))

        graph["contradictions"] = [
            {
                "id": "X-001",
                "description": "Разные знаменатели",
                "conflicting_refs": ["F-001", "F-002"],
                "resolution_status": "resolved",
                "resolution_note": "",
            }
        ]
        c = sv.codes(sv.validate_evidence_graph(graph))
        self.assertNotIn("T03_UNRECORDED_METRIC_CONFLICT", c)
        self.assertIn("CONTRADICTION_NOTE_MISSING", c)

    def test_06_t08_cascade_stale_propagation_Across_graph_and_decision(self):
        graph = valid_evidence()
        decision = valid_decision()
        graph["sources"][0]["verification_level"] = "revoked"
        # F-001 -> C-001 -> H-001 все ещё valid, а решение approved_by_human
        c = sv.codes(sv.validate_documents(valid_state(), graph, decision))
        self.assertIn("T08_STALE_DEPENDENCY", c)
        self.assertIn("T08_STALE_DECISION", c)
        self.assertIn("T08_STALE_NOT_FLAGGED", c)

        # Каскадно переводим зависимые узлы и решение в needs_reassessment
        graph["findings"][0]["validity_status"] = "needs_reassessment"
        graph["calculations"][0]["validity_status"] = "needs_reassessment"
        graph["hypotheses"][0]["validity_status"] = "needs_reassessment"
        decision["decision_status"] = "needs_reassessment"
        decision["decision_support_and_reassessment"]["affected_by_stale_nodes"] = ["F-001", "C-001", "H-001"]
        self.assertEqual(sv.errors_of(sv.validate_documents(valid_state(), graph, decision)), [])

    def test_07_synthetic_respondent_guards(self):
        graph = valid_evidence()
        decision = valid_decision()
        # Выбранная стратегия опирается только на синтетического респондента H-002 без пометки
        decision["product_strategy"]["evidence_refs"] = ["H-002"]
        decision["product_strategy"]["assumptions_and_limits"] = []
        self.assertIn("SYNTHETIC_SOLE_BASIS", sv.codes(sv.validate_decision(decision, graph)))

        # С явной пометкой synthetic_respondent_basis ошибка снимается
        decision["product_strategy"]["assumptions_and_limits"] = [
            {
                "kind": "synthetic_respondent_basis",
                "statement": "Инсайт получен от ИИ-респондента и требует проверки на реальных людях.",
                "related_refs": ["H-002"],
            }
        ]
        self.assertNotIn("SYNTHETIC_SOLE_BASIS", sv.codes(sv.validate_decision(decision, graph)))

        # Синтетический респондент не может иметь высокую уверенность
        graph["hypotheses"][1]["confidence"] = "high"
        self.assertIn("SYNTHETIC_HIGH_CONFIDENCE", sv.codes(sv.validate_evidence_graph(graph)))

        # CORE-01: смешанные ссылки (реальный факт + нераскрытый синтетический респондент)
        graph2 = valid_evidence()
        dec2 = valid_decision()
        dec2["product_strategy"]["evidence_refs"] = ["F-001", "H-002"]
        dec2["product_strategy"]["assumptions_and_limits"] = []
        self.assertIn("SYNTHETIC_UNDISCLOSED_BASIS", sv.codes(sv.validate_decision(dec2, graph2)))

        # CORE-01: proof_point в коммуникационной стратегии не может опираться на синтетического респондента
        dec3 = valid_decision()
        dec3["communication_strategy"]["proof_points"][0]["evidence_refs"] = ["H-002"]
        self.assertIn("SYNTHETIC_PROOF_POINT", sv.codes(sv.validate_decision(dec3, graph2)))

    def test_08_t05_alternatives_business_rules(self):
        graph = valid_evidence()
        # Нет status_quo и sunset_or_close, пустое возражение, менее 3 вариантов
        decision = valid_decision()
        decision["alternatives"] = [
            {
                "id": "O-001",
                "title": "Вариант А",
                "option_type": "strategic_direction",
                "summary": "Описание А",
                "supporting_refs": ["F-001"],
                "strong_objections": [""],
                "expected_economics": "Экономика А",
                "verdict": "selected",
            },
            {
                "id": "O-002",
                "title": "Вариант А",
                "option_type": "strategic_direction",
                "summary": "Описание Б",
                "supporting_refs": ["F-001"],
                "strong_objections": ["Возражение"],
                "expected_economics": "Экономика Б",
                "verdict": "selected",
            },
        ]
        c = sv.codes(sv.validate_decision(decision, graph))
        self.assertIn("T05_MIN_ALTERNATIVES", c)
        self.assertIn("T05_MISSING_STATUS_QUO", c)
        self.assertIn("T05_MISSING_SUNSET", c)
        self.assertIn("T05_NO_OBJECTIONS", c)
        self.assertIn("T05_DUPLICATE_ALTERNATIVE", c)
        self.assertIn("T05_MULTIPLE_SELECTED", c)

    def test_09_t06_communication_consistency_and_capability_links(self):
        graph = valid_evidence()
        decision = valid_decision()
        decision["communication_strategy"]["consistency_check"]["is_consistent"] = False
        decision["communication_strategy"]["proof_points"][0]["product_capability_ref"] = "P-999"
        c = sv.codes(sv.validate_decision(decision, graph))
        self.assertIn("T06_INCONSISTENT_COMMUNICATION", c)
        self.assertIn("T06_UNSUPPORTED_PROMISE", c)

        # CORE-02: обещание в коммуникации противоречит explicit_refusals
        dec2 = valid_decision()
        dec2["communication_strategy"]["proof_points"][0]["promise"] = (
            "Начисляем повышенный кэшбэк по программе лояльности с первого дня"
        )
        self.assertIn("T06_PROMISES_EXPLICIT_REFUSAL", sv.codes(sv.validate_decision(dec2, graph)))

        dec3 = valid_decision()
        dec3["product_strategy"]["explicit_refusals"] = ["   "]
        self.assertIn("T06_EMPTY_EXPLICIT_REFUSAL", sv.codes(sv.validate_decision(dec3, graph)))

    def test_10_t01_t09_t11_state_workflow_recovery_and_cost_ledger(self):
        state = valid_state()
        state["problem_framing"]["goal"] = None
        state["cost_and_usage_ledger"]["totals"]["total_tokens"] = 999
        state["checkpoints_and_recovery"]["in_progress_operation"] = {
            "operation_id": "STEP-002",
            "started_at": "2026-11-09T10:25:00+03:00",
            "actor_or_tool": "strategy-synthesis",
            "idempotency_key": None,
            "is_paid_or_heavy": True,
            "status": "interrupted",
            "resume_hint": "Проверить черновик решения перед повторным вызовом",
            "error": "Timeout",
        }
        c = sv.codes(sv.validate_state(state))
        self.assertIn("T01_FRAMING_INCOMPLETE", c)
        self.assertIn("T11_TOTALS_MISMATCH", c)
        self.assertIn("T09_OPERATION_STATE_CONFLICT", c)
        self.assertIn("T09_OPERATION_ALREADY_LEDGERED", c)
        self.assertIn("T09_NO_IDEMPOTENCY_KEY", sv.codes(sv.validate_state(state), severity="WARNING"))

    def test_11_calculation_dependency_cycle_caught(self):
        graph = valid_evidence()
        graph["calculations"] = [
            {
                "id": "C-001",
                "description": "Расчёт 1",
                "formula": "C-002 + 1",
                "depends_on": ["C-002"],
                "result_value": 10,
                "unit": "RUB",
                "reproduce_command": "echo 10",
                "validity_status": "valid",
            },
            {
                "id": "C-002",
                "description": "Расчёт 2",
                "formula": "C-001 + 1",
                "depends_on": ["C-001"],
                "result_value": 11,
                "unit": "RUB",
                "reproduce_command": "echo 11",
                "validity_status": "valid",
            },
        ]
        self.assertIn("DEPENDENCY_CYCLE", sv.codes(sv.validate_evidence_graph(graph)))

    def test_12_case_directory_integrity_and_cli(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        case = tmp / "demo_mvp"
        (case / "evidence").mkdir(parents=True)
        (case / "decisions").mkdir(parents=True)

        ev_path = case / "evidence" / "evidence_graph.json"
        dec_path = case / "decisions" / "strategy_decision.json"
        st_path = case / "state.json"

        ev_path.write_text(json.dumps(valid_evidence(), ensure_ascii=False, indent=2), encoding="utf-8")
        dec_path.write_text(json.dumps(valid_decision(), ensure_ascii=False, indent=2), encoding="utf-8")

        state = copy.deepcopy(valid_state())
        state["checkpoints_and_recovery"]["artifacts_integrity"] = [
            {
                "path": "evidence/evidence_graph.json",
                "sha256": sv.artifact_sha256(ev_path),
                "recorded_at": "2026-11-09T10:35:00+03:00",
            },
            {
                "path": "decisions/strategy_decision.json",
                "sha256": sv.artifact_sha256(dec_path),
                "recorded_at": "2026-11-09T10:35:00+03:00",
            },
        ]
        st_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = sv.main(["--check-schemas", "--case", str(case), "--strict"])
        self.assertEqual(rc, 0, buf.getvalue())

        # Изменение файла после контрольной точки ловится в --strict
        ev_tampered = valid_evidence()
        ev_tampered["sources"][1]["notes"] = "Изменено после контрольной точки"
        ev_path.write_text(json.dumps(ev_tampered, ensure_ascii=False, indent=2), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(sv.main(["--case", str(case)]), 0)  # по умолчанию WARNING
            self.assertEqual(sv.main(["--case", str(case), "--strict"]), 1)  # в strict -> ERROR


if __name__ == "__main__":
    unittest.main()
