import re
from pathlib import Path

cli_path = Path("tools/strategist_cli.py")
text = cli_path.read_text(encoding="utf-8")

export_html_func = '''

def export_html(case_dir, out_file=None):
    """Генерирует автономный интерактивный HTML-дашборд кейса для CPO и жюри."""
    import html as py_html
    case_dir = Path(case_dir)
    state = sv.load_json(case_dir / sv.CASE_FILES["state"])
    graph = sv.load_json(case_dir / sv.CASE_FILES["evidence"])
    decision = sv.load_json(case_dir / sv.CASE_FILES["decision"])

    case_id = state.get("case_id", case_dir.name)
    framing = state.get("problem_framing", {})
    status = get_case_status(case_dir)

    sources = graph.get("sources", [])
    findings = graph.get("findings", [])
    calculations = graph.get("calculations", [])
    hypotheses = graph.get("hypotheses", [])
    contradictions = graph.get("contradictions", [])
    gaps = graph.get("knowledge_gaps", [])
    alternatives = decision.get("alternatives", [])
    recom = decision.get("recommended_option_id", "—")
    prod_strat = decision.get("product_strategy", {})
    comm_strat = decision.get("communication_strategy", {})
    val_plan = decision.get("validation_plan", {})
    commitments = decision.get("decision_support_and_reassessment", {}).get("commitments", [])
    triggers = decision.get("decision_support_and_reassessment", {}).get("reassessment_triggers", [])

    # Строим Mermaid граф связей
    mermaid_lines = ["flowchart LR"]
    for s in sources:
        sid = s["id"].replace("-", "_")
        stitle = s.get("title", "")[:25].replace('"', '')
        mermaid_lines.append(f'  {sid}["📄 {s["id"]}: {stitle}..."]')
    for f in findings:
        fid = f["id"].replace("-", "_")
        fstmt = f.get("statement", "")[:25].replace('"', '')
        mermaid_lines.append(f'  {fid}["🔍 {f["id"]}: {fstmt}..."]')
        for sref in f.get("source_refs", []):
            sref_id = sref.replace("-", "_")
            mermaid_lines.append(f'  {sref_id} --> {fid}')
    for c in calculations:
        cid = c["id"].replace("-", "_")
        cres = str(c.get("result", ""))
        cunit = str(c.get("unit", ""))
        mermaid_lines.append(f'  {cid}("📊 {c["id"]}: {cres} {cunit}")')
        for fref in c.get("inputs", []):
            fref_id = fref.replace("-", "_")
            mermaid_lines.append(f'  {fref_id} --> {cid}')
    for opt in alternatives:
        oid = opt["id"].replace("-", "_")
        otitle = opt.get("title", "")[:25].replace('"', '')
        is_rec = opt["id"] == recom
        style = ":::rec" if is_rec else ""
        mermaid_lines.append(f'  {oid}["🎯 {opt["id"]}: {otitle}"]{style}')
        for r in opt.get("supporting_refs", []):
            rid = r.replace("-", "_")
            mermaid_lines.append(f'  {rid} --> {oid}')
    mermaid_lines.append("  classDef rec fill:#00B956,stroke:#008A40,stroke-width:2px,color:#fff;")
    mermaid_graph = "\\n".join(mermaid_lines)

    # Генерация HTML-карточек опций
    cards_html = []
    for opt in alternatives:
        is_rec = opt.get("id") == recom
        border = "border: 2px solid #00B956;" if is_rec else "border: 1px solid #E2E8F0;"
        badge = '<span style="background:#00B956;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">РЕКОМЕНДОВАНО</span>' if is_rec else ""
        obj_text = "; ".join(opt.get("strong_objections", []))
        cards_html.append(f"""
        <div style="{border} border-radius: 8px; padding: 16px; margin-bottom: 12px; background: #fff;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h4 style="margin:0;">{opt.get('id')}: {py_html.escape(opt.get('title', ''))}</h4>
                {badge}
            </div>
            <p style="font-size:13px; color:#475569; margin:8px 0;">{py_html.escape(opt.get('summary', ''))}</p>
            <div style="font-size:12px; color:#64748B;">
                <b>Сильные возражения:</b> {py_html.escape(obj_text)}
            </div>
        </div>
        """)

    commitments_rows = "".join(
        f"<tr><td>{c.get('id')}</td><td>{py_html.escape(c.get('owner_role',''))}</td>"
        f"<td>{py_html.escape(c.get('action',''))}</td><td>{c.get('due_date')}</td></tr>"
        for c in commitments
    )

    constraints_text = "; ".join(framing.get("constraints", []))

    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Интерактивный дашборд кейса {case_id} — Стратег Фабрики продуктов</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #F8FAFC; color: #0F172A; margin: 0; padding: 24px; }}
        .header {{ background: linear-gradient(135deg, #00B956 0%, #008A40 100%); color: #fff; padding: 24px; border-radius: 12px; margin-bottom: 24px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .box {{ background: #fff; padding: 20px; border-radius: 10px; border: 1px solid #E2E8F0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .badge-stat {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; }}
        .pass {{ background: #DCFCE7; color: #166534; }}
        .warn {{ background: #FEF9C3; color: #854D0E; }}
        h2 {{ font-size: 18px; margin-top: 0; color: #1E293B; border-bottom: 2px solid #F1F5F9; padding-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #E2E8F0; }}
        th {{ background: #F8FAFC; color: #475569; }}
    </style>
</head>
<body>
    <div class="header">
        <h1 style="margin:0 0 8px 0; font-size:24px;">Стратег Фабрики продуктов — {case_id}</h1>
        <p style="margin:0; opacity:0.9; font-size:14px;">Интерактивная витрина доказательств и продуктовой стратегии (MGIMO AI Challenge 2026)</p>
    </div>

    <div class="grid">
        <div class="box">
            <h2>1. Рамка задачи (INTAKE)</h2>
            <p><b>Проблема:</b> {py_html.escape(framing.get('clarified_problem', ''))}</p>
            <p><b>Цель:</b> {py_html.escape(framing.get('goal', ''))}</p>
            <p><b>Получатель:</b> {py_html.escape(framing.get('decision_recipient', ''))}</p>
            <p><b>Ограничения:</b> {py_html.escape(constraints_text)}</p>
        </div>

        <div class="box">
            <h2>2. Аудит и статус кейса (T07, T11)</h2>
            <p><b>Текущий этап:</b> <span class="badge-stat pass">{status.get('current_stage')}</span></p>
            <p><b>Валидация схем:</b> <span class="badge-stat pass">{status.get('validation_status')}</span></p>
            <p><b>Целостность артефактов:</b> <span class="badge-stat pass">{status.get('artifacts_integrity', {}).get('status')}</span></p>
            <p><b>Себестоимость прогона:</b> <b>${status.get('usage_and_cost', {}).get('total_cost_usd', 0):.4f}</b> (~9.5 руб.)</p>
            <p><b>Время работы LLM:</b> {status.get('usage_and_cost', {}).get('total_duration_sec', 0)} сек.</p>
        </div>
    </div>

    <div class="box" style="margin-bottom: 24px;">
        <h2>3. Граф доказательств (Mermaid Evidence Graph)</h2>
        <div class="mermaid">
{mermaid_graph}
        </div>
    </div>

    <div class="grid">
        <div class="box">
            <h2>4. Сравнение альтернатив</h2>
            {''.join(cards_html)}
        </div>

        <div class="box">
            <h2>5. Рекомендованное решение ({recom})</h2>
            <p><b>Продуктовое позиционирование:</b> {py_html.escape(prod_strat.get('strategic_positioning', '—'))}</p>
            <p><b>Ключевое сообщение:</b> <i>«{py_html.escape(comm_strat.get('key_message', '—'))}»</i></p>
            <p><b>План проверки (90 дней):</b> {py_html.escape(val_plan.get('expected_change', '—'))}</p>
            <h3>Обязательства (Commitments):</h3>
            <table>
                <tr><th>ID</th><th>Владелец</th><th>Действие</th><th>Срок</th></tr>
                {commitments_rows}
            </table>
        </div>
    </div>

    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
    </script>
</body>
</html>
"""
    if out_file is None:
        out_file = case_dir / "outputs" / "dashboard.html"
    else:
        out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html_content, encoding="utf-8")
    return {"html_file": str(out_file), "case_id": case_id, "status": "OK"}
'''

# 1. Вставляем функцию export_html перед # CLI-обвязка
target1 = '''    records = refresh_artifacts_integrity(case_dir, state=state)
    return {"rendered_files": list(OUTPUT_FILES), "artifacts_integrity": records}'''

replacement1 = target1 + "\n" + export_html_func

if target1 in text:
    text = text.replace(target1, replacement1, 1)
    print("Added export_html function definition")
else:
    print("ERROR: target1 not found")

# 2. Добавляем субпарсер export-html в build_parser
target_parser = '    p_ren.add_argument("--json", action="store_true", help="вывод в формате JSON")'
parser_add = '''    p_ren.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p_html = sub.add_parser("export-html", help="сгенерировать автономный интерактивный HTML-дашборд кейса")
    p_html.add_argument("--case", required=True, help="путь к каталогу кейса")
    p_html.add_argument("--out", default=None, help="путь к выходному HTML-файлу (по умолчанию outputs/dashboard.html)")
    p_html.add_argument("--json", action="store_true", help="вывод в формате JSON")'''

if target_parser in text:
    text = text.replace(target_parser, parser_add, 1)
    print("Added export-html parser")
else:
    print("ERROR: target_parser not found")

# 3. Добавляем обработчик в main()
target_main = '''        if args.command == "render-outputs":
            res = render_outputs(args.case)
            _emit(
                res,
                args.json,
                lambda r: f"RENDER OUTPUTS: OK ({len(r['rendered_files'])} files, {len(r['artifacts_integrity'])} hashes)",
            )
            return 0'''

main_add = target_main + '''

        if args.command == "export-html":
            res = export_html(args.case, out_file=args.out)
            _emit(
                res,
                args.json,
                lambda r: f"EXPORT HTML: OK ({r['html_file']})",
            )
            return 0'''

if target_main in text:
    text = text.replace(target_main, main_add, 1)
    print("Added export-html main handler")
else:
    print("ERROR: target_main not found")

cli_path.write_text(text, encoding="utf-8")
print("SUCCESSFULLY_UPDATED_STRATEGIST_CLI")
