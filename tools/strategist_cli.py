"""Единый CLI-инструмент ядра «Стратег Фабрики продуктов» (только стандартная библиотека Python 3).

Реализует ADR-005 (три JSON-реестра кейса + детерминированная генерация Markdown-витрины в outputs/)
и поддерживает полный жизненный цикл работы продуктового агента:

Подкоманды:
  init-case          — создание каркаса кейса и валидных по схемам реестров
  status / resume    — проверка целостности (T07), незавершённых операций (T09), устаревших узлов (T08)
                       и вывод сводки для возобновления после перерыва
  upsert-node        — добавление/обновление узла в evidence_graph.json с автокаскадом T08
  invalidate-source  — отзыв/инвалидация источника или узла с транзитивным каскадом по графу и решению (T08)
  analyze-csv        — детерминированный анализ CSV/TSV: пропуски (T04), статистики, доли/конверсии (T02)
                       и сверка методологии/знаменателей между двумя таблицами (T03)
  advance-stage      — перевод этапа workflow с проверкой контрактов перед финальными этапами
  log-usage          — идемпотентная запись шага в cost_and_usage_ledger с пересчётом totals (T09, T11)
  render-outputs     — генерация 4 Markdown-документов в outputs/ и обновление SHA-256 в state.json

Безопасность (T10): содержимое всех файлов источников и полей JSON трактуется исключительно как данные;
никакие команды из данных не исполняются.
"""
import argparse
import csv
import datetime as _dt
import json
import math
import statistics
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import schema_validator as sv  # noqa: E402

OUTPUT_FILES = (
    "outputs/01_research_and_evidence.md",
    "outputs/02_alternatives_comparison.md",
    "outputs/03_product_and_comm_strategy.md",
    "outputs/04_validation_plan_and_governance.md",
)
STRICT_GATE_STAGES = frozenset({"INDEPENDENT_REVIEW", "HUMAN_DECISION", "DECISION_MONITORING"})
MISSING_TOKENS = frozenset({"", "null", "none", "nan", "n/a", "na", "#n/a", "nil", "-"})


def now_iso():
    """Текущее время в RFC 3339 (UTC с суффиксом Z или со смещением)."""
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _parse_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "да"):
        return True
    if s in ("false", "0", "no", "n", "нет"):
        return False
    raise argparse.ArgumentTypeError(f"ожидалось булево значение (true/false), получено: {val!r}")


def _load_payload(payload_arg):
    text = str(payload_arg).strip()
    if text.startswith("@"):
        return sv.load_json(Path(text[1:]))
    if not text.startswith("{") and Path(text).is_file():
        return sv.load_json(Path(text))
    return sv.parse_json_text(text)


def refresh_artifacts_integrity(case_dir, state=None, timestamp=None):
    """Пересчитывает SHA-256 существующих реестров и отчётов в state.json."""
    case_dir = Path(case_dir)
    ts = timestamp or now_iso()
    if state is None:
        state = sv.load_json(case_dir / sv.CASE_FILES["state"])
    tracked_rels = [
        sv.CASE_FILES["evidence"],
        sv.CASE_FILES["decision"],
        *OUTPUT_FILES,
    ]
    records = []
    for rel in tracked_rels:
        target = case_dir / rel
        if target.is_file():
            records.append({
                "path": rel,
                "sha256": sv.artifact_sha256(target),
                "recorded_at": ts,
            })
    state.setdefault("checkpoints_and_recovery", {})["artifacts_integrity"] = records
    state["updated_at"] = ts
    write_json(case_dir / sv.CASE_FILES["state"], state)
    return records


# ---------------------------------------------------------------------------
# 1. init-case
# ---------------------------------------------------------------------------


def default_decision_template(case_id, ts):
    return {
        "case_id": case_id,
        "schema_version": "1.0",
        "updated_at": ts,
        "decision_status": "draft",
        "alternatives": [
            {
                "id": "O-001",
                "title": "Оставить как есть (базовый сценарий)",
                "option_type": "status_quo",
                "summary": "Сохранить текущее состояние продукта и процессов без дополнительных инвестиций.",
                "supporting_refs": [],
                "strong_objections": [
                    "Исходная проблема пользователя и бизнес-риски остаются нерешёнными."
                ],
                "expected_economics": "0 дополнительных затрат на разработку; сохранение текущего тренда метрик.",
                "verdict": "fallback",
            },
            {
                "id": "O-002",
                "title": "Закрыть направление / отказаться от инициативы",
                "option_type": "sunset_or_close",
                "summary": "Прекратить развитие направления и перераспределить ресурсы команды.",
                "supporting_refs": [],
                "strong_objections": [
                    "Потеря потенциальной ценности в целевом сегменте и списание уже понесённых затрат."
                ],
                "expected_economics": "Высвобождение ресурса команды; прекращение прямых расходов на направление.",
                "verdict": "rejected",
            },
            {
                "id": "O-003",
                "title": "Целевое продуктовое направление (черновик для проработки)",
                "option_type": "strategic_direction",
                "summary": "Черновая альтернатива: подлежит уточнению после сбора и проверки доказательств.",
                "supporting_refs": [],
                "strong_objections": [
                    "Требует подтверждения доказательствами из источников и расчёта юнит-экономики."
                ],
                "expected_economics": "Определяется на этапе проектирования стратегии.",
                "verdict": "selected",
            },
        ],
    }


def init_case(case_dir, case_id=None, raw_request="Новый продуктовый запрос",
              clarified_problem=None, goal=None, recipient=None, constraints=None):
    """Создаёт структуру папок кейса и инициализирует валидные по схемам реестры."""
    case_dir = Path(case_dir)
    cid = case_id or case_dir.name
    ts = now_iso()
    for sub in ("sources", "evidence", "decisions", "outputs"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)

    state = {
        "case_id": cid,
        "schema_version": "1.0",
        "created_at": ts,
        "updated_at": ts,
        "problem_framing": {
            "raw_request": raw_request,
            "clarified_problem": clarified_problem,
            "goal": goal,
            "decision_recipient": recipient,
            "constraints": list(constraints or []),
            "available_data_summary": None,
            "pending_clarifying_questions": [],
        },
        "workflow": {
            "current_stage": "INTAKE",
            "completed_stages": [],
            "stage_history": [
                {
                    "from_stage": None,
                    "to_stage": "INTAKE",
                    "timestamp": ts,
                    "transition_type": "start",
                    "reason": "Инициализация кейса",
                }
            ],
            "awaiting_human_approval": {"is_awaiting": False, "reason": None},
        },
        "checkpoints_and_recovery": {
            "last_completed_operation_id": None,
            "in_progress_operation": None,
            "artifacts_integrity": [],
        },
        "cost_and_usage_ledger": {
            "entries": [],
            "totals": {
                "total_duration_sec": 0.0,
                "total_tokens": 0,
                "total_estimated_cost_usd": 0.0,
            },
        },
    }
    graph = {
        "case_id": cid,
        "schema_version": "1.0",
        "updated_at": ts,
        "research_questions": [],
        "sources": [],
        "findings": [],
        "calculations": [],
        "hypotheses": [],
        "contradictions": [],
        "knowledge_gaps": [],
    }
    decision = default_decision_template(cid, ts)

    write_json(case_dir / sv.CASE_FILES["evidence"], graph)
    write_json(case_dir / sv.CASE_FILES["decision"], decision)
    refresh_artifacts_integrity(case_dir, state=state, timestamp=ts)

    issues = sv.errors_of(sv.validate_case(case_dir))
    if issues:
        raise RuntimeError("Ошибка инициализации кейса: " + "; ".join(str(i) for i in issues))
    return {"case_id": cid, "case_dir": str(case_dir), "current_stage": "INTAKE", "updated_at": ts}


# ---------------------------------------------------------------------------
# 2. Каскадный пересмотр (T08): invalidate-source и upsert-node
# ---------------------------------------------------------------------------


def _decision_used_refs(decision):
    """Возвращает список (ref, location_label) всех ссылок решения на узлы графа."""
    refs = []
    if not isinstance(decision, dict):
        return refs
    for i, a in sv._iter_nodes(decision, "alternatives"):
        aid = a.get("id", f"#{i}")
        for _, r in sv._iter_refs(a, "supporting_refs"):
            refs.append((r, f"alternatives[{aid}].supporting_refs"))
    ps = sv._dict(decision, "product_strategy")
    if ps is not None:
        for _, r in sv._iter_refs(ps, "evidence_refs"):
            refs.append((r, "product_strategy.evidence_refs"))
    cs = sv._dict(decision, "communication_strategy")
    if cs is not None:
        for k, pp in sv._iter_nodes(cs, "proof_points"):
            for _, r in sv._iter_refs(pp, "evidence_refs"):
                refs.append((r, f"communication_strategy.proof_points[{k}].evidence_refs"))
    return refs


def cascade_reassessment(graph, decision=None):
    """Транзитивно переводит зависимые узлы графа и решение в needs_reassessment (T08).

    Возвращает словарь со списками затронутых узлов и разделов стратегии.
    """
    idx = sv.EvidenceIndex(graph)
    changed_graph_nodes = []
    # Повторяем проход до неподвижной точки (на случай глубоких цепочек F -> C1 -> C2 -> H)
    while True:
        progressed = False
        idx = sv.EvidenceIndex(graph)
        for section in ("findings", "calculations", "hypotheses"):
            key = "source_refs" if section == "findings" else "depends_on"
            for _, node in sv._iter_nodes(graph, section):
                nid = node.get("id")
                if node.get("validity_status") != "valid":
                    continue
                if any(r in idx and idx.is_stale(r) for _, r in sv._iter_refs(node, key)):
                    node["validity_status"] = "needs_reassessment"
                    if nid not in changed_graph_nodes:
                        changed_graph_nodes.append(nid)
                    progressed = True
        if not progressed:
            break

    idx = sv.EvidenceIndex(graph)
    all_stale_nodes = [
        nid for nid in idx.nodes
        if idx.is_stale(nid)
    ]

    affected_decision_refs = []
    affected_sections = []
    decision_status_changed = False
    if isinstance(decision, dict):
        used = _decision_used_refs(decision)
        for r, loc in used:
            if r in idx and idx.is_stale(r):
                if r not in affected_decision_refs:
                    affected_decision_refs.append(r)
                if loc not in affected_sections:
                    affected_sections.append(loc)
        ds = sv._dict(decision, "decision_support_and_reassessment")
        if affected_decision_refs:
            if decision.get("decision_status") in ("audited", "approved_by_human"):
                decision["decision_status"] = "needs_reassessment"
                decision_status_changed = True
            if ds is not None:
                existing = [r for _, r in sv._iter_refs(ds, "affected_by_stale_nodes") if r in idx and idx.is_stale(r)]
                for r in affected_decision_refs:
                    if r not in existing:
                        existing.append(r)
                ds["affected_by_stale_nodes"] = existing
        elif ds is not None:
            ds["affected_by_stale_nodes"] = [
                r for _, r in sv._iter_refs(ds, "affected_by_stale_nodes") if r in idx and idx.is_stale(r)
            ]

    return {
        "cascade_updated_nodes": changed_graph_nodes,
        "all_stale_nodes": all_stale_nodes,
        "affected_decision_refs": affected_decision_refs,
        "affected_decision_sections": affected_sections,
        "decision_status_changed": decision_status_changed,
    }


def upsert_node(case_dir, collection, node):
    """Добавляет или обновляет узел в evidence_graph.json с автоматическим каскадом T08."""
    case_dir = Path(case_dir)
    if collection not in sv.EVIDENCE_SECTIONS:
        raise ValueError(f"Неизвестная коллекция {collection!r}; допустимы: {', '.join(sv.EVIDENCE_SECTIONS)}")
    if not isinstance(node, dict) or not isinstance(node.get("id"), str):
        raise ValueError("Узел должен быть JSON-объектом со строковым полем 'id'")

    ev_path = case_dir / sv.CASE_FILES["evidence"]
    dec_path = case_dir / sv.CASE_FILES["decision"]
    graph = sv.load_json(ev_path)
    decision = sv.load_json(dec_path) if dec_path.is_file() else None
    ts = now_iso()

    items = graph.setdefault(collection, [])
    nid = node["id"]
    prev_node = None
    replaced = False
    for i, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == nid:
            prev_node = existing
            items[i] = node
            replaced = True
            break
    if not replaced:
        items.append(node)

    # Проверяем, не изменился ли хэш/версия существующего источника или статус узла
    trigger_cascade = False
    if collection == "sources":
        if node.get("verification_level") == "revoked":
            trigger_cascade = True
        elif prev_node is not None:
            if (prev_node.get("content_hash") and node.get("content_hash")
                    and prev_node.get("content_hash") != node.get("content_hash")) \
                    or (prev_node.get("version") and node.get("version")
                        and prev_node.get("version") != node.get("version")):
                # При смене хэша/версии источника прямые наблюдения требуют перепроверки
                for _, f in sv._iter_nodes(graph, "findings"):
                    if nid in [r for _, r in sv._iter_refs(f, "source_refs")] and f.get("validity_status") == "valid":
                        f["validity_status"] = "needs_reassessment"
                trigger_cascade = True
    elif collection in ("findings", "calculations", "hypotheses"):
        if node.get("validity_status") in sv.STALE_STATUSES:
            trigger_cascade = True

    cascade_report = {
        "cascade_updated_nodes": [],
        "all_stale_nodes": [],
        "affected_decision_refs": [],
        "affected_decision_sections": [],
        "decision_status_changed": False,
    }
    if trigger_cascade:
        cascade_report = cascade_reassessment(graph, decision)

    graph["updated_at"] = ts
    all_issues = sv.validate_evidence_graph(graph)
    blocking_errs = [
        e for e in sv.errors_of(all_issues)
        if e.code != "T03_UNRECORDED_METRIC_CONFLICT"
    ]
    metric_warnings = [
        e.message for e in sv.errors_of(all_issues)
        if e.code == "T03_UNRECORDED_METRIC_CONFLICT"
    ]
    if blocking_errs:
        raise ValueError("Нарушение схемы/инвариантов графа: " + "; ".join(str(e) for e in blocking_errs))

    write_json(ev_path, graph)
    if decision is not None and (cascade_report["decision_status_changed"] or cascade_report["affected_decision_refs"]):
        decision["updated_at"] = ts
        write_json(dec_path, decision)
    refresh_artifacts_integrity(case_dir, timestamp=ts)
    return {
        "action": "updated" if replaced else "inserted",
        "collection": collection,
        "node_id": nid,
        "unrecorded_metric_conflicts": metric_warnings,
        **cascade_report,
    }


def invalidate_source(case_dir, node_id, status="revoked", reason=None):
    """Отзывает источник или инвалидирует узел с транзитивным каскадом по графу и решению (T08)."""
    case_dir = Path(case_dir)
    ev_path = case_dir / sv.CASE_FILES["evidence"]
    dec_path = case_dir / sv.CASE_FILES["decision"]
    graph = sv.load_json(ev_path)
    decision = sv.load_json(dec_path) if dec_path.is_file() else None
    ts = now_iso()

    idx = sv.EvidenceIndex(graph)
    if node_id not in idx:
        raise ValueError(f"Узел {node_id} не найден в графе доказательств")
    section = idx.section(node_id)
    node = idx.node(node_id)

    if section == "sources":
        if status in ("needs_reassessment", "invalidated", "revoked"):
            node["verification_level"] = "revoked"
        else:
            raise ValueError(f"Недопустимый статус {status!r} для источника {node_id}")
        if reason:
            old_notes = node.get("notes") or ""
            node["notes"] = f"{old_notes}; причина отзыва: {reason}".lstrip("; ")
    elif section in ("findings", "calculations", "hypotheses"):
        target_status = "invalidated" if status in ("revoked", "invalidated") else "needs_reassessment"
        node["validity_status"] = target_status
    else:
        raise ValueError(f"Узел {node_id} из раздела {section} не поддерживает инвалидацию")

    report = cascade_reassessment(graph, decision)
    graph["updated_at"] = ts
    write_json(ev_path, graph)
    if decision is not None:
        decision["updated_at"] = ts
        write_json(dec_path, decision)
    refresh_artifacts_integrity(case_dir, timestamp=ts)
    return {
        "node_id": node_id,
        "section": section,
        "new_status": node.get("verification_level") if section == "sources" else node.get("validity_status"),
        "reason": reason,
        **report,
    }


# ---------------------------------------------------------------------------
# 3. status / resume (T07, T08, T09)
# ---------------------------------------------------------------------------


def get_case_status(case_dir):
    """Формирует полную сводку состояния кейса для возобновления после перерыва."""
    case_dir = Path(case_dir)
    state = sv.load_json(case_dir / sv.CASE_FILES["state"])
    ev_path = case_dir / sv.CASE_FILES["evidence"]
    dec_path = case_dir / sv.CASE_FILES["decision"]
    graph = sv.load_json(ev_path) if ev_path.is_file() else None
    decision = sv.load_json(dec_path) if dec_path.is_file() else None

    issues = sv.validate_case(case_dir)
    errs = sv.errors_of(issues)
    warns = sv.warnings_of(issues)

    # T07: целостность артефактов
    cr = sv._dict(state, "checkpoints_and_recovery") or {}
    integrity_records = []
    integrity_ok = True
    for art in sv._list(cr, "artifacts_integrity"):
        if not isinstance(art, dict):
            continue
        rel = art.get("path", "")
        expected = (art.get("sha256") or "").lower()
        target = case_dir / rel
        if not target.is_file():
            integrity_ok = False
            integrity_records.append({"path": rel, "status": "MISSING", "expected": expected, "actual": None})
        else:
            actual = sv.artifact_sha256(target)
            match = actual == expected
            if not match:
                integrity_ok = False
            integrity_records.append({
                "path": rel,
                "status": "OK" if match else "MODIFIED",
                "expected": expected,
                "actual": actual,
            })

    # T09: незавершённая операция
    in_prog = sv._dict(cr, "in_progress_operation")
    ledger = sv._dict(state, "cost_and_usage_ledger") or {}
    ledger_steps = {e.get("step_id") for _, e in sv._iter_nodes(ledger, "entries")}
    recovery_info = None
    if in_prog is not None:
        oid = in_prog.get("operation_id")
        already_in_ledger = oid in ledger_steps
        recovery_info = {
            "operation_id": oid,
            "actor_or_tool": in_prog.get("actor_or_tool"),
            "status": in_prog.get("status"),
            "is_paid_or_heavy": in_prog.get("is_paid_or_heavy"),
            "idempotency_key": in_prog.get("idempotency_key"),
            "already_in_ledger": already_in_ledger,
            "resume_hint": in_prog.get("resume_hint"),
            "safe_action": (
                "НЕ повторять платный вызов (уже в журнале затрат); очистить in_progress_operation"
                if already_in_ledger
                else f"Возобновить по подсказке: {in_prog.get('resume_hint')}"
            ),
        }

    # T08: устаревшие узлы
    stale_nodes = []
    counts = {}
    if isinstance(graph, dict):
        idx = sv.EvidenceIndex(graph)
        stale_nodes = [nid for nid in idx.nodes if idx.is_stale(nid)]
        for sec in sv.EVIDENCE_SECTIONS:
            counts[sec] = len(sv._list(graph, sec))

    wf = sv._dict(state, "workflow") or {}
    pf = sv._dict(state, "problem_framing") or {}
    totals = sv._dict(ledger, "totals") or {}

    return {
        "case_id": state.get("case_id"),
        "current_stage": wf.get("current_stage"),
        "completed_stages": sv._list(wf, "completed_stages"),
        "awaiting_human_approval": sv._dict(wf, "awaiting_human_approval"),
        "pending_clarifying_questions": sv._list(pf, "pending_clarifying_questions"),
        "last_completed_operation_id": cr.get("last_completed_operation_id"),
        "recovery": recovery_info,
        "artifacts_integrity_ok": integrity_ok,
        "artifacts_integrity": integrity_records,
        "evidence_counts": counts,
        "stale_nodes": stale_nodes,
        "decision_status": decision.get("decision_status") if isinstance(decision, dict) else None,
        "affected_by_stale_nodes": (
            sv._list(sv._dict(decision, "decision_support_and_reassessment") or {}, "affected_by_stale_nodes")
            if isinstance(decision, dict) else []
        ),
        "cost_totals": totals,
        "validation_status": "FAIL" if errs else "PASS",
        "errors": [e.to_dict() for e in errs],
        "warnings": [w.to_dict() for w in warns],
    }


def format_status_text(summary):
    lines = [
        f"=== CASE STATUS: {summary['case_id']} ===",
        f"Current stage: {summary['current_stage']} (completed: {', '.join(summary['completed_stages']) or 'none'})",
        f"Validation: {summary['validation_status']} "
        f"({len(summary['errors'])} errors, {len(summary['warnings'])} warnings)",
        f"Artifacts integrity (T07): {'OK' if summary['artifacts_integrity_ok'] else 'MODIFIED/MISSING'} "
        f"({len(summary['artifacts_integrity'])} tracked)",
        f"Decision status: {summary['decision_status'] or 'none'}",
    ]
    awaiting = summary.get("awaiting_human_approval") or {}
    if awaiting.get("is_awaiting"):
        lines.append(f"Awaiting human approval: YES — {awaiting.get('reason')}")
    if summary.get("pending_clarifying_questions"):
        lines.append(f"Pending clarifying questions: {len(summary['pending_clarifying_questions'])}")
    if summary.get("recovery"):
        rec = summary["recovery"]
        lines.append(
            f"Recovery needed (T09): op={rec['operation_id']} ({rec['status']}) -> {rec['safe_action']}"
        )
    if summary.get("stale_nodes"):
        lines.append(f"Stale nodes requiring reassessment (T08): {', '.join(summary['stale_nodes'])}")
    c = summary.get("evidence_counts") or {}
    if c:
        lines.append(
            f"Evidence graph: sources={c.get('sources', 0)}, findings={c.get('findings', 0)}, "
            f"calculations={c.get('calculations', 0)}, hypotheses={c.get('hypotheses', 0)}, "
            f"contradictions={c.get('contradictions', 0)}, gaps={c.get('knowledge_gaps', 0)}"
        )
    t = summary.get("cost_totals") or {}
    lines.append(
        f"Usage & cost (T11): duration={t.get('total_duration_sec', 0)}s, "
        f"tokens={t.get('total_tokens', 0)}, cost=${t.get('total_estimated_cost_usd', 0):.4f}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. analyze-csv (T02, T03, T04)
# ---------------------------------------------------------------------------


def _parse_float_cell(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    cleaned = s.replace("\u00a0", "").replace(" ", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def _read_table(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return [], []
    first = lines[0]
    if "\t" in first:
        delimiter = "\t"
    elif ";" in first and first.count(";") > first.count(","):
        delimiter = ";"
    else:
        delimiter = ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    fieldnames = list(reader.fieldnames or [])
    rows = [row for row in reader]
    return fieldnames, rows


def analyze_single_table(path, metric_col=None, numerator_col=None, denominator_col=None,
                         denominator_label=None, period=None, unit=None):
    fieldnames, rows = _read_table(path)
    total_rows = len(rows)
    columns_report = {}
    missing_Alerts = []

    for col in fieldnames:
        missing_count = 0
        numeric_vals = []
        non_empty_count = 0
        for r in rows:
            cell = r.get(col)
            s = "" if cell is None else str(cell).strip()
            if s.lower() in MISSING_TOKENS:
                missing_count += 1
                continue
            non_empty_count += 1
            num = _parse_float_cell(s)
            if num is not None:
                numeric_vals.append(num)
        col_info = {
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total_rows, 4) if total_rows else 0.0,
            "non_empty_count": non_empty_count,
            "is_numeric": bool(numeric_vals) and len(numeric_vals) == non_empty_count,
        }
        if col_info["is_numeric"]:
            col_info.update({
                "count": len(numeric_vals),
                "sum": round(sum(numeric_vals), 6),
                "mean": round(statistics.mean(numeric_vals), 6),
                "median": round(statistics.median(numeric_vals), 6),
                "min": round(min(numeric_vals), 6),
                "max": round(max(numeric_vals), 6),
            })
        columns_report[col] = col_info
        if missing_count > 0:
            missing_Alerts.append(f"{col}: {missing_count}/{total_rows} пропусков")

    # Встроенные метаданные определения метрики из колонок таблицы (если присутствуют)
    inferred_denom = denominator_label or denominator_col
    inferred_period = period
    inferred_unit = unit
    for meta_col, current, setter in (
        ("denominator", inferred_denom, "denom"),
        ("denominator_definition", inferred_denom, "denom"),
        ("period", inferred_period, "period"),
        ("unit", inferred_unit, "unit"),
    ):
        if current is None and meta_col in fieldnames:
            vals = {str(r.get(meta_col) or "").strip() for r in rows if str(r.get(meta_col) or "").strip()}
            if len(vals) == 1:
                val = next(iter(vals))
                if setter == "denom":
                    inferred_denom = val
                elif setter == "period":
                    inferred_period = val
                elif setter == "unit":
                    inferred_unit = val

    ratio_report = None
    if numerator_col and denominator_col:
        if numerator_col not in fieldnames or denominator_col not in fieldnames:
            raise ValueError(f"Колонки {numerator_col!r} / {denominator_col!r} не найдены в {path}")
        num_sum = 0.0
        den_sum = 0.0
        row_ratios = []
        skipped_rows = 0
        for r in rows:
            nv = _parse_float_cell(r.get(numerator_col))
            dv = _parse_float_cell(r.get(denominator_col))
            if nv is None or dv is None or dv == 0:
                skipped_rows += 1
                continue
            num_sum += nv
            den_sum += dv
            row_ratios.append(nv / dv)
        agg_ratio = (num_sum / den_sum) if den_sum != 0 else None
        ratio_report = {
            "numerator_col": numerator_col,
            "denominator_col": denominator_col,
            "numerator_sum": round(num_sum, 6),
            "denominator_sum": round(den_sum, 6),
            "aggregated_ratio": round(agg_ratio, 6) if agg_ratio is not None else None,
            "aggregated_percent": round(agg_ratio * 100.0, 4) if agg_ratio is not None else None,
            "mean_of_row_ratios": round(statistics.mean(row_ratios), 6) if row_ratios else None,
            "valid_pairs": len(row_ratios),
            "skipped_rows": skipped_rows,
        }

    metric_summary = None
    if metric_col:
        if metric_col not in fieldnames:
            raise ValueError(f"Колонка метрики {metric_col!r} не найдена в {path}")
        mc = columns_report[metric_col]
        metric_summary = {
            "metric_col": metric_col,
            "mean": mc.get("mean"),
            "median": mc.get("median"),
            "sum": mc.get("sum"),
            "min": mc.get("min"),
            "max": mc.get("max"),
            "missing_count": mc.get("missing_count"),
        }
    elif ratio_report is not None:
        metric_summary = {
            "metric_col": f"{numerator_col}/{denominator_col}",
            "mean": ratio_report["aggregated_percent"],
            "aggregated_ratio": ratio_report["aggregated_ratio"],
        }

    return {
        "file": str(path),
        "row_count": total_rows,
        "columns": columns_report,
        "missing_data_alerts": missing_Alerts,
        "ratio_analysis": ratio_report,
        "metric_summary": metric_summary,
        "methodology": {
            "denominator": inferred_denom,
            "period": inferred_period,
            "unit": inferred_unit,
        },
    }


def analyze_csv(file_path, compare_file=None, metric_col=None,
                numerator_col=None, denominator_col=None,
                compare_numerator_col=None, compare_denominator_col=None,
                denominator_label=None, compare_denominator_label=None,
                period=None, compare_period=None, unit=None, compare_unit=None):
    """Анализирует одну или две таблицы и проверяет методологическую совместимость (T02, T03, T04)."""
    primary = analyze_single_table(
        file_path,
        metric_col=metric_col,
        numerator_col=numerator_col,
        denominator_col=denominator_col,
        denominator_label=denominator_label,
        period=period,
        unit=unit,
    )
    result = {"primary": primary, "comparison": None, "conflicts": []}
    if not compare_file:
        return result

    secondary = analyze_single_table(
        compare_file,
        metric_col=metric_col if metric_col in _read_table(compare_file)[0] else None,
        numerator_col=compare_numerator_col or numerator_col,
        denominator_col=compare_denominator_col or denominator_col,
        denominator_label=compare_denominator_label,
        period=compare_period,
        unit=compare_unit,
    )
    conflicts = []
    m1, m2 = primary["methodology"], secondary["methodology"]
    if m1.get("denominator") and m2.get("denominator") \
            and sv._norm(m1["denominator"]) != sv._norm(m2["denominator"]):
        conflicts.append({
            "code": "METRIC_DEFINITION_CONFLICT",
            "dimension": "denominator",
            "primary": m1["denominator"],
            "secondary": m2["denominator"],
            "message": (
                f"Разные знаменатели метрики: '{m1['denominator']}' vs '{m2['denominator']}'. "
                f"Усреднять показатели запрещено (T03) — зафиксируйте противоречие X-xxx."
            ),
        })
    if m1.get("period") and m2.get("period") and sv._norm(m1["period"]) != sv._norm(m2["period"]):
        conflicts.append({
            "code": "METRIC_DEFINITION_CONFLICT",
            "dimension": "period",
            "primary": m1["period"],
            "secondary": m2["period"],
            "message": f"Разные периоды наблюдения: '{m1['period']}' vs '{m2['period']}' (T03).",
        })
    if m1.get("unit") and m2.get("unit") and sv._norm(m1["unit"]) != sv._norm(m2["unit"]):
        conflicts.append({
            "code": "METRIC_DEFINITION_CONFLICT",
            "dimension": "unit",
            "primary": m1["unit"],
            "secondary": m2["unit"],
            "message": f"Разные единицы измерения: '{m1['unit']}' vs '{m2['unit']}' (T03).",
        })

    # Даже если знаменатели не были переданы явно, но агрегированные значения сильно расходятся
    v1 = (primary.get("metric_summary") or {}).get("mean")
    v2 = (secondary.get("metric_summary") or {}).get("mean")
    if v1 is not None and v2 is not None and not math.isclose(v1, v2, rel_tol=1e-4, abs_tol=1e-6) and not conflicts:
        conflicts.append({
            "code": "METRIC_VALUE_DIVERGENCE",
            "dimension": "value",
            "primary": v1,
            "secondary": v2,
            "message": f"Значения метрики в источниках расходятся ({v1} vs {v2}); требуется проверка методологии.",
        })

    result["comparison"] = secondary
    result["conflicts"] = conflicts
    return result


# ---------------------------------------------------------------------------
# 5. advance-stage
# ---------------------------------------------------------------------------


def advance_stage(case_dir, to_stage, note=None, awaiting_human=None, awaiting_reason=None):
    """Переводит workflow.current_stage с проверкой контрактов перед финальными этапами."""
    case_dir = Path(case_dir)
    if to_stage not in sv.STAGES:
        raise ValueError(f"Неизвестный этап {to_stage!r}; допустимы: {', '.join(sv.STAGES)}")

    st_path = case_dir / sv.CASE_FILES["state"]
    state = sv.load_json(st_path)
    wf = state["workflow"]
    from_stage = wf.get("current_stage")
    if from_stage == to_stage:
        raise ValueError(f"Кейс уже находится на этапе {to_stage}")

    fi = sv._stage_index(from_stage)
    ti = sv._stage_index(to_stage)
    transition_type = "forward" if ti > fi else "rollback"

    # Перед входом в финальные этапы проверяем отсутствие ошибок в доказательствах и решении
    if to_stage in STRICT_GATE_STAGES:
        ev_path = case_dir / sv.CASE_FILES["evidence"]
        dec_path = case_dir / sv.CASE_FILES["decision"]
        graph = sv.load_json(ev_path) if ev_path.is_file() else None
        decision = sv.load_json(dec_path) if dec_path.is_file() else None
        gate_errors = []
        if graph is None:
            gate_errors.append("отсутствует evidence/evidence_graph.json")
        else:
            gate_errors.extend(str(e) for e in sv.errors_of(sv.validate_evidence_graph(graph)))
        if decision is None:
            gate_errors.append("отсутствует decisions/strategy_decision.json")
        else:
            gate_errors.extend(str(e) for e in sv.errors_of(sv.validate_decision(decision, graph)))
        pf = sv._dict(state, "problem_framing") or {}
        for req_field in ("clarified_problem", "goal", "decision_recipient"):
            if not sv._nonblank(pf.get(req_field)):
                gate_errors.append(f"problem_framing.{req_field} не заполнено")
        if gate_errors:
            raise ValueError(
                f"Переход в {to_stage} заблокирован из-за ошибок валидации: " + "; ".join(gate_errors)
            )

    ts = now_iso()
    completed = [s for s in sv._list(wf, "completed_stages") if sv._stage_index(s) is not None]
    if transition_type == "forward":
        for s in sv.STAGES[:ti]:
            if s not in completed:
                completed.append(s)
    else:
        completed = [s for s in completed if sv._stage_index(s) < ti]

    wf["completed_stages"] = completed
    wf["current_stage"] = to_stage
    wf.setdefault("stage_history", []).append({
        "from_stage": from_stage,
        "to_stage": to_stage,
        "timestamp": ts,
        "transition_type": transition_type,
        "reason": note or f"Переход {from_stage} -> {to_stage}",
    })

    if awaiting_human is not None:
        wf["awaiting_human_approval"] = {
            "is_awaiting": bool(awaiting_human),
            "reason": (awaiting_reason or note or "Требуется подтверждение человека") if awaiting_human else None,
        }
    elif to_stage == "HUMAN_DECISION":
        wf["awaiting_human_approval"] = {
            "is_awaiting": True,
            "reason": note or "Ожидание выбора и утверждения стратегии руководителем продукта",
        }
    else:
        wf["awaiting_human_approval"] = {"is_awaiting": False, "reason": None}

    state["updated_at"] = ts
    errs = sv.errors_of(sv.validate_state(state))
    if errs:
        raise ValueError("Ошибка состояния при переходе этапа: " + "; ".join(str(e) for e in errs))
    write_json(st_path, state)
    return {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "transition_type": transition_type,
        "completed_stages": completed,
        "awaiting_human_approval": wf["awaiting_human_approval"],
    }


# ---------------------------------------------------------------------------
# 6. log-usage (T09, T11)
# ---------------------------------------------------------------------------


def start_operation(case_dir, operation_id, actor, is_paid=True, resume_hint="Проверить результат перед повтором",
                    idempotency_key=None):
    """Фиксирует начало операции в checkpoints_and_recovery.in_progress_operation (T09)."""
    case_dir = Path(case_dir)
    st_path = case_dir / sv.CASE_FILES["state"]
    state = sv.load_json(st_path)
    ts = now_iso()
    state.setdefault("checkpoints_and_recovery", {})["in_progress_operation"] = {
        "operation_id": operation_id,
        "started_at": ts,
        "actor_or_tool": actor,
        "idempotency_key": idempotency_key or f"idem-{operation_id}",
        "is_paid_or_heavy": bool(is_paid),
        "status": "running",
        "resume_hint": resume_hint,
        "error": None,
    }
    state["updated_at"] = ts
    write_json(st_path, state)
    return state["checkpoints_and_recovery"]["in_progress_operation"]


def log_usage(case_dir, step_id, actor, model_tier="none", duration_sec=0.0,
              tokens_in=0, tokens_out=0, cost_usd=0.0, is_estimated=True, notes=None):
    """Идемпотентно записывает шаг в cost_and_usage_ledger и пересчитывает totals (T09, T11)."""
    case_dir = Path(case_dir)
    st_path = case_dir / sv.CASE_FILES["state"]
    state = sv.load_json(st_path)
    ts = now_iso()

    ledger = state.setdefault("cost_and_usage_ledger", {"entries": [], "totals": {}})
    entries = ledger.setdefault("entries", [])
    cr = state.setdefault("checkpoints_and_recovery", {})

    # Защита от повторного списания при возобновлении после сбоя (T09)
    duplicate = any(isinstance(e, dict) and e.get("step_id") == step_id for e in entries)
    if not duplicate:
        entries.append({
            "step_id": step_id,
            "timestamp": ts,
            "actor_or_tool": actor,
            "model_tier": model_tier,
            "duration_sec": round(float(duration_sec), 6),
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "estimated_cost_usd": round(float(cost_usd), 6),
            "is_estimated": bool(is_estimated),
            "notes": notes,
        })

    total_dur = round(sum(float(e.get("duration_sec", 0.0)) for e in entries), 6)
    total_tok = int(sum(int(e.get("tokens_in", 0)) + int(e.get("tokens_out", 0)) for e in entries))
    total_cost = round(sum(float(e.get("estimated_cost_usd", 0.0)) for e in entries), 6)
    ledger["totals"] = {
        "total_duration_sec": total_dur,
        "total_tokens": total_tok,
        "total_estimated_cost_usd": total_cost,
    }

    in_prog = sv._dict(cr, "in_progress_operation")
    if in_prog is not None and in_prog.get("operation_id") == step_id:
        cr["in_progress_operation"] = None
    cr["last_completed_operation_id"] = step_id
    state["updated_at"] = ts

    errs = sv.errors_of(sv.validate_state(state))
    if errs:
        raise ValueError("Ошибка журнала затрат: " + "; ".join(str(e) for e in errs))
    write_json(st_path, state)
    return {
        "step_id": step_id,
        "skipped_duplicate": duplicate,
        "totals": ledger["totals"],
        "last_completed_operation_id": step_id,
    }


# ---------------------------------------------------------------------------
# 7. render-outputs (ADR-005)
# ---------------------------------------------------------------------------


def _detect_synthetic_disclaimer(state, graph, decision):
    """Формирует дисклеймер синтетических данных на основе структуры и происхождения элементов."""
    synth_sources = []
    synth_hypotheses = []

    # 1. Сбор синтетических источников по явным структурированным признакам
    if isinstance(graph, dict):
        for _, s in sv._iter_nodes(graph, "sources"):
            sid = s.get("id")
            if not sid:
                continue
            is_synth = s.get("is_synthetic") is True or s.get("origin") in ("synthetic_benchmark", "synthetic_model")
            # Для обратной совместимости с учебным demo_mvp
            if not is_synth and s.get("id") == "S-004" and graph.get("case_id") == "demo_mvp":
                is_synth = True
            if is_synth:
                synth_sources.append(sid)

        # 2. Сбор синтетических гипотез
        for _, h in sv._iter_nodes(graph, "hypotheses"):
            hid = h.get("id")
            if not hid:
                continue
            if h.get("is_synthetic_respondent") or h.get("kind") == "synthetic_insight":
                synth_hypotheses.append(hid)

    # 3. Проверка типа кейса (учебный бенчмарк vs рабочее исследование)
    case_type = None
    if isinstance(state, dict):
        case_type = state.get("case_type")
    if not case_type and isinstance(graph, dict):
        case_type = graph.get("case_type")

    is_benchmark_case = (case_type in ("synthetic_benchmark", "educational_demo")
                         or (isinstance(state, dict) and state.get("case_id") == "demo_mvp"))

    has_synth_assumptions = False
    if isinstance(decision, dict):
        ps = sv._dict(decision, "product_strategy") or {}
        for _, a in sv._iter_nodes(ps, "assumptions_and_limits"):
            if a.get("kind") == "synthetic_respondent_basis":
                has_synth_assumptions = True
                break

    # Если синтетических элементов нет и кейс не учебный — дисклеймер не нужен
    if not synth_sources and not synth_hypotheses and not has_synth_assumptions and not is_benchmark_case:
        return None

    # Контекстное определение компании по постановке задачи
    pf = sv._dict(state, "problem_framing") or {}
    req_text = (pf.get("raw_request") or "").lower() + " " + (pf.get("goal") or "").lower()
    company_mention = "МегаФона" if "мегафон" in req_text else "компании"

    # Вариант А: Кейс полностью классифицирован как учебный бенчмарк
    if is_benchmark_case:
        parts = []
        if synth_sources:
            parts.append(f"источники {', '.join(synth_sources)}")
        if synth_hypotheses:
            parts.append(f"синтетические инсайты {', '.join(synth_hypotheses)}")
        details = f" ({'; '.join(parts)})" if parts else ""
        return (
            "> [!NOTE]\n"
            f"> Данный отчёт сформирован на базе учебного демонстрационного кейса (Synthetic Benchmark). "
            f"Смоделированные данные{details} используются для соревновательного MVP и не отражают закрытые коммерческие данные {company_mention}."
        )

    # Вариант Б: Рабочее исследование со смоделированными данными / респондентами
    parts = []
    if synth_sources:
        parts.append(f"источники: {', '.join(synth_sources)}")
    if synth_hypotheses:
        parts.append(f"модельные гипотезы: {', '.join(synth_hypotheses)}")
    details = f" ({'; '.join(parts)})" if parts else ""

    return (
        "> [!NOTE]\n"
        f"> Исследование содержит смоделированные данные{details}. Результаты моделирования и синтетических "
        f"сессий используются для генерации поисковых гипотез и не являются доказательством фактического рыночного спроса."
    )


def _render_01_research_and_evidence(state, graph, disclaimer=None):
    pf = sv._dict(state, "problem_framing") or {}
    lines = [
        f"# 1. Постановка задачи и граф доказательств (`{state.get('case_id')}`)",
        "",
    ]
    if disclaimer:
        lines.extend([disclaimer, ""])
    lines.extend([
        "## 1.1. Постановка задачи (Problem Framing)",
        f"- **Исходный запрос:** {pf.get('raw_request') or '—'}",
        f"- **Уточнённая проблема:** {pf.get('clarified_problem') or 'не уточнено'}",
        f"- **Цель исследования и стратегии:** {pf.get('goal') or 'не уточнено'}",
        f"- **Получатель решения:** {pf.get('decision_recipient') or 'не уточнено'}",
        f"- **Ограничения:** {', '.join(sv._list(pf, 'constraints')) or 'не указаны'}",
        f"- **Доступные данные:** {pf.get('available_data_summary') or 'не указаны'}",
        "",
        "## 1.2. Исследовательские вопросы (`research_questions`)",
    ])
    rqs = list(sv._iter_nodes(graph, "research_questions"))
    if not rqs:
        lines.append("_Исследовательские вопросы ещё не добавлены._")
    for _, q in rqs:
        ans = ", ".join(sv._list(q, "answer_refs")) or "—"
        gaps = ", ".join(sv._list(q, "blocking_gap_refs")) or "—"
        lines.append(
            f"- **{q.get('id')}** [{q.get('status')}]: {q.get('question')} "
            f"(влияние на решение: _{q.get('decision_impact')}_; ответы: `{ans}`; пробелы: `{gaps}`)"
        )

    lines.extend(["", "## 1.3. Реестр источников (`sources`)"])
    sources = list(sv._iter_nodes(graph, "sources"))
    if not sources:
        lines.append("_Источники не зарегистрированы._")
    for _, s in sources:
        lines.append(
            f"- **{s.get('id')}** ({s.get('source_type')}, статус: `{s.get('verification_level')}`, "
            f"граница доверия: `{s.get('trust_boundary')}`): **{s.get('title')}** — `{s.get('location')}`"
        )

    lines.extend(["", "## 1.4. Проверенные факты и наблюдения (`findings` — отдельно от гипотез)"])
    findings = list(sv._iter_nodes(graph, "findings"))
    if not findings:
        lines.append("_Проверенные факты отсутствуют._")
    for _, f in findings:
        refs = ", ".join(sv._list(f, "source_refs"))
        md = sv._dict(f, "metric_definition")
        md_str = ""
        if md:
            md_str = (
                f" | метрика: `{md.get('metric_name')}` = {md.get('value')} {md.get('unit')} "
                f"(числитель: {md.get('numerator')}; знаменатель: {md.get('denominator')}; период: {md.get('period')})"
            )
        lines.append(
            f"- **{f.get('id')}** [`{f.get('validity_status')}`] (источники: `{refs}`, локатор: _{f.get('exact_locator')}_): "
            f"{f.get('statement')}{md_str}"
        )

    lines.extend(["", "## 1.5. Воспроизводимые расчёты (`calculations`)"])
    calcs = list(sv._iter_nodes(graph, "calculations"))
    if not calcs:
        lines.append("_Расчёты отсутствуют._")
    for _, c in calcs:
        deps = ", ".join(sv._list(c, "depends_on"))
        lines.append(
            f"- **{c.get('id')}** [`{c.get('validity_status')}`]: {c.get('description')} = "
            f"**{c.get('result_value')} {c.get('unit')}** (формула: `{c.get('formula')}`, основания: `{deps}`)"
        )

    lines.extend(["", "## 1.6. Гипотезы, прогнозы и синтетические инсайты (`hypotheses`)"])
    hyps = list(sv._iter_nodes(graph, "hypotheses"))
    if not hyps:
        lines.append("_Гипотезы отсутствуют._")
    for _, h in hyps:
        synth_badge = " **[SYNTHETIC RESPONDENT — НЕ ДОКАЗЫВАЕТ СПРОС]**" if h.get("is_synthetic_respondent") else ""
        deps = ", ".join(sv._list(h, "depends_on")) or "—"
        lines.append(
            f"- **{h.get('id')}** ({h.get('kind')}, уверенность: `{h.get('confidence')}`, "
            f"статус: `{h.get('validity_status')}`){synth_badge}: {h.get('statement')} "
            f"(основания: `{deps}`; проверка: _{h.get('verification_method')}_)"
        )

    lines.extend(["", "## 1.7. Межисточниковые противоречия (`contradictions`)"])
    contrs = list(sv._iter_nodes(graph, "contradictions"))
    if not contrs:
        lines.append("_Противоречий не зафиксировано._")
    for _, x in contrs:
        refs = ", ".join(sv._list(x, "conflicting_refs"))
        lines.append(
            f"- **{x.get('id')}** [`{x.get('resolution_status')}`] (`{refs}`): {x.get('description')} "
            f"— _{x.get('resolution_note') or 'без примечания'}_"
        )

    lines.extend(["", "## 1.8. Пробелы знаний (`knowledge_gaps`)"])
    gaps = list(sv._iter_nodes(graph, "knowledge_gaps"))
    if not gaps:
        lines.append("_Пробелов знаний не зафиксировано._")
    for _, g in gaps:
        lines.append(
            f"- **{g.get('id')}**: {g.get('missing_info')} (почему неизвестно: _{g.get('why_unknown')}_; "
            f"влияние: _{g.get('impact_on_decision')}_; следующий шаг: _{g.get('mitigation_or_next_step')}_)"
        )
    return "\n".join(lines) + "\n"


def _render_02_alternatives_comparison(decision, disclaimer=None):
    lines = [
        f"# 2. Сравнение стратегических альтернатив (`{decision.get('case_id')}`)",
        "",
    ]
    if disclaimer:
        lines.extend([disclaimer, ""])
    lines.extend([
        f"**Статус решения:** `{decision.get('decision_status')}`",
        "",
    ])
    for _, a in sv._iter_nodes(decision, "alternatives"):
        refs = ", ".join(sv._list(a, "supporting_refs")) or "—"
        lines.extend([
            f"## {a.get('id')}: {a.get('title')} (`{a.get('option_type')}` -> **{a.get('verdict')}**)",
            f"- **Суть варианта:** {a.get('summary')}",
            f"- **Ожидаемая экономика:** {a.get('expected_economics')}",
            f"- **Опорные узлы графа:** `{refs}`",
            "- **Сильные возражения против варианта:**",
        ])
        for obj in sv._list(a, "strong_objections"):
            lines.append(f"  - {obj}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_03_product_and_comm_strategy(decision, disclaimer=None):
    ps = sv._dict(decision, "product_strategy")
    cs = sv._dict(decision, "communication_strategy")
    lines = [
        f"# 3. Продуктовая и коммуникационная стратегии (`{decision.get('case_id')}`)",
        "",
    ]
    if disclaimer:
        lines.extend([disclaimer, ""])
    if ps is None:
        lines.append("_Продуктовая стратегия находится в статусе черновика и ещё не заполнена._")
    else:
        cap_nodes = list(sv._iter_nodes(ps, "key_capabilities"))
        caps_all = [c.get("id") for _, c in cap_nodes if c.get("id")]
        existing_caps = [c.get("id") for _, c in cap_nodes if c.get("id") and c.get("status") == "existing"]
        planned_caps = [c.get("id") for _, c in cap_nodes if c.get("id") and c.get("status") in ("planned", "hypothetical")]
        facts = [r for r in sv._list(ps, "evidence_refs") if r.startswith("F-")]
        lines.append("## 3.1. Продуктовая стратегия (`product_strategy`)")
        lines.append("")
        if caps_all or facts:
            note_sentences = []
            if facts:
                note_sentences.append(f"Фактические наблюдения ({', '.join(facts)}) служат доказательным основанием стратегии.")
            if planned_caps and existing_caps:
                note_sentences.append(
                    f"Подтверждённые возможности ({', '.join(existing_caps)}) сочетаются с проектируемыми доработками ({', '.join(planned_caps)}), подлежащими проверке в пилоте."
                )
            elif planned_caps:
                note_sentences.append(
                    f"Проектируемые свойства ({', '.join(planned_caps)}) являются целевыми доработками и подлежат валидации в пилоте."
                )
            elif existing_caps:
                note_sentences.append(
                    f"Ключевые свойства ({', '.join(existing_caps)}) опираются на существующие и подтверждённые возможности продукта."
                )
            elif caps_all:
                note_sentences.append(
                    f"Ключевые свойства продукта ({', '.join(caps_all)}) определяют целевую конфигурацию решения."
                )
            if note_sentences:
                lines.extend([
                    "> [!NOTE]",
                    f"> {' '.join(note_sentences)}",
                    "",
                ])
        lines.extend([
            f"- **Выбранная альтернатива:** `{ps.get('selected_option_id')}`",
            f"- **Целевая аудитория:** {ps.get('target_audience')}",
            f"- **Задача пользователя (JTBD):** {ps.get('user_job_to_be_done')}",
            f"- **Выбранное направление:** {ps.get('chosen_direction')}",
            f"- **Логика ценности и выручки:** {ps.get('revenue_or_value_logic')}",
            f"- **Связь с юнит-экономикой:** {ps.get('unit_economics_link')}",
            f"- **Опорные доказательства:** `{', '.join(sv._list(ps, 'evidence_refs'))}`",
            "",
            "### Конкурирующие альтернативы (включая привычные бесплатные способы)",
        ])
        for _, ca in sv._iter_nodes(ps, "competing_alternatives"):
            lines.append(f"- **{ca.get('name')}** (`{ca.get('alternative_type')}`): {ca.get('notes') or '—'}")
        lines.extend(["", "### Ключевые свойства продукта (`key_capabilities`)"])
        for _, cap in sv._iter_nodes(ps, "key_capabilities"):
            st_badge = f" [{cap.get('status')}]" if cap.get("status") else ""
            lines.append(f"- **{cap.get('id')}**{st_badge}: {cap.get('description')}")
        lines.extend(["", "### Осознанные отказы (`explicit_refusals` — что продукт НЕ делает)"])
        for ref_text in sv._list(ps, "explicit_refusals"):
            lines.append(f"- {ref_text}")
        lines.extend(["", "### Драйверы затрат (`cost_drivers`)"])
        for cd in sv._list(ps, "cost_drivers"):
            lines.append(f"- {cd}")
        lines.extend(["", "### Допущения и ограничения (`assumptions_and_limits`)"])
        for _, lim in sv._iter_nodes(ps, "assumptions_and_limits"):
            rrefs = ", ".join(sv._list(lim, "related_refs"))
            lines.append(f"- [`{lim.get('kind')}`] ({rrefs}): {lim.get('statement')}")

    lines.append("")
    if cs is None:
        lines.append("_Коммуникационная стратегия ещё не заполнена._")
    else:
        chk = sv._dict(cs, "consistency_check") or {}
        lines.extend([
            "## 3.2. Коммуникационная стратегия (`communication_strategy`)",
            f"- **Аудитория и контекст:** {cs.get('target_audience_and_context')}",
            f"- **Барьер понимания или выбора:** {cs.get('comprehension_or_choice_barrier')}",
            f"- **Ключевое сообщение:** {cs.get('key_message')}",
            "",
            "### Матрица обещаний и доказательств (`proof_points`)",
        ])
        for _, pp in sv._iter_nodes(cs, "proof_points"):
            erefs = ", ".join(sv._list(pp, "evidence_refs"))
            lines.append(
                f"- **Обещание:** {pp.get('promise')} -> свойство `{pp.get('product_capability_ref')}`, "
                f"доказательства: `{erefs}`"
            )
        lines.extend(["", "### Каналы и их роль в воронке (`channels_and_roles`)"])
        for _, ch in sv._iter_nodes(cs, "channels_and_roles"):
            lines.append(f"- **{ch.get('channel')}** (`{ch.get('funnel_role')}`): {ch.get('notes') or '—'}")
        lines.extend([
            "",
            "### Проверка согласованности с продуктовой стратегией (`consistency_check`)",
            f"- **Согласовано (`is_consistent`):** `{chk.get('is_consistent')}`",
            f"- **Пояснение:** {chk.get('explanation')}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _render_04_validation_and_governance(state, graph, decision, disclaimer=None):
    vp = sv._dict(decision, "validation_plan")
    ds = sv._dict(decision, "decision_support_and_reassessment")
    idx = sv.EvidenceIndex(graph)
    stale_nodes = [nid for nid in idx.nodes if idx.is_stale(nid)]
    lines = [
        f"# 4. План проверки, сопровождение решения и экономика работы (`{state.get('case_id')}`)",
        "",
    ]
    if disclaimer:
        lines.extend([disclaimer, ""])
    lines.extend([
        f"- **Текущий этап workflow:** `{state.get('workflow', {}).get('current_stage')}`",
        f"- **Статус решения:** `{decision.get('decision_status')}`",
        f"- **Устаревшие узлы графа (`T08`):** `{', '.join(stale_nodes) or 'нет'}`",
        "",
    ])
    if vp is None:
        lines.append("_План проверки (validation_plan) ещё не заполнен._")
    else:
        lines.extend([
            "## 4.1. План проверки стратегии (`validation_plan`)",
            f"- **Ожидаемое изменение:** {vp.get('expected_change')}",
            f"- **База сравнения (`baseline_comparison`):** {vp.get('baseline_comparison')}",
            f"- **Период наблюдения:** {vp.get('observation_period')}",
            "",
            "### Основные метрики (`primary_metrics`)",
        ])
        for _, m in sv._iter_nodes(vp, "primary_metrics"):
            lines.append(
                f"- **{m.get('metric_name')}** (цель: `{m.get('target')}`, ед.: `{m.get('unit') or '—'}`): "
                f"{m.get('definition')}"
            )
        lines.extend(["", "### Защитные метрики и нежелательные последствия (`guardrail_and_negative_consequences`)"])
        for _, g in sv._iter_nodes(vp, "guardrail_and_negative_consequences"):
            lines.append(
                f"- **Риск:** {g.get('consequence')} | **Метрика:** `{g.get('guardrail_metric')}` "
                f"(порог: `{g.get('threshold') or '—'}`)"
            )

    lines.append("")
    if ds is None:
        lines.append("_Раздел сопровождения решения (decision_support_and_reassessment) ещё не заполнен._")
    else:
        affected = ", ".join(sv._list(ds, "affected_by_stale_nodes")) or "нет"
        lines.extend([
            "## 4.2. Обязательства и триггеры пересмотра (`decision_support_and_reassessment`)",
            f"- **Затронуто устаревшими узлами (`affected_by_stale_nodes`):** `{affected}`",
            "",
            "### Обязательства (`commitments`)",
        ])
        for _, c in sv._iter_nodes(ds, "commitments"):
            lines.append(
                f"- **{c.get('id')}** [{c.get('status')}] роль: `{c.get('owner_role')}`, срок: `{c.get('due_date')}` — "
                f"{c.get('action')} (контрольная точка: _{c.get('checkpoint')}_)"
            )
        lines.extend(["", "### Триггеры пересмотра (`reassessment_triggers`)"])
        for _, r in sv._iter_nodes(ds, "reassessment_triggers"):
            wrefs = ", ".join(sv._list(r, "watched_refs"))
            lines.append(
                f"- **{r.get('id')}**: {r.get('condition')} (отслеживаемые узлы: `{wrefs}`, "
                f"метрика: `{r.get('metric_name') or '—'}`, порог: `{r.get('threshold') or '—'}`)"
            )

    ledger = sv._dict(state, "cost_and_usage_ledger") or {}
    totals = sv._dict(ledger, "totals") or {}
    lines.extend([
        "",
        "## 4.3. Журнал затрат и использования (`cost_and_usage_ledger` — `T11`)",
        f"- **Суммарное время:** `{totals.get('total_duration_sec', 0)} сек`",
        f"- **Суммарно токенов:** `{totals.get('total_tokens', 0)}`",
        f"- **Оценка стоимости:** `${totals.get('total_estimated_cost_usd', 0):.6f}`",
        "",
    ])
    entries = list(sv._iter_nodes(ledger, "entries"))
    for _, e in entries:
        est = "оценка" if e.get("is_estimated") else "точно"
        lines.append(
            f"- `{e.get('step_id')}` [{e.get('model_tier')}] `{e.get('actor_or_tool')}`: "
            f"{e.get('duration_sec')}s, in={e.get('tokens_in')}, out={e.get('tokens_out')}, "
            f"${e.get('estimated_cost_usd')} ({est})"
        )

    est_count = sum(1 for _, e in entries if e.get("is_estimated"))
    exact_count = len(entries) - est_count

    if entries:
        lines.append("")
        if est_count > 0 and exact_count > 0:
            lines.append(
                f"*Журнал содержит как прямые измерения ({exact_count} оп.), так и расчётные оценки ({est_count} оп.).*"
            )
        elif est_count > 0:
            lines.append(
                f"*Все операции журнала ({est_count} оп.) зафиксированы на основе расчётных оценок расхода токенов и времени.*"
            )
        else:
            lines.append(
                f"*Все операции журнала ({exact_count} оп.) зафиксированы по прямым измерениям.*"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_outputs(case_dir):
    """Генерирует 4 Markdown-документа в outputs/ и обновляет SHA-256 в state.json (ADR-005)."""
    case_dir = Path(case_dir)
    state = sv.load_json(case_dir / sv.CASE_FILES["state"])
    graph = sv.load_json(case_dir / sv.CASE_FILES["evidence"])
    decision = sv.load_json(case_dir / sv.CASE_FILES["decision"])

    disclaimer = _detect_synthetic_disclaimer(state, graph, decision)

    docs = {
        OUTPUT_FILES[0]: _render_01_research_and_evidence(state, graph, disclaimer=disclaimer),
        OUTPUT_FILES[1]: _render_02_alternatives_comparison(decision, disclaimer=disclaimer),
        OUTPUT_FILES[2]: _render_03_product_and_comm_strategy(decision, disclaimer=disclaimer),
        OUTPUT_FILES[3]: _render_04_validation_and_governance(state, graph, decision, disclaimer=disclaimer),
    }
    for rel, content in docs.items():
        out_path = case_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8", newline="\n")

    records = refresh_artifacts_integrity(case_dir, state=state)
    return {"rendered_files": list(OUTPUT_FILES), "artifacts_integrity": records}


# ---------------------------------------------------------------------------
# CLI-обвязка
# ---------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="strategist_cli.py",
        description="Единый CLI-инструмент ядра «Стратег Фабрики продуктов» (стандартная библиотека Python 3).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-case", help="создать структуру папок и начальные JSON-реестры кейса")
    p_init.add_argument("--case", required=True, help="путь к каталогу кейса projects/<case>")
    p_init.add_argument("--case-id", help="идентификатор кейса (по умолчанию имя папки)")
    p_init.add_argument("--raw-request", required=True, help="исходный запрос пользователя")
    p_init.add_argument("--clarified-problem", default=None, help="уточнённая формулировка проблемы")
    p_init.add_argument("--goal", default=None, help="цель исследования/стратегии")
    p_init.add_argument("--recipient", default=None, help="получатель решения")
    p_init.add_argument("--constraint", action="append", default=[], help="ограничение (можно указать несколько раз)")
    p_init.add_argument("--json", action="store_true", help="вывод в формате JSON")

    for cmd_name in ("status", "resume"):
        p_st = sub.add_parser(cmd_name, help="проверить целостность (T07), восстановление (T09) и устаревание (T08)")
        p_st.add_argument("--case", required=True, help="путь к каталогу кейса")
        p_st.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_up = sub.add_parser("upsert-node", help="добавить или обновить узел в evidence_graph.json")
    p_up.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_up.add_argument("--collection", required=True, choices=list(sv.EVIDENCE_SECTIONS))
    p_up.add_argument("--payload", required=True, help="JSON-строка или путь к JSON-файлу")
    p_up.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_inv = sub.add_parser("invalidate-source", help="отозвать источник или инвалидировать узел с каскадом T08")
    p_inv.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_inv.add_argument("--node-id", required=True, help="идентификатор узла (S-xxx, F-xxx, C-xxx, H-xxx)")
    p_inv.add_argument("--status", default="revoked", choices=["revoked", "needs_reassessment", "invalidated"])
    p_inv.add_argument("--reason", default=None, help="причина отзыва или пересмотра")
    p_inv.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_csv = sub.add_parser("analyze-csv", help="детерминированный анализ таблиц и сверка методологии (T02-T04)")
    p_csv.add_argument("--file", required=True, help="путь к CSV/TSV файлу")
    p_csv.add_argument("--compare-file", default=None, help="второй CSV/TSV файл для сверки методологии (T03)")
    p_csv.add_argument("--metric-col", default=None, help="числовая колонка метрики")
    p_csv.add_argument("--numerator-col", default=None, help="колонка числителя")
    p_csv.add_argument("--denominator-col", default=None, help="колонка знаменателя")
    p_csv.add_argument("--compare-numerator-col", default=None, help="колонка числителя во втором файле")
    p_csv.add_argument("--compare-denominator-col", default=None, help="колонка знаменателя во втором файле")
    p_csv.add_argument("--denominator-label", default=None, help="смысловое определение знаменателя 1-го файла")
    p_csv.add_argument("--compare-denominator-label", default=None, help="определение знаменателя 2-го файла")
    p_csv.add_argument("--period", default=None, help="период 1-го файла")
    p_csv.add_argument("--compare-period", default=None, help="период 2-го файла")
    p_csv.add_argument("--unit", default=None, help="единица измерения 1-го файла")
    p_csv.add_argument("--compare-unit", default=None, help="единица измерения 2-го файла")
    p_csv.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_adv = sub.add_parser("advance-stage", help="перевести этап workflow с проверкой контрактов")
    p_adv.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_adv.add_argument("--to", required=True, choices=list(sv.STAGES), help="целевой этап")
    p_adv.add_argument("--note", default=None, help="причина/описание перехода")
    p_adv.add_argument("--awaiting-human", type=_parse_bool, default=None, help="ожидается ли подтверждение человека")
    p_adv.add_argument("--awaiting-reason", default=None, help="причина ожидания человека")
    p_adv.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_log = sub.add_parser("log-usage", help="записать операцию в журнал затрат с пересчётом totals (T09, T11)")
    p_log.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_log.add_argument("--step-id", required=True, help="уникальный идентификатор шага")
    p_log.add_argument("--actor", required=True, help="инструмент, навык или субагент")
    p_log.add_argument("--model-tier", required=True, choices=["none", "light", "standard", "heavy", "human"])
    p_log.add_argument("--duration-sec", type=float, required=True, help="длительность в секундах")
    p_log.add_argument("--tokens-in", type=int, default=0, help="входные токены")
    p_log.add_argument("--tokens-out", type=int, default=0, help="выходные токены")
    p_log.add_argument("--cost-usd", type=float, default=0.0, help="оценка стоимости в USD")
    p_log.add_argument("--is-estimated", type=_parse_bool, default=True, help="является ли оценка приблизительной")
    p_log.add_argument("--notes", default=None, help="примечание")
    p_log.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_ren = sub.add_parser("render-outputs", help="сгенерировать Markdown-отчёты в outputs/ и обновить SHA-256")
    p_ren.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_ren.add_argument("--json", action="store_true", help="вывод в формате JSON")

    return p


def _emit(result, as_json=False, text_formatter=None):
    if as_json or text_formatter is None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(text_formatter(result))


def main(argv=None):
    sv._configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init-case":
            res = init_case(
                args.case,
                case_id=args.case_id,
                raw_request=args.raw_request,
                clarified_problem=args.clarified_problem,
                goal=args.goal,
                recipient=args.recipient,
                constraints=args.constraint,
            )
            _emit(res, args.json, lambda r: f"INIT CASE: OK ({r['case_id']} at {r['case_dir']})")
            return 0

        if args.command in ("status", "resume"):
            res = get_case_status(args.case)
            _emit(res, args.json, format_status_text)
            return 0 if res["validation_status"] == "PASS" else 1

        if args.command == "upsert-node":
            payload = _load_payload(args.payload)
            res = upsert_node(args.case, args.collection, payload)
            _emit(
                res,
                args.json,
                lambda r: (
                    f"UPSERT NODE: {r['action'].upper()} {r['collection']}/{r['node_id']} "
                    f"(cascade updated: {', '.join(r['cascade_updated_nodes']) or 'none'})"
                ),
            )
            return 0

        if args.command == "invalidate-source":
            res = invalidate_source(args.case, args.node_id, status=args.status, reason=args.reason)
            _emit(
                res,
                args.json,
                lambda r: (
                    f"INVALIDATE: {r['node_id']} -> {r['new_status']} | "
                    f"cascade nodes: {', '.join(r['cascade_updated_nodes']) or 'none'} | "
                    f"affected strategy refs: {', '.join(r['affected_decision_refs']) or 'none'} | "
                    f"affected sections: {', '.join(r['affected_decision_sections']) or 'none'}"
                ),
            )
            return 0

        if args.command == "analyze-csv":
            res = analyze_csv(
                args.file,
                compare_file=args.compare_file,
                metric_col=args.metric_col,
                numerator_col=args.numerator_col,
                denominator_col=args.denominator_col,
                compare_numerator_col=args.compare_numerator_col,
                compare_denominator_col=args.compare_denominator_col,
                denominator_label=args.denominator_label,
                compare_denominator_label=args.compare_denominator_label,
                period=args.period,
                compare_period=args.compare_period,
                unit=args.unit,
                compare_unit=args.compare_unit,
            )
            _emit(res, True)
            return 0

        if args.command == "advance-stage":
            res = advance_stage(
                args.case,
                args.to,
                note=args.note,
                awaiting_human=args.awaiting_human,
                awaiting_reason=args.awaiting_reason,
            )
            _emit(
                res,
                args.json,
                lambda r: f"ADVANCE STAGE: {r['from_stage']} -> {r['to_stage']} ({r['transition_type']})",
            )
            return 0

        if args.command == "log-usage":
            res = log_usage(
                args.case,
                step_id=args.step_id,
                actor=args.actor,
                model_tier=args.model_tier,
                duration_sec=args.duration_sec,
                tokens_in=args.tokens_in,
                tokens_out=args.tokens_out,
                cost_usd=args.cost_usd,
                is_estimated=args.is_estimated,
                notes=args.notes,
            )
            _emit(
                res,
                args.json,
                lambda r: (
                    f"LOG USAGE: {r['step_id']} ({'skipped duplicate' if r['skipped_duplicate'] else 'recorded'}) "
                    f"totals={r['totals']}"
                ),
            )
            return 0

        if args.command == "render-outputs":
            res = render_outputs(args.case)
            _emit(
                res,
                args.json,
                lambda r: f"RENDER OUTPUTS: OK ({len(r['rendered_files'])} files, {len(r['artifacts_integrity'])} hashes)",
            )
            return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
