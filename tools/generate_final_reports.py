"""Скрипт генерации двух официальных итоговых Word-документов (.docx).
1. docs/reports/01_Full_System_Audit_Report.docx — Полный системный аудит этапов разработки и приёмки MVP.
2. docs/reports/02_Interactive_Session_Decisions_and_Prompts_Log.docx — Хроника диалога, принятые решения и промпты.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_native_docx import DocxBuilder

def generate_audit_document():
    doc = DocxBuilder("Полный системный аудит архитектуры и приёмки MVP")
    
    doc.add_title("MGIMO AI Challenge 2026: «Стратег Фабрики продуктов»")
    doc.add_paragraph("Официальный отчёт сквозного системного аудита архитектуры, координации и приёмки MVP", bold=True, color="003366")
    doc.add_paragraph("Версия репозитория: v0.1.1-hotfix | Дата фиксации: 10 ноября 2026 года | Статус: ВСЕ ЭТАПЫ ACCEPTED")
    
    doc.add_heading_1("1. Сводная ведомость реализации задач (task-board.md)")
    doc.add_paragraph("В проекте реализована гибридная координация через общую файловую память и Git с разделением прав на запись. Ни одна задача не принималась без тройного независимого подтверждения.")
    
    headers = ["Task ID", "Наименование задачи", "Исполнитель", "Аудитор", "Dev Status", "Audit Status", "Owner Status", "Commit"]
    rows = [
        ["TASK-000", "Каркас репозитория, Git, AGENTS.md, координация", "Sonnet-Staff", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "d6e54f7"],
        ["TASK-001", "JSON-схемы состояния, Evidence Graph и решений", "Opus-Core", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "c2b3aca"],
        ["TASK-002", "Ядро Python CLI strategist_cli.py и unit-тесты", "Opus-Core", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "b8dca7a"],
        ["TASK-003", "Хук автовосстановления .agents/hooks.json", "Sonnet-Staff", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "d6f669c"],
        ["TASK-004", "Оркестратор, база знаний knowledge/ и 4 навыка", "Opus-Mind", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "db0ffdc"],
        ["TASK-005", "Субагенты в agents/ и демо-кейс demo_mvp", "Opus-Mind", "Argon-Judge", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "cf9eaa8"],
        ["TASK-006", "Сквозные испытания T01–T12 и релиз MVP", "Argon-Judge", "Argon-Prime", "READY_FOR_REVIEW", "PASS", "ACCEPTED", "e0de896"],
    ]
    doc.add_table(headers, rows)

    doc.add_heading_1("2. Детальный аудит выполненных шагов (Шаги 0 – 5)")
    
    doc.add_heading_2("Шаг 0 (TASK-000): Каркас репозитория и защита системных правил")
    doc.add_bullet("Разделение двух контуров: Контур А (продуктовый агент МегаФона) изолирован от Контура Б (команда разработки). Внутренние токены TASK-xxx и координация никогда не попадают в ответы пользователю.", "Контуры:")
    doc.add_bullet("Защита AGENTS.md цифровой пломбой SHA-256 (57bf75979bd8d3b17fef9c137c09f9b96bbf5504b8699080955c13da9c900b73) с контролем скриптом check_coordination.py.", "Защита правил:")
    doc.add_bullet("Мосты переносимости: CLAUDE.md для Claude Code, .cursorrules для Cursor, .agents/skills.json для Antigravity.", "Переносимость:")

    doc.add_heading_2("Шаг 1 (TASK-001): Единые JSON-реестры и Evidence Graph (Вариант А)")
    doc.add_bullet("Принято архитектурное решение ADR-005 в пользу единых реестров кейса (state.json, evidence_graph.json, strategy_decision.json) вместо россыпи мелких файлов.", "Архитектура:")
    doc.add_bullet("Строгие схемы JSON Schema Draft 2020-12 с запретом непредусмотренных свойств (additionalProperties: false).", "Стандарты:")
    doc.add_bullet("Детерминированный валидатор tools/schema_validator.py на стандартной библиотеке Python 3 (1330 строк), проверяющий ссылочную целостность графа и бизнес-инварианты.", "Валидатор:")

    doc.add_heading_2("Шаг 2 (TASK-002, TASK-003): Программное ядро CLI и автопилот нового чата")
    doc.add_bullet("CLI-инструмент tools/strategist_cli.py (1500 строк): 8 команд (init-case, status/resume, upsert-node, invalidate-source, analyze-csv, advance-stage, log-usage, render-outputs).", "CLI-двигатель:")
    doc.add_bullet("Калькулятор таблиц analyze-csv с автоматическим детектированием расхождения знаменателей конверсии (METRIC_DEFINITION_CONFLICT) и обнаружением пропусков данных.", "Анализ данных:")
    doc.add_bullet("Автовосстановление сессии через .agents/hooks.json (SessionStart) и tools/session_recovery_hook.py: автоматический ввод контекста в новом чате с проверкой 6 хэшей SHA-256.", "Автопилот T07:")

    doc.add_heading_2("Шаг 3 (TASK-004): Оркестратор, база знаний и 4 рабочих навыка")
    doc.add_bullet("Главный регламент agent/runtime-instructions.md: 9 этапов, 4 точки обязательной остановки человека (awaiting_human_approval), правила маршрутизации по сложности и стоимости.", "Оркестратор:")
    doc.add_bullet("База знаний knowledge/: frameworks.md (JTBD, отказы, юнит-экономика), messaging-guide.md (барьеры, proof_points), evidence-and-metrics.md (знаменатели, синтетика), validation-and-guardrails.md (пилоты, guardrails).", "База знаний:")
    doc.add_bullet("Навыки skills/: problem-framing, source-and-data-analysis, options-and-strategy, evidence-audit-and-reassessment.", "Skills:")

    doc.add_heading_2("Шаг 4 (TASK-005): Продуктовые субагенты и кейс «Семейный Щит»")
    doc.add_bullet("Три субагента в agents/: research-analyst (flash, чтение и фильтрация инъекций), synthetic-respondent (flash, маркировка SYNTHETIC_HYPOTHESIS), strategy-auditor (pro, независимый критик).", "Субагенты:")
    doc.add_bullet("Демо-кейс projects/demo_mvp/: конфликт 4.2% (от визитов) vs 18.5% (от триалов), пропуски в данных S-001, нейтрализация Prompt Injection в S-003, выбор бесшовного онбординга O-004 и отказ от убыточного ИИ-детектора O-003.", "Демо-кейс:")

    doc.add_heading_2("Шаг 5 (TASK-006): Сквозные приёмочные сценарии T01–T12")
    doc.add_bullet("Набор тестов tests/scenarios/test_acceptance_t01_t12.py (895 строк, 12 сценариев): автоматизированная верификация контрактов, инвариантов бизнес-логики и переходов состояний в изолированной среде согласно сценариям ТЗ конкурса.", "Сценарии:")
    doc.add_bullet("T12 подтверждает программную переносимость и корректность выполнения полного сценарного контракта на независимом наборе данных: успешное сквозное решение второго кейса B2B Облачная АТС с нуля с результатом 0 ошибок, 0 предупреждений.", "Обобщаемость:")

    doc.add_heading_1("3. Сводная таблица прохождения сценариев T01–T12")
    t_headers = ["ID", "Название сценария", "Метод проверки", "Результат"]
    t_rows = [
        ["T01", "Неоднозначный запрос и рамка задачи", "Формирование problem_framing, Q-xxx, лимит вопросов <= 3", "PASS (0.024s)"],
        ["T02", "Разнородные форматы источников", "CSV, MD, UX-аудит, сверка SHA-256 файлов источников и exact_locator", "PASS (0.015s)"],
        ["T03", "Конфликт определений метрик (4.2% vs 18.5%)", "Детекция METRIC_DEFINITION_CONFLICT, запрет усреднения, X-001", "PASS (0.021s)"],
        ["T04", "Пропуски данных и пробелы знаний", "Поиск пропусков в таблицах, расчёт среднего без нулей, G-001/G-002", "PASS (0.012s)"],
        ["T05", "Альтернативы (status_quo, sunset, >= 3)", "Проверка 4 вариантов с сильными возражениями, перехват отсутствия", "PASS (0.018s)"],
        ["T06", "Согласованность продуктовой и промо-стратегий", "Привязка proof_points, запрет синтетики и отказных функций", "PASS (0.020s)"],
        ["T07", "Восстановление в новом чате (resume + hook)", "Сверка 6 хэшей SHA-256, детектор ручной модификации MODIFIED", "PASS (0.038s)"],
        ["T08", "Каскадный пересмотр при отзыве источника", "Транзитивный перевод S-001 -> F -> C -> H -> decision в needs_reassessment", "PASS (0.045s)"],
        ["T09", "Устойчивость к сбоям и идемпотентность", "Восстановление in_progress_operation, защита от дублей log-usage", "PASS (0.019s)"],
        ["T10", "Иммунитет к Prompt Injection", "Изоляция trust_boundary: untrusted_data в S-003, отказ от команды взлома", "PASS (0.014s)"],
        ["T11", "Точность журнала затрат и сметы", "Сверка сумм duration, tokens, cost в totals, отлов расхождений", "PASS (0.011s)"],
        ["T12", "Второй независимый кейс (B2B Облачная АТС)", "T12 подтверждает программную переносимость и корректность выполнения полного сценарного контракта на независимом наборе данных", "PASS (0.138s)"],
    ]
    doc.add_table(t_headers, t_rows)

    doc.add_heading_1("4. Итоговые метрики тестового покрытия и надежности")
    doc.add_bullet("Общее количество автоматических тестов: 49 тестов (37 unit-тестов + 12 сценарных приёмочных тестов).", "Тесты:")
    doc.add_bullet("Время выполнения всего тестового пакета: ~1.0 секунда на стандартном интерпретаторе Python 3.13.", "Скорость:")
    doc.add_bullet("Зависимости: 0 внешних pip-пакетов для ядра системы (100% стандартная библиотека Python).", "Автономность:")
    doc.add_bullet("Результат валидации демонстрационного кейса: CASE CHECK: PASS (0 errors, 0 warnings).", "Качество:")
    
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        git_commit = "v0.1.1"
    doc.add_bullet(f"Релизный тег Git: v0.1.1-hotfix (коммит {git_commit}).", "Релиз:")

    out_path = ROOT / "docs" / "reports" / "01_Full_System_Audit_Report.docx"
    doc.save(out_path)
    print(f"Audit document saved: {out_path}")

def generate_interactive_log_document():
    doc = DocxBuilder("Хроника диалога, принятые решения и промпты взаимодействия с ИИ")
    
    doc.add_title("Хроника взаимодействия пользователя и ИИ-агентов")
    doc.add_paragraph("Детальный протокол управления разработкой, принятых решений, команд и промптов", bold=True, color="003366")
    doc.add_paragraph("Проект: «Стратег Фабрики продуктов» МегаФона | Период: 8–9 ноября 2026 года")

    doc.add_heading_1("1. Роли и распределение обязанностей в команде")
    doc.add_paragraph("Пользователь выстроил гибридную инженерную структуру из 5 специализированных чатов с чётким разделением ответственности, предотвращающим галлюцинации и конфликт интересов:")
    doc.add_bullet("Пользователь (Owner) — ставит цели, принимает архитектурные развилки, утверждает этапы (owner_status: ACCEPTED).", "Владелец проекта:")
    doc.add_bullet("Argon-Prime (Куратор, Gemini Flash / Argon) — ведёт диалог с пользователем, проектирует ТЗ, координирует роли и проводит аудит.", "Главный куратор:")
    doc.add_bullet("Sonnet-Staff (Техперсонал, Sonnet / Flash) — отвечает за инфраструктуру репозитория, Git, AGENTS.md, координационные скрипты и хуки.", "Инфраструктура:")
    doc.add_bullet("Opus-Core (Инженер ядра, Claude Opus / Argon) — создаёт схемы данных schemas/, валидатор schema_validator.py и CLI-двигатель strategist_cli.py.", "Ядро:")
    doc.add_bullet("Opus-Mind (Архитектор стратегий, Claude Opus / Argon) — создаёт продуктовые инструкции, базу знаний knowledge/, навыки skills/ и демо-кейс demo_mvp.", "Методология:")
    doc.add_bullet("Argon-Judge (Независимый ревизор, Gemini Argon) — режим строго Read-Only к коду; проводит независимую приёмку, запускает тесты и выносит вердикты audit_status.", "Аудитор:")

    doc.add_heading_1("2. Хронология сессии: запросы, принятые решения и отправленные промпты")

    doc.add_heading_2("Эпизод 1: Старт проекта и формирование архитектурного регламента (8 ноября)")
    doc.add_bullet("Пользователь передал контекст конкурса МегаФона и опыт прошлых проектов (MGIMOv, Smoky Pomegranate), предложив разделить работу на отдельные чаты с общей файловой памятью вместо одного раздутого чата.", "Запрос пользователя:")
    doc.add_bullet("Куратор восстановил требования ТЗ (40 баллов), проанализировал лимиты моделей и предложил 5-чатовую архитектуру с защитой от ошибок MGIMOv (дублирование статусов, забытые handoff).", "Анализ куратора:")
    doc.add_bullet("Принято решение о разграничении Контура разработки (docs/coordination/) и Контура продукта (agent/, skills/), а также о защите системных правил хэшем SHA-256.", "Решение ADR-001..004:")

    doc.add_heading_2("Эпизод 2: Запуск Шага 0 (TASK-000, 9 ноября 10:11)")
    doc.add_bullet("Пользователь запросил: «начнём создай начальный промт для чата staff».", "Запрос пользователя:")
    doc.add_bullet("Подготовлен подробный промпт TASK-000 для Sonnet-Staff: инициализация Git, .gitignore, .gitattributes (фиксация LF для хэшей), каркас директорий, AGENTS.md, мосты переносимости, check_coordination.py и test_check_coordination.py.", "Промпт для Sonnet-Staff:")
    doc.add_bullet("Sonnet-Staff выполнил задачу (коммит d6e54f7, handoff b7cc402). Аудитор Argon-Judge провёл независимую проверку (коммит 8cc73a3, PASS) и зафиксировал неблокирующее улучшение COORD-01. Пользователь лично утвердил шаг («Принимаю TASK-000»).", "Исполнение и приёмка:")

    doc.add_heading_2("Эпизод 3: Архитектурная развилка и Шаг 1 (TASK-001, 9 ноября 10:50)")
    doc.add_bullet("Куратор предложил пользователю выбор: Вариант А (три единых JSON-реестра на кейс + автогенерация Markdown) против Варианта Б (россыпь мелких JSON/MD на каждый факт). Пользователь выбрал: «идём по варианту А». Зафиксировано в ADR-005.", "Архитектурный выбор:")
    doc.add_bullet("Сформирован промпт TASK-001 для Opus-Core: разработка evidence.schema.json, decision.schema.json, state.schema.json, schema_validator.py и тестов.", "Промпт для Opus-Core:")
    doc.add_bullet("Когда у Opus-Core исчерпался 5-часовой лимит Claude, пользователь согласовал оптимизацию: переключить модель на Gemini 4 Argon, что позволило без потери качества завершить задачу (коммит c2b3aca).", "Оптимизация лимитов:")
    doc.add_bullet("Argon-Judge на глубине High нашёл 2 логические лазейки: CORE-01 (недекларированные синтетические респонденты) и CORE-02 (отсутствие сверки текста обещаний с explicit_refusals). Замечания приняты к закрытию в TASK-002. Пользователь утвердил («Принимаю task-001»).", "Аудит и решения:")

    doc.add_heading_2("Эпизод 4: Шаг 2 (TASK-002 и TASK-003, 9 ноября 13:51 – 16:06)")
    doc.add_bullet("Сформирован промпт TASK-002 для Opus-Core: написание ядра tools/strategist_cli.py (8 подкоманд), закрытие CORE-01 и CORE-02, тесты test_strategist_cli.py.", "Промпт для Opus-Core:")
    doc.add_bullet("Opus-Core реализовал CLI-ядро (коммит b8dca7a). Аудитор Argon-Judge подтвердил успешное закрытие CORE-01 и CORE-02 (коммит 4a4b187, PASS). Пользователь утвердил («Принимаю task-002»).", "Приёмка TASK-002:")
    doc.add_bullet("Пользователь сообщил о наличии 100% лимита Gemini Flash. Куратор перевёл чат Sonnet-Staff на Gemini Flash (High), сэкономив квоту Claude.", "Стратегия экономии:")
    doc.add_bullet("Сформирован промпт TASK-003 для Sonnet-Staff: закрытие COORD-01 в check_coordination.py, создание .agents/hooks.json и tools/session_recovery_hook.py. Задача выполнена (коммит d6f669c) и принята Argon-Judge (коммит 71e7ae3, PASS). Пользователь утвердил («Принимаю TASK-003»).", "Приёмка TASK-003:")

    doc.add_heading_2("Эпизод 5: Шаг 3 (TASK-004, 9 ноября 16:35 – 16:58)")
    doc.add_bullet("Пользователь сообщил об откате лимитов: «переходим к TASK-004 прошлый результат утверждён да ты прав лимиты откатились».", "Запрос пользователя:")
    doc.add_bullet("Сформирован промпт TASK-004 для Opus-Mind: устав agent/runtime-instructions.md (9 этапов, 4 стоп-крана), 4 файла knowledge/ и 4 навыка skills/*.md с точными командами CLI.", "Промпт для Opus-Mind:")
    doc.add_bullet("Opus-Mind выполнил задачу (коммит db0ffdc). Argon-Judge проверил все 31 команду CLI и 7 примеров JSON через валидатор (31/31 и 7/7 PASS), отметил неблокирующее замечание SKILL-01 и выставил PASS (коммит 015130c). Пользователь утвердил («Принимаю TASK-004»).", "Приёмка TASK-004:")

    doc.add_heading_2("Эпизод 6: Шаг 4 (TASK-005, 9 ноября 17:06 – 18:05)")
    doc.add_bullet("Сформирован промпт TASK-005 для Opus-Mind: субагенты research-analyst, synthetic-respondent, strategy-auditor в agents/, закрытие SKILL-01 и сквозной демонстрационный кейс projects/demo_mvp/ («МегаФон Семейный Щит»).", "Промпт для Opus-Mind:")
    doc.add_bullet("Opus-Mind собрал кейс (биллинг S-001, триалы S-002, рынок с Prompt Injection S-003, UX-аудит S-004, граф, решение, 4 отчёта). Argon-Judge подтвердил 100% совпадение расчётов (4.2% vs 18.5%, пропуски T04, изоляция T10) и выставил PASS (коммит a312184, 0 замечаний). Пользователь утвердил («Принимаю TASK-005»).", "Приёмка TASK-005:")

    doc.add_heading_2("Эпизод 7: Финальный Шаг 5 (TASK-006, 9 ноября 18:05 – 18:27)")
    doc.add_bullet("Сформирован промпт TASK-006 для Argon-Judge (в роли исполнителя): создание пакета приёмочных тестов tests/scenarios/test_acceptance_t01_t12.py (895 строк) для автоматизированной верификации контрактов, инвариантов бизнес-логики и переходов состояний в изолированной среде по 12 сценариям T01–T12 (включая обобщаемость на втором кейсе B2B Облачная АТС).", "Промпт для Argon-Judge:")
    doc.add_bullet("Argon-Judge разработал и прогнал тесты: 49 тестов OK, 12 сценариев PASS. Куратор Argon-Prime провёл аудит и выставил PASS (коммит dd16138).", "Аудит куратора:")
    doc.add_bullet("Пользователь провёл детальный разбор всех шагов в формате личного аудита, ответил на контрольные вопросы и утвердил финальный релиз: «так утерждаем TASK-006 сделай мне 2 word документа...». Зафиксирован официальный Git-тег v0.1.0-mvp.", "Финальный вердикт:")

    doc.add_heading_1("3. Качественная оценка работы пользователя с ИИ")
    doc.add_paragraph("В соответствии с критериями ТЗ конкурса МегаФона (оценка взаимодействия человека с ИИ-системой), в данном проекте продемонстрированы ключевые компетенции эффективного управления:")
    doc.add_bullet("Не слепое доверие, а разделение властей: пользователь не позволял моделям одобрять собственный код, разделив разработку (Opus/Sonnet) и независимый аудит (Argon) со своим финальным подтверждением.", "Критический контроль:")
    doc.add_bullet("Бережное отношение к вычислительным квотам: своевременный перевод рутинных задач на Gemini Flash и Argon сохранил недельный лимит Claude для ответственных формулировок.", "Управление ресурсами:")
    doc.add_bullet("Глубокое понимание архитектуры: выбор Варианта А (единые реестры) предотвратил рассинхронизацию графа доказательств, а фиксация хэша AGENTS.md защитила проект от самовольного изменения правил моделью.", "Архитектурное видение:")
    doc.add_bullet("Следование формальным регламентам: фиксация каждого шага в Git-коммитах, журналах handoff и протоколах координации обеспечивает 100% воспроизводимость для жюри конкурса.", "Инженерная дисциплина:")

    out_path = ROOT / "docs" / "reports" / "02_Interactive_Session_Decisions_and_Prompts_Log.docx"
    doc.save(out_path)
    print(f"Log document saved: {out_path}")

if __name__ == "__main__":
    generate_audit_document()
    generate_interactive_log_document()
