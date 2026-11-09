---
name: options-and-strategy
description: >-
  Генерирует не менее трёх содержательно разных вариантов развития продукта
  (включая «оставить как есть» и «закрыть направление») с сильными
  возражениями и проектирует согласованные продуктовую и коммуникационную
  стратегии, план проверки и сопровождение решения в strategy_decision.json.
  Активируется на этапах OPTIONS_GENERATION и STRATEGY_DESIGN.
---

# Skill: options-and-strategy

Покрывает `FR-05`..`FR-08`, `T05` (варианты), `T06` (согласованность продукта и коммуникации).

Справочники (прочитай перед работой):
- `knowledge/product-strategy/frameworks.md` — JTBD, альтернативы, варианты, экономика;
- `knowledge/communication/messaging-guide.md` — сообщение, доказательства, каналы;
- `knowledge/evaluation/validation-and-guardrails.md` — план проверки, обязательства, триггеры.

Профиль: проектирование стратегии — `pro` / `inherit`.

## Когда активировать

- Этап `OPTIONS_GENERATION` или `STRATEGY_DESIGN`.
- Возврат после отказа аудита или каскадного пересмотра.

## Входные условия

```
python tools/strategist_cli.py status --case projects/<case>
```

Нет устаревших узлов в опорах; противоречия объяснены; пробелы названы. Иначе — назад в `source-and-data-analysis`.

## Шаг 1. Сгенерировать варианты (`OPTIONS_GENERATION`)

Файл: `projects/<case>/decisions/strategy_decision.json`, `decision_status: "draft"`.

Минимум 3 варианта `O-xxx`, различающиеся логикой ценности/модели:

| `option_type` | Обязательность | Суть |
|---|---|---|
| `status_quo` | обязательно | что будет без изменений — тренды, затраты, риски |
| `sunset_or_close` | обязательно | закрыть/свернуть — высвобождаемые ресурсы, потери, миграция |
| `strategic_direction` | ≥ 1 | смена сегмента, монетизации, канала, позиционирования |

Каждый вариант:

```json
{
  "id": "O-003",
  "title": "Фокус на подготовке к сессии с оплатой за семестр",
  "option_type": "strategic_direction",
  "summary": "...механика ценности...",
  "supporting_refs": ["F-001", "C-001", "H-002"],
  "strong_objections": ["Сезонный спрос: 4 месяца выручки в году (F-006)", "..."],
  "expected_economics": "Выручка +, CAC −, риск оттока между сессиями",
  "verdict": "selected"
}
```

Правила:
- `strong_objections` — сильнейшие аргументы скептика, а не формальность; у выбранного варианта тоже.
- `status_quo` и `sunset_or_close` оцениваются с цифрами, не отбрасываются без разбора.
- Ровно один `selected`; остальные `rejected` или `fallback` с причиной в `summary`/возражениях.
- Экономика — из `C-xxx`; если цифры нет — `H-xxx` и пометка в допущениях.

Проверка и переход:

```
python tools/schema_validator.py --case projects/<case>
python tools/strategist_cli.py advance-stage --case projects/<case> --to STRATEGY_DESIGN --note "варианты сформированы"
```

## Шаг 2. Продуктовая стратегия (`product_strategy`)

Обязательные поля: `selected_option_id`, `target_audience`, `user_job_to_be_done`, `competing_alternatives` (включая `habitual_free_workaround` и `do_nothing`), `chosen_direction`, `key_capabilities` (`id` + `description`), `explicit_refusals`, `cost_drivers`, `revenue_or_value_logic`, `unit_economics_link`, `evidence_refs`, `assumptions_and_limits`.

- `selected_option_id` = `id` варианта с `verdict: selected`.
- `explicit_refusals` — от чего отказываемся и почему (сегменты, функции, обещания).
- `unit_economics_link` — как ценность превращается в маржу; помни: рост выручки ≠ рост прибыли, интерес ≠ готовность платить, проблема ≠ необходимость ИИ.

## Шаг 3. Раскрыть допущения (`assumptions_and_limits`)

Если хоть одна опора — `H-xxx` или синтетика, добавь запись `{kind, statement, related_refs}`:
- гипотезы и прогнозы — с указанием, как будут проверены;
- синтетические респонденты — явно: «основано на модельных респондентах, не является доказательством спроса»;
- пробелы `G-xxx`, влияющие на выбор.

## Шаг 4. Коммуникационная стратегия (`communication_strategy`)

Поля: `target_audience_and_context`, `comprehension_or_choice_barrier`, `key_message`, `proof_points[]` (`promise`, `product_capability_ref`, `evidence_refs`), `channels_and_roles[]` (`channel`, `funnel_role`), `consistency_check`.

Проверка непротиворечивости (`T06`) — запиши результат в `consistency_check`:
1. каждый `proof_point.product_capability_ref` существует в `key_capabilities`;
2. `evidence_refs` в `proof_points` — только `F-xxx`/`C-xxx`, без синтетики;
3. ни одно обещание не противоречит `explicit_refusals` (по смыслу);
4. аудитория совпадает с `product_strategy.target_audience`;
5. обещанный результат измеряется в `validation_plan`.

## Шаг 5. План проверки (`validation_plan`)

`expected_change`, `primary_metrics[]` (`metric_name`, `definition`, `target`, `unit`), `baseline_comparison`, `observation_period`, `guardrail_and_negative_consequences[]` (`consequence`, `guardrail_metric`, `threshold`). Минимум 2 защитные метрики (отток, нагрузка на поддержку, каннибализация, жалобы).

## Шаг 6. Сопровождение (`decision_support_and_reassessment`)

- `commitments[]`: `id`, `owner_role`, `action`, `due_date`, `checkpoint`, `status`.
- `reassessment_triggers[]`: `id`, `condition`, `metric_name`, `threshold`, `watched_refs` — покрыть опоры выбранного варианта и `proof_points`.
- `affected_by_stale_nodes`: `[]` (заполняется каскадом `invalidate-source`).

## Шаг 7. Проверка и передача на аудит

```
python tools/schema_validator.py --case projects/<case> --strict
python tools/strategist_cli.py render-outputs --case projects/<case>
python tools/strategist_cli.py log-usage --case projects/<case> --step-id strategy-001 \
  --actor options-and-strategy --model-tier heavy --duration-sec <N> --is-estimated true
python tools/strategist_cli.py advance-stage --case projects/<case> --to INDEPENDENT_REVIEW --note "стратегия готова к аудиту"
```

Далее — skill `evidence-audit-and-reassessment`.

## Анти-паттерны

- Три оттенка одного варианта; «закрыть» отвергнуто одной фразой.
- Обещание без возможности продукта или без `F/C`.
- Синтетические ответы как доказательство спроса.
- Целевая метрика с другим знаменателем, чем в графе.
- Самостоятельная установка `approved_by_human`.
