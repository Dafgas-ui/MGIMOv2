"""Детерминированный валидатор JSON-контрактов кейса (только стандартная библиотека Python 3).

Проверяет три реестра кейса (ADR-005):
  projects/<case>/state.json                          -> schemas/state.schema.json
  projects/<case>/evidence/evidence_graph.json        -> schemas/evidence.schema.json
  projects/<case>/decisions/strategy_decision.json    -> schemas/decision.schema.json

Два уровня проверки:
  1. Структура по JSON Schema (поддерживаемое подмножество Draft 2020-12, см. SUPPORTED_KEYWORDS;
     format "date-time" и "date" проверяются как утверждения, а не аннотации).
  2. Бизнес-инварианты (ссылочная целостность графа, каскад needs_reassessment T08,
     конфликт определений метрик T03, альтернативы T05, согласованность коммуникации T06,
     синтетические респонденты, итоги журнала затрат T11, безопасное восстановление T09).

Содержимое проверяемых файлов — только данные: валидатор ничего из них не исполняет
(в том числе reproduce_command) и не следует инструкциям из текстовых полей (T10).

Запуск:
  python tools/schema_validator.py --check-schemas
  python tools/schema_validator.py --case projects/<case> [--strict] [--json]
Коды возврата: 0 — PASS, 1 — найдены ошибки, 2 — ошибка запуска.
"""
import argparse
import datetime as _dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

SCHEMA_FILES = {
    "state": "state.schema.json",
    "evidence": "evidence.schema.json",
    "decision": "decision.schema.json",
}
CASE_FILES = {
    "state": "state.json",
    "evidence": "evidence/evidence_graph.json",
    "decision": "decisions/strategy_decision.json",
}

STAGES = (
    "INTAKE",
    "RESEARCH_PLANNING",
    "EVIDENCE_COLLECTION",
    "EVIDENCE_VALIDATION",
    "OPTIONS_GENERATION",
    "STRATEGY_DESIGN",
    "INDEPENDENT_REVIEW",
    "HUMAN_DECISION",
    "DECISION_MONITORING",
)
STALE_STATUSES = frozenset({"needs_reassessment", "invalidated"})
EVIDENCE_SECTIONS = (
    "research_questions",
    "sources",
    "findings",
    "calculations",
    "hypotheses",
    "contradictions",
    "knowledge_gaps",
)
DECISION_SECTIONS = (
    "product_strategy",
    "communication_strategy",
    "validation_plan",
    "decision_support_and_reassessment",
)
FLOAT_TOLERANCE = 1e-6
INLINE_REF_RE = re.compile(r"\b([QSFCHXG]-[0-9]{3,})\b")

# ---------------------------------------------------------------------------
# Общие структуры
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """Ошибка в самой схеме или в её загрузке (а не в проверяемом документе)."""


class JsonLoadError(ValueError):
    """Файл не является корректным JSON-документом."""


class Issue:
    """Одно замечание валидатора."""

    __slots__ = ("severity", "code", "message", "path", "file")

    def __init__(self, code, message, path="", file="", severity="ERROR"):
        self.code = code
        self.message = message
        self.path = path
        self.file = file
        self.severity = severity

    def to_dict(self):
        return {"severity": self.severity, "code": self.code, "file": self.file,
                "path": self.path or "/", "message": self.message}

    def __str__(self):
        where = f"[{self.file}] " if self.file else ""
        return f"{self.severity} {where}{self.path or '/'} {self.code}: {self.message}"

    __repr__ = __str__


def errors_of(issues):
    return [i for i in issues if i.severity == "ERROR"]


def warnings_of(issues):
    return [i for i in issues if i.severity == "WARNING"]


def codes(issues, severity="ERROR"):
    """Множество кодов замечаний заданной серьёзности (None — любые)."""
    return {i.code for i in issues if severity is None or i.severity == severity}


# ---------------------------------------------------------------------------
# Загрузка JSON
# ---------------------------------------------------------------------------


def _no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise JsonLoadError(f"дублирующийся ключ '{key}' в объекте")
        obj[key] = value
    return obj


def _reject_constant(name):
    raise JsonLoadError(f"недопустимое значение {name} (не входит в стандарт JSON)")


def parse_json_text(text):
    """Строгий разбор JSON: запрещены дубли ключей и NaN/Infinity."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as e:
        raise JsonLoadError(f"некорректный JSON: {e.msg} (строка {e.lineno}, столбец {e.colno})") from None


def load_json(path):
    """Читает JSON-файл в UTF-8 (BOM допускается)."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise JsonLoadError(f"файл не в кодировке UTF-8: {e}") from None
    except OSError as e:
        raise JsonLoadError(f"не удалось прочитать файл: {e}") from None
    return parse_json_text(text)


def artifact_sha256(path):
    """SHA-256 файла с нормализацией CRLF -> LF (устойчиво к git autocrlf на разных ОС)."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Движок JSON Schema (подмножество Draft 2020-12)
# ---------------------------------------------------------------------------

SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "examples", "default",
    "type", "enum", "const",
    "properties", "required", "additionalProperties",
    "items", "minItems", "maxItems", "uniqueItems",
    "minLength", "maxLength", "pattern", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "anyOf", "oneOf", "allOf",
})
JSON_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
SUPPORTED_FORMATS = frozenset({"date-time", "date"})
_NON_NEGATIVE_INT_KEYWORDS = ("minItems", "maxItems", "minLength", "maxLength")
_NUMBER_KEYWORDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")

_DATE_TIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """RFC 3339 date-time (обязателен часовой пояс) -> aware datetime или None."""
    if not isinstance(value, str):
        return None
    m = _DATE_TIME_RE.match(value)
    if not m:
        return None
    date_part, time_part, frac, tz = m.groups()
    frac = (frac or "0")[:6].ljust(6, "0")
    tz = "+00:00" if tz in ("Z", "z") else tz
    try:
        return _dt.datetime.fromisoformat(f"{date_part}T{time_part}.{frac}{tz}")
    except ValueError:
        return None


def _format_ok(value, fmt):
    if fmt == "date-time":
        return parse_datetime(value) is not None
    if fmt == "date":
        if not _DATE_RE.match(value):
            return False
        try:
            _dt.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return True


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type(value, json_type):
    if json_type == "object":
        return isinstance(value, dict)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "null":
        return value is None
    if not _is_number(value):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if json_type == "integer":
        return isinstance(value, int) or value.is_integer()
    return json_type == "number"


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _esc(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def resolve_ref(root, ref):
    """Разрешает локальную ссылку вида '#/$defs/name'."""
    if not isinstance(ref, str) or not ref.startswith("#"):
        raise SchemaError(f"поддерживаются только локальные $ref ('#/...'), получено: {ref!r}")
    node = root
    pointer = ref[1:]
    if pointer in ("", "/"):
        return root
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise SchemaError(f"не удалось разрешить $ref {ref}")
    return node


def validate_instance(instance, schema, root=None):
    """Проверяет документ по схеме. Возвращает список (json_pointer, сообщение)."""
    out = []
    _validate(instance, schema, schema if root is None else root, "", out, 0)
    return out


def _validate(inst, schema, root, path, out, depth):
    if schema is True:
        return
    if schema is False:
        out.append((path, "значение запрещено схемой"))
        return
    if not isinstance(schema, dict):
        raise SchemaError(f"подсхема по пути {path or '/'} должна быть объектом")
    if depth > 100:
        raise SchemaError("слишком глубокая рекурсия $ref")

    if "$ref" in schema:
        _validate(inst, resolve_ref(root, schema["$ref"]), root, path, out, depth + 1)

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(inst, t) for t in types):
            out.append((path, f"ожидался тип {'|'.join(types)}, получен {_type_name(inst)}"))
            return

    if "enum" in schema and not any(_canon(inst) == _canon(e) for e in schema["enum"]):
        allowed = ", ".join(_canon(e) for e in schema["enum"])
        out.append((path, f"значение {_canon(inst)} не входит в допустимые: {allowed}"))
    if "const" in schema and _canon(inst) != _canon(schema["const"]):
        out.append((path, f"значение {_canon(inst)} должно быть равно {_canon(schema['const'])}"))

    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            out.append((path, f"строка короче {schema['minLength']} символов"))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            out.append((path, f"строка длиннее {schema['maxLength']} символов"))
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            out.append((path, f"строка {inst!r} не соответствует шаблону {schema['pattern']}"))
        if "format" in schema and not _format_ok(inst, schema["format"]):
            out.append((path, f"строка {inst!r} не соответствует формату {schema['format']}"))

    if _is_number(inst):
        if "minimum" in schema and inst < schema["minimum"]:
            out.append((path, f"значение {inst} меньше минимума {schema['minimum']}"))
        if "maximum" in schema and inst > schema["maximum"]:
            out.append((path, f"значение {inst} больше максимума {schema['maximum']}"))
        if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
            out.append((path, f"значение {inst} должно быть больше {schema['exclusiveMinimum']}"))
        if "exclusiveMaximum" in schema and inst >= schema["exclusiveMaximum"]:
            out.append((path, f"значение {inst} должно быть меньше {schema['exclusiveMaximum']}"))

    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            out.append((path, f"массив содержит {len(inst)} элемент(ов), минимум {schema['minItems']}"))
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            out.append((path, f"массив содержит {len(inst)} элемент(ов), максимум {schema['maxItems']}"))
        if schema.get("uniqueItems") is True:
            seen = set()
            for i, item in enumerate(inst):
                c = _canon(item)
                if c in seen:
                    out.append((f"{path}/{i}", f"повторяющийся элемент {c} (uniqueItems)"))
                seen.add(c)
        if "items" in schema:
            for i, item in enumerate(inst):
                _validate(item, schema["items"], root, f"{path}/{i}", out, depth + 1)

    if isinstance(inst, dict):
        for key in schema.get("required", []):
            if key not in inst:
                out.append((path, f"отсутствует обязательное поле '{key}'"))
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in inst.items():
            child = f"{path}/{_esc(key)}"
            if key in props:
                _validate(value, props[key], root, child, out, depth + 1)
            elif additional is False:
                out.append((child, f"недопустимое поле '{key}' (additionalProperties: false)"))
            elif isinstance(additional, dict):
                _validate(value, additional, root, child, out, depth + 1)

    for sub in schema.get("allOf", []):
        _validate(inst, sub, root, path, out, depth + 1)

    if "anyOf" in schema:
        branches = []
        for sub in schema["anyOf"]:
            errs = []
            _validate(inst, sub, root, path, errs, depth + 1)
            if not errs:
                branches = None
                break
            branches.append(errs)
        if branches is not None:
            best = min(branches, key=len)
            out.append((path, f"не соответствует ни одному варианту anyOf; ближайший: {best[0][1]}"))

    if "oneOf" in schema:
        matched = 0
        for sub in schema["oneOf"]:
            errs = []
            _validate(inst, sub, root, path, errs, depth + 1)
            if not errs:
                matched += 1
        if matched != 1:
            out.append((path, f"должно соответствовать ровно одному варианту oneOf (совпало: {matched})"))


# ---------------------------------------------------------------------------
# Самопроверка файлов схем
# ---------------------------------------------------------------------------


def check_schema_document(schema, name="schema"):
    """Проверяет, что схема корректна и использует только поддерживаемое подмножество."""
    errors = []
    if not isinstance(schema, dict):
        return [f"{name}: корень схемы должен быть объектом"]
    if schema.get("$schema") != DRAFT_2020_12:
        errors.append(f"{name}: $schema должен быть {DRAFT_2020_12}")
    if not isinstance(schema.get("$id"), str) or not schema.get("$id"):
        errors.append(f"{name}: отсутствует $id")
    if schema.get("type") != "object":
        errors.append(f"{name}: корневой type должен быть 'object'")
    _walk_schema(schema, "#", schema, errors, name)
    return errors


def _walk_schema(node, ptr, root, errors, name):
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        errors.append(f"{name}: {ptr}: подсхема должна быть объектом или boolean")
        return
    for key in node:
        if key not in SUPPORTED_KEYWORDS:
            errors.append(f"{name}: {ptr}: неподдерживаемое ключевое слово '{key}'")

    if "type" in node:
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not types or any(t not in JSON_TYPES for t in types) or len(set(types)) != len(types):
            errors.append(f"{name}: {ptr}: некорректный type {node['type']!r}")
    if "enum" in node:
        enum = node["enum"]
        if not isinstance(enum, list) or not enum:
            errors.append(f"{name}: {ptr}: enum должен быть непустым массивом")
        elif len({_canon(e) for e in enum}) != len(enum):
            errors.append(f"{name}: {ptr}: enum содержит повторы")
    if "pattern" in node:
        try:
            re.compile(node["pattern"])
        except (re.error, TypeError) as e:
            errors.append(f"{name}: {ptr}: некорректный pattern: {e}")
    if "format" in node and node["format"] not in SUPPORTED_FORMATS:
        errors.append(f"{name}: {ptr}: неподдерживаемый format {node['format']!r}")
    for kw in _NON_NEGATIVE_INT_KEYWORDS:
        if kw in node and (not isinstance(node[kw], int) or isinstance(node[kw], bool) or node[kw] < 0):
            errors.append(f"{name}: {ptr}: {kw} должен быть неотрицательным целым")
    for kw in _NUMBER_KEYWORDS:
        if kw in node and not _is_number(node[kw]):
            errors.append(f"{name}: {ptr}: {kw} должен быть числом")
    if "uniqueItems" in node and not isinstance(node["uniqueItems"], bool):
        errors.append(f"{name}: {ptr}: uniqueItems должен быть boolean")
    if "$ref" in node:
        try:
            resolve_ref(root, node["$ref"])
        except SchemaError as e:
            errors.append(f"{name}: {ptr}: {e}")

    props = node.get("properties")
    if props is not None and not isinstance(props, dict):
        errors.append(f"{name}: {ptr}: properties должен быть объектом")
        props = None
    if "required" in node:
        req = node["required"]
        if not isinstance(req, list) or not all(isinstance(r, str) for r in req) or len(set(req)) != len(req):
            errors.append(f"{name}: {ptr}: required должен быть массивом уникальных строк")
        elif node.get("additionalProperties") is False:
            for r in req:
                if r not in (props or {}):
                    errors.append(f"{name}: {ptr}: обязательное поле '{r}' не описано в properties")
    if props is not None and "additionalProperties" not in node:
        errors.append(f"{name}: {ptr}: объектная подсхема должна явно задавать additionalProperties")

    if props:
        for key, sub in props.items():
            _walk_schema(sub, f"{ptr}/properties/{_esc(key)}", root, errors, name)
    defs = node.get("$defs")
    if defs is not None:
        if not isinstance(defs, dict):
            errors.append(f"{name}: {ptr}: $defs должен быть объектом")
        else:
            for key, sub in defs.items():
                _walk_schema(sub, f"{ptr}/$defs/{_esc(key)}", root, errors, name)
    if "items" in node:
        if not isinstance(node["items"], (dict, bool)):
            errors.append(f"{name}: {ptr}: items должен быть схемой (Draft 2020-12)")
        else:
            _walk_schema(node["items"], f"{ptr}/items", root, errors, name)
    if isinstance(node.get("additionalProperties"), dict):
        _walk_schema(node["additionalProperties"], f"{ptr}/additionalProperties", root, errors, name)
    elif "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
        errors.append(f"{name}: {ptr}: additionalProperties должен быть boolean или схемой")
    for kw in ("anyOf", "oneOf", "allOf"):
        if kw in node:
            subs = node[kw]
            if not isinstance(subs, list) or not subs:
                errors.append(f"{name}: {ptr}: {kw} должен быть непустым массивом")
                continue
            for i, sub in enumerate(subs):
                _walk_schema(sub, f"{ptr}/{kw}/{i}", root, errors, name)


def check_schemas(schemas_dir=None):
    """Самопроверка schemas/*.schema.json. Возвращает список ошибок (пустой — PASS)."""
    schemas_dir = Path(schemas_dir or SCHEMAS_DIR)
    errors = []
    ids = {}
    for kind, filename in SCHEMA_FILES.items():
        path = schemas_dir / filename
        if not path.is_file():
            errors.append(f"{filename}: файл схемы не найден в {schemas_dir}")
            continue
        try:
            schema = load_json(path)
        except JsonLoadError as e:
            errors.append(f"{filename}: {e}")
            continue
        errors.extend(check_schema_document(schema, filename))
        sid = schema.get("$id") if isinstance(schema, dict) else None
        if sid:
            if sid in ids:
                errors.append(f"{filename}: $id совпадает с {ids[sid]}")
            ids[sid] = filename
    return errors


_SCHEMA_CACHE = {}


def load_schemas(schemas_dir=None):
    """Загружает и самопроверяет схемы; результат кэшируется по каталогу."""
    key = str(Path(schemas_dir or SCHEMAS_DIR).resolve())
    if key not in _SCHEMA_CACHE:
        errs = check_schemas(key)
        if errs:
            raise SchemaError("схемы не прошли самопроверку: " + "; ".join(errs))
        _SCHEMA_CACHE[key] = {kind: load_json(Path(key) / f) for kind, f in SCHEMA_FILES.items()}
    return _SCHEMA_CACHE[key]


def schema_issues(doc, kind, file="", schemas=None):
    schema = (schemas or load_schemas())[kind]
    return [Issue("SCHEMA", msg, path, file) for path, msg in validate_instance(doc, schema)]


# ---------------------------------------------------------------------------
# Вспомогательные функции для бизнес-инвариантов (защитное чтение)
# ---------------------------------------------------------------------------


def _list(doc, key):
    value = doc.get(key) if isinstance(doc, dict) else None
    return value if isinstance(value, list) else []


def _iter_nodes(doc, key):
    for i, node in enumerate(_list(doc, key)):
        if isinstance(node, dict):
            yield i, node


def _iter_refs(node, key):
    for j, ref in enumerate(_list(node, key)):
        if isinstance(ref, str):
            yield j, ref


def _dict(doc, key):
    value = doc.get(key) if isinstance(doc, dict) else None
    return value if isinstance(value, dict) else None


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _norm(value):
    return " ".join(value.lower().split()) if isinstance(value, str) else ""


def _stage_index(stage):
    return STAGES.index(stage) if stage in STAGES else None


def _unique(seq):
    seen, out = set(), []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _unsafe_path(path):
    if not isinstance(path, str) or not path or "\x00" in path:
        return True
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        return True
    return ".." in re.split(r"[/\\]", path)


_REFUSAL_PREFIX_RE = re.compile(
    r"^(?:осознанный\s+отказ(?:\s+от)?|отказываемся(?:\s+от)?|отказ(?:\s+от)?|"
    r"не\s+(?:делаем|строим|обещаем|включаем|запускаем|поддерживаем|реализуем|"
    r"предлагаем|вводим|добавляем|используем|даём|даем|гарантируем|фокусируемся\s+на)|"
    r"без|we\s+do\s+not(?:\s+build|\s+offer|\s+promise|\s+provide)?|no)\s+",
    re.IGNORECASE,
)
_REFUSAL_STOPWORDS = frozenset({
    "и", "в", "во", "на", "по", "с", "со", "к", "ко", "от", "до", "из", "за", "у", "о", "об", "для", "при", "без",
    "или", "а", "но", "не", "ни", "же", "ли", "бы", "как", "что", "это", "этот", "эта", "эти", "этом", "этого",
    "этой", "этих", "тот", "та", "те", "все", "всё", "вся", "весь", "всех", "свой", "свои", "своих", "наш", "наши",
    "наших", "любой", "любые", "рамках", "текущем", "текущего", "данном", "данного", "первом", "этапе", "квартале",
    "релизе", "версии", "продукта", "сервиса", "пользователя", "пользователей", "пользователем", "клиента",
    "клиентов", "сценария", "сценариев", "сценарий", "настройки", "настройку", "настройкой", "настройте",
    "условий", "условия", "условиями", "подписки", "подписку", "подпиской", "приложения", "приложении",
    "работы", "работу", "решения", "решение", "задачи", "задачу", "функции", "функцию", "возможности",
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "without", "and", "or", "by", "this",
})
_WORD_RE = re.compile(r"[a-zа-яё0-9]{3,}", re.IGNORECASE)


def _stem_token(w):
    w = w.lower().replace("ё", "е")
    return w[:6] if len(w) > 6 else w


def _refusal_clauses_and_stems(refusal_text):
    """Разбивает формулировку отказа на смысловые клаузы и их ключевые основы (без префикса 'не делаем')."""
    text = refusal_text.strip()
    while True:
        new_text = _REFUSAL_PREFIX_RE.sub("", text).strip(" .,;:!—–-\"'«»")
        if new_text == text:
            break
        text = new_text
    # Отсекаем уточняющие оговорки вида «без настройки ...» / «при условии ...»
    text = re.split(r"\s+(?:без|при\s+условии|если|кроме|за\s+исключением)\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    clauses = re.split(r"\s+(?:и|или|а\s+также|либо)\s+|[,;]", text, flags=re.IGNORECASE)
    result = []
    for clause in clauses:
        clean = _REFUSAL_PREFIX_RE.sub("", clause.strip()).strip(" .,;:!—–-\"'«»")
        words = [w.lower().replace("ё", "е") for w in _WORD_RE.findall(clean)]
        sig = [_stem_token(w) for w in words if w not in _REFUSAL_STOPWORDS and len(w) >= 4]
        if sig:
            result.append((clean.lower().replace("ё", "е"), _unique(sig)))
    return result


def _text_promises_refusal(promise_text, refusal_text):
    """True, если текст обещания/сообщения обещает то, что запрещено в explicit_refusals (T06)."""
    if not isinstance(promise_text, str) or not isinstance(refusal_text, str):
        return False
    norm_p = " ".join(promise_text.lower().replace("ё", "е").split())
    # Если в самом сообщении явно сказано, что мы этого НЕ делаем / без этого — это честное предупреждение
    p_words = [w.lower().replace("ё", "е") for w in _WORD_RE.findall(norm_p)]
    p_stems = {_stem_token(w) for w in p_words}
    for phrase, stems in _refusal_clauses_and_stems(refusal_text):
        if len(phrase) >= 5 and phrase in norm_p:
            idx_pos = norm_p.find(phrase)
            prefix = norm_p[max(0, idx_pos - 25):idx_pos]
            if not re.search(r"\b(?:не|без|нет|никогда|no|not|without)\b", prefix):
                return True
        if not stems:
            continue
        matched = [s for s in stems if s in p_stems]
        need = 1 if len(stems) == 1 else min(2, len(stems))
        if len(matched) >= need:
            # Проверяем, не стоят ли совпавшие слова под отрицанием ('не обещаем кэшбэк', 'без кэшбэка')
            negated = False
            for s in matched:
                for m in re.finditer(re.escape(s), norm_p):
                    prefix = norm_p[max(0, m.start() - 25):m.start()]
                    if re.search(r"\b(?:не|без|нет|никогда|отказ\w*|no|not|without)\b", prefix):
                        negated = True
                        break
            if not negated:
                return True
    return False


class EvidenceIndex:
    """Индекс узлов графа доказательств: id -> (раздел, позиция, узел)."""

    def __init__(self, graph):
        self.nodes = {}
        self.duplicates = []
        for section in EVIDENCE_SECTIONS:
            for i, node in _iter_nodes(graph, section):
                nid = node.get("id")
                if not isinstance(nid, str):
                    continue
                if nid in self.nodes:
                    self.duplicates.append((nid, section, i))
                else:
                    self.nodes[nid] = (section, i, node)
        self._stale = {}

    def __contains__(self, nid):
        return nid in self.nodes

    def section(self, nid):
        return self.nodes[nid][0] if nid in self.nodes else None

    def node(self, nid):
        return self.nodes[nid][2] if nid in self.nodes else None

    def parents(self, nid):
        section = self.section(nid)
        if section == "findings":
            return [r for _, r in _iter_refs(self.node(nid), "source_refs")]
        if section in ("calculations", "hypotheses"):
            return [r for _, r in _iter_refs(self.node(nid), "depends_on")]
        return []

    def is_self_stale(self, nid):
        section, node = self.section(nid), self.node(nid)
        if section == "sources":
            return node.get("verification_level") == "revoked"
        if section in ("findings", "calculations", "hypotheses"):
            return node.get("validity_status") in STALE_STATUSES
        return False

    def is_stale(self, nid, _visiting=None):
        """Узел устарел сам или через любого предка (транзитивно, T08)."""
        if nid in self._stale:
            return self._stale[nid]
        if nid not in self.nodes:
            return False
        visiting = _visiting if _visiting is not None else set()
        if nid in visiting:
            return False
        visiting.add(nid)
        result = self.is_self_stale(nid) or any(self.is_stale(p, visiting) for p in self.parents(nid))
        visiting.discard(nid)
        self._stale[nid] = result
        return result


# ---------------------------------------------------------------------------
# Инварианты графа доказательств
# ---------------------------------------------------------------------------


def evidence_invariants(graph, file=CASE_FILES["evidence"]):
    issues = []
    if not isinstance(graph, dict):
        return issues
    idx = EvidenceIndex(graph)

    def add(code, msg, path, severity="ERROR"):
        issues.append(Issue(code, msg, path, file, severity))

    for nid, section, i in idx.duplicates:
        add("DUPLICATE_ID", f"идентификатор {nid} уже используется в графе", f"/{section}/{i}/id")

    def check_refs(section, i, node, key, allowed):
        for j, ref in _iter_refs(node, key):
            path = f"/{section}/{i}/{key}/{j}"
            if ref not in idx:
                add("REF_MISSING", f"ссылка {ref} не найдена в графе доказательств", path)
            elif idx.section(ref) not in allowed:
                add("REF_WRONG_TYPE", f"ссылка {ref} указывает на раздел {idx.section(ref)}, "
                                      f"допустимы: {', '.join(sorted(allowed))}", path)

    def check_stale(section, i, node, key):
        if node.get("validity_status") != "valid":
            return
        stale = _unique(r for _, r in _iter_refs(node, key) if r in idx and idx.is_stale(r))
        if stale:
            add("T08_STALE_DEPENDENCY",
                f"узел {node.get('id')} помечен valid, но опирается на устаревшие или отозванные основания "
                f"{', '.join(stale)}; требуется needs_reassessment или invalidated",
                f"/{section}/{i}/validity_status")

    for i, q in _iter_nodes(graph, "research_questions"):
        check_refs("research_questions", i, q, "answer_refs", {"findings", "calculations", "hypotheses"})
        check_refs("research_questions", i, q, "blocking_gap_refs", {"knowledge_gaps"})
        if q.get("status") == "answered" and not list(_iter_refs(q, "answer_refs")):
            add("Q_ANSWER_WITHOUT_EVIDENCE", f"вопрос {q.get('id')} отмечен answered без answer_refs",
                f"/research_questions/{i}/answer_refs")
        if q.get("status") == "blocked_by_gap" and not list(_iter_refs(q, "blocking_gap_refs")):
            add("Q_BLOCKED_WITHOUT_GAP", f"вопрос {q.get('id')} отмечен blocked_by_gap без blocking_gap_refs",
                f"/research_questions/{i}/blocking_gap_refs")

    for i, s in _iter_nodes(graph, "sources"):
        if s.get("verification_level") == "content_verified" and not _nonblank(s.get("content_hash")):
            add("SOURCE_HASH_MISSING", f"источник {s.get('id')} отмечен content_verified без content_hash",
                f"/sources/{i}/content_hash")

    for i, f in _iter_nodes(graph, "findings"):
        check_refs("findings", i, f, "source_refs", {"sources"})
        check_stale("findings", i, f, "source_refs")

    for i, c in _iter_nodes(graph, "calculations"):
        check_refs("calculations", i, c, "depends_on", {"findings", "calculations"})
        check_stale("calculations", i, c, "depends_on")

    for i, h in _iter_nodes(graph, "hypotheses"):
        check_refs("hypotheses", i, h, "depends_on", {"sources", "findings", "calculations"})
        check_stale("hypotheses", i, h, "depends_on")
        if h.get("kind") == "synthetic_insight" and h.get("is_synthetic_respondent") is not True:
            add("SYNTHETIC_FLAG_MISMATCH",
                f"гипотеза {h.get('id')} имеет kind=synthetic_insight, но is_synthetic_respondent != true",
                f"/hypotheses/{i}/is_synthetic_respondent")
        if h.get("is_synthetic_respondent") is True and h.get("confidence") == "high":
            add("SYNTHETIC_HIGH_CONFIDENCE",
                f"гипотеза {h.get('id')} от модельных респондентов не может иметь confidence=high: "
                f"синтетические ответы не доказывают спрос", f"/hypotheses/{i}/confidence")

    for i, x in _iter_nodes(graph, "contradictions"):
        check_refs("contradictions", i, x, "conflicting_refs", {"sources", "findings"})
        if x.get("resolution_status") in ("explained_by_methodology", "resolved") \
                and not _nonblank(x.get("resolution_note")):
            add("CONTRADICTION_NOTE_MISSING",
                f"противоречие {x.get('id')} со статусом {x.get('resolution_status')} без resolution_note",
                f"/contradictions/{i}/resolution_note")

    issues.extend(_calculation_cycles(graph, idx, file))
    issues.extend(_metric_conflicts(graph, file))
    return issues


def _calculation_cycles(graph, idx, file):
    issues = []
    color = {}

    def visit(nid, trail):
        color[nid] = 1
        for parent in idx.parents(nid):
            if idx.section(parent) != "calculations":
                continue
            if color.get(parent) == 1:
                cycle = trail[trail.index(parent):] + [parent] if parent in trail else [nid, parent]
                sec, i, _ = idx.nodes[nid]
                issues.append(Issue("DEPENDENCY_CYCLE", f"циклическая зависимость расчётов: {' -> '.join(cycle)}",
                                    f"/{sec}/{i}/depends_on", file))
            elif color.get(parent) is None:
                visit(parent, trail + [parent])
        color[nid] = 2

    for _, c in _iter_nodes(graph, "calculations"):
        nid = c.get("id")
        if isinstance(nid, str) and idx.section(nid) == "calculations" and color.get(nid) is None:
            visit(nid, [nid])
    return issues


def _metric_conflicts(graph, file):
    """T03: одна метрика за один период с разным знаменателем/единицей/значением без записи в contradictions."""
    issues = []
    groups = {}
    for i, f in _iter_nodes(graph, "findings"):
        md = f.get("metric_definition")
        if not isinstance(md, dict) or f.get("validity_status") == "invalidated":
            continue
        key = (_norm(md.get("metric_name")), _norm(md.get("period")))
        if key[0]:
            groups.setdefault(key, []).append((i, f, md))
    recorded = [{r for _, r in _iter_refs(x, "conflicting_refs")} for _, x in _iter_nodes(graph, "contradictions")]
    for members in groups.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                (_, fa, ma), (ib, fb, mb) = members[a], members[b]
                diff = []
                if _norm(ma.get("denominator")) != _norm(mb.get("denominator")):
                    diff.append("знаменатель")
                if _norm(ma.get("unit")) != _norm(mb.get("unit")):
                    diff.append("единица измерения")
                va, vb = ma.get("value"), mb.get("value")
                if not diff and _is_number(va) and _is_number(vb) \
                        and not math.isclose(va, vb, rel_tol=1e-9, abs_tol=1e-12):
                    diff.append("значение")
                if not diff:
                    continue
                ida, idb = fa.get("id"), fb.get("id")
                if any(ida in refs and idb in refs for refs in recorded):
                    continue
                issues.append(Issue(
                    "T03_UNRECORDED_METRIC_CONFLICT",
                    f"факты {ida} и {idb} описывают метрику '{ma.get('metric_name')}' за период "
                    f"'{ma.get('period')}' с расхождением ({', '.join(diff)}), но противоречие с обоими "
                    f"идентификаторами не зафиксировано в contradictions",
                    f"/findings/{ib}/metric_definition", file))
    return issues


def validate_evidence_graph(graph, file=CASE_FILES["evidence"], schemas=None):
    return schema_issues(graph, "evidence", file, schemas) + evidence_invariants(graph, file)


# ---------------------------------------------------------------------------
# Инварианты решения
# ---------------------------------------------------------------------------


def decision_invariants(decision, graph, file=CASE_FILES["decision"]):
    issues = []
    if not isinstance(decision, dict):
        return issues
    idx = EvidenceIndex(graph) if isinstance(graph, dict) else None
    used = []  # (ref, path) — ссылки решения на граф для проверки устаревания
    graph_missing_reported = [False]

    def add(code, msg, path, severity="ERROR"):
        issues.append(Issue(code, msg, path, file, severity))

    def check_ref(ref, path, allowed=None, track=True):
        if idx is None:
            if not graph_missing_reported[0]:
                add("GRAPH_MISSING", "решение ссылается на граф доказательств, но evidence_graph.json "
                                     "недоступен — ссылки не проверены", path)
                graph_missing_reported[0] = True
            return False
        if ref not in idx:
            add("REF_MISSING", f"ссылка {ref} не найдена в графе доказательств", path)
            return False
        if allowed and idx.section(ref) not in allowed:
            add("REF_WRONG_TYPE", f"ссылка {ref} указывает на раздел {idx.section(ref)}, "
                                  f"допустимы: {', '.join(sorted(allowed))}", path)
            return False
        if track:
            used.append((ref, path))
        return True

    evidence_sections = {"findings", "calculations", "hypotheses"}
    status = decision.get("decision_status")

    # --- Альтернативы (FR-05, T05)
    raw_alts = _list(decision, "alternatives")
    alts = list(_iter_nodes(decision, "alternatives"))
    if len(raw_alts) < 3:
        add("T05_MIN_ALTERNATIVES", f"рассмотрено {len(raw_alts)} вариант(а), требуется не меньше трёх",
            "/alternatives")
    types = {a.get("option_type") for _, a in alts}
    if "status_quo" not in types:
        add("T05_MISSING_STATUS_QUO", "среди альтернатив нет варианта status_quo («оставить как есть»)",
            "/alternatives")
    if "sunset_or_close" not in types:
        add("T05_MISSING_SUNSET", "среди альтернатив нет варианта sunset_or_close («закрыть направление»)",
            "/alternatives")
    if "strategic_direction" not in types:
        add("T05_NO_STRATEGIC_DIRECTION", "среди альтернатив нет ни одного strategic_direction",
            "/alternatives")
    alt_by_id, titles = {}, {}
    for i, a in alts:
        aid = a.get("id")
        if isinstance(aid, str):
            if aid in alt_by_id:
                add("DUPLICATE_ID", f"идентификатор варианта {aid} повторяется", f"/alternatives/{i}/id")
            else:
                alt_by_id[aid] = a
        title = _norm(a.get("title"))
        if title:
            if title in titles:
                add("T05_DUPLICATE_ALTERNATIVE",
                    f"вариант {aid} дублирует название варианта {titles[title]} — варианты должны "
                    f"быть содержательно разными", f"/alternatives/{i}/title")
            else:
                titles[title] = aid
        objections = _list(a, "strong_objections")
        if not any(_nonblank(o) for o in objections):
            add("T05_NO_OBJECTIONS", f"у варианта {aid} нет сильных возражений (strong_objections пуст)",
                f"/alternatives/{i}/strong_objections")
        for j, ref in _iter_refs(a, "supporting_refs"):
            check_ref(ref, f"/alternatives/{i}/supporting_refs/{j}", evidence_sections)
    selected = [a.get("id") for _, a in alts if a.get("verdict") == "selected"]
    if len(selected) > 1:
        add("T05_MULTIPLE_SELECTED", f"выбрано более одного варианта: {', '.join(map(str, selected))}",
            "/alternatives")

    # --- Полнота разделов вне черновика
    if status in ("audited", "approved_by_human", "needs_reassessment"):
        for section in DECISION_SECTIONS:
            if section not in decision:
                add("DECISION_INCOMPLETE", f"при decision_status={status} обязателен раздел {section}",
                    f"/{section}")

    # --- Продуктовая стратегия (FR-06)
    ps = _dict(decision, "product_strategy")
    capabilities = set()
    if ps is not None:
        sel = ps.get("selected_option_id")
        if isinstance(sel, str):
            if sel not in alt_by_id:
                add("REF_MISSING", f"selected_option_id {sel} не найден среди alternatives",
                    "/product_strategy/selected_option_id")
            elif alt_by_id[sel].get("verdict") != "selected":
                add("STRATEGY_OPTION_NOT_SELECTED",
                    f"стратегия построена на варианте {sel}, но его verdict = {alt_by_id[sel].get('verdict')}",
                    "/product_strategy/selected_option_id")
        for k, cap in _iter_nodes(ps, "key_capabilities"):
            cid = cap.get("id")
            if isinstance(cid, str):
                if cid in capabilities:
                    add("DUPLICATE_ID", f"идентификатор свойства {cid} повторяется",
                        f"/product_strategy/key_capabilities/{k}/id")
                capabilities.add(cid)
        evidence = []
        for j, ref in _iter_refs(ps, "evidence_refs"):
            if check_ref(ref, f"/product_strategy/evidence_refs/{j}", evidence_sections):
                evidence.append(ref)
        disclosed_synthetic, disclosed_any = set(), set()
        for k, assumption in _iter_nodes(ps, "assumptions_and_limits"):
            for j, ref in _iter_refs(assumption, "related_refs"):
                check_ref(ref, f"/product_strategy/assumptions_and_limits/{k}/related_refs/{j}", track=False)
                disclosed_any.add(ref)
                if assumption.get("kind") == "synthetic_respondent_basis":
                    disclosed_synthetic.add(ref)
        link = ps.get("unit_economics_link")
        if isinstance(link, str):
            for ref in _unique(INLINE_REF_RE.findall(link)):
                check_ref(ref, "/product_strategy/unit_economics_link", track=False)
        raw_refusals = _list(ps, "explicit_refusals")
        if not raw_refusals or any(not _nonblank(r) for r in raw_refusals):
            add("T06_EMPTY_EXPLICIT_REFUSAL",
                "product_strategy.explicit_refusals должен содержать непустые формулировки осознанных отказов",
                "/product_strategy/explicit_refusals")
        if idx is not None:
            synthetic = [r for r in evidence if idx.section(r) == "hypotheses"
                         and idx.node(r).get("is_synthetic_respondent") is True]
            real = [r for r in evidence if idx.section(r) in ("findings", "calculations")]
            undisclosed = [r for r in synthetic if r not in disclosed_synthetic]
            if synthetic and not real and undisclosed:
                add("SYNTHETIC_SOLE_BASIS",
                    f"выбранная стратегия опирается только на ответы модельных респондентов "
                    f"({', '.join(undisclosed)}) без реальных фактов F/C и без явной пометки "
                    f"synthetic_respondent_basis в assumptions_and_limits", "/product_strategy/evidence_refs")
            elif undisclosed:
                add("SYNTHETIC_UNDISCLOSED_BASIS",
                    f"в основаниях стратегии присутствуют ответы модельных респондентов "
                    f"({', '.join(undisclosed)}), не задекларированные в assumptions_and_limits "
                    f"с kind=synthetic_respondent_basis", "/product_strategy/assumptions_and_limits")
            plain_hypotheses = [r for r in evidence if idx.section(r) == "hypotheses"
                                and r not in synthetic and r not in disclosed_any]
            if plain_hypotheses:
                add("HYPOTHESIS_BASIS_UNDISCLOSED",
                    f"гипотезы {', '.join(plain_hypotheses)} входят в основания стратегии, но не отражены "
                    f"в assumptions_and_limits", "/product_strategy/assumptions_and_limits", "WARNING")
        comp_types = {c.get("alternative_type") for _, c in _iter_nodes(ps, "competing_alternatives")}
        if not comp_types & {"habitual_free_workaround", "do_nothing"}:
            add("NO_HABITUAL_ALTERNATIVE",
                "среди competing_alternatives нет привычного бесплатного способа или варианта «ничего не делать»",
                "/product_strategy/competing_alternatives", "WARNING")

    # --- Коммуникационная стратегия (FR-07, T06)
    cs = _dict(decision, "communication_strategy")
    if cs is not None:
        if ps is None:
            add("COMM_WITHOUT_PRODUCT_STRATEGY",
                "коммуникационная стратегия задана без продуктовой — обещания не с чем сверить",
                "/communication_strategy")
        check = _dict(cs, "consistency_check")
        if check is None or check.get("is_consistent") is not True:
            add("T06_INCONSISTENT_COMMUNICATION",
                "consistency_check.is_consistent должен быть true: коммуникация не может обещать то, "
                "от чего продукт осознанно отказался", "/communication_strategy/consistency_check/is_consistent")
        refusals = [r for r in (_list(ps, "explicit_refusals") if ps is not None else []) if _nonblank(r)]
        key_msg = cs.get("key_message")
        if _nonblank(key_msg):
            for ref_text in refusals:
                if _text_promises_refusal(key_msg, ref_text):
                    add("T06_PROMISES_EXPLICIT_REFUSAL",
                        f"key_message обещает то, от чего продукт отказался в explicit_refusals ({ref_text!r})",
                        "/communication_strategy/key_message")
                    break
        for k, pp in _iter_nodes(cs, "proof_points"):
            cap = pp.get("product_capability_ref")
            if ps is not None and isinstance(cap, str) and cap not in capabilities:
                add("T06_UNSUPPORTED_PROMISE",
                    f"обещание ссылается на свойство {cap}, которого нет в product_strategy.key_capabilities",
                    f"/communication_strategy/proof_points/{k}/product_capability_ref")
            promise_text = pp.get("promise")
            if _nonblank(promise_text):
                for ref_text in refusals:
                    if _text_promises_refusal(promise_text, ref_text):
                        add("T06_PROMISES_EXPLICIT_REFUSAL",
                            f"обещание в proof_points[{k}] противоречит explicit_refusals ({ref_text!r})",
                            f"/communication_strategy/proof_points/{k}/promise")
                        break
            pp_valid_refs = []
            for j, ref in _iter_refs(pp, "evidence_refs"):
                if check_ref(ref, f"/communication_strategy/proof_points/{k}/evidence_refs/{j}", evidence_sections):
                    pp_valid_refs.append(ref)
            if idx is not None and pp_valid_refs:
                pp_synth = [r for r in pp_valid_refs if idx.section(r) == "hypotheses"
                            and idx.node(r).get("is_synthetic_respondent") is True]
                pp_real = [r for r in pp_valid_refs if idx.section(r) in ("findings", "calculations")]
                if pp_synth and not pp_real:
                    add("SYNTHETIC_PROOF_POINT",
                        f"обещание клиенту в proof_points[{k}] опирается на ответы модельных респондентов "
                        f"({', '.join(pp_synth)}) без реальных фактов F/C",
                        f"/communication_strategy/proof_points/{k}/evidence_refs")
                elif pp_synth:
                    add("SYNTHETIC_PROOF_POINT",
                        f"обещание клиенту в proof_points[{k}] включает ссылку на модельного респондента "
                        f"({', '.join(pp_synth)}); синтетические ответы нельзя использовать как подтверждение обещаний",
                        f"/communication_strategy/proof_points/{k}/evidence_refs")

    # --- Сопровождение решения и пересмотр (T08)
    ds = _dict(decision, "decision_support_and_reassessment")
    flagged = set()
    if ds is not None:
        for key, label in (("commitments", "обязательства"), ("reassessment_triggers", "триггера пересмотра")):
            seen = set()
            for k, item in _iter_nodes(ds, key):
                iid = item.get("id")
                if isinstance(iid, str):
                    if iid in seen:
                        add("DUPLICATE_ID", f"идентификатор {label} {iid} повторяется",
                            f"/decision_support_and_reassessment/{key}/{k}/id")
                    seen.add(iid)
        for k, trigger in _iter_nodes(ds, "reassessment_triggers"):
            for j, ref in _iter_refs(trigger, "watched_refs"):
                check_ref(ref, f"/decision_support_and_reassessment/reassessment_triggers/{k}/watched_refs/{j}",
                          track=False)
        for j, ref in _iter_refs(ds, "affected_by_stale_nodes"):
            check_ref(ref, f"/decision_support_and_reassessment/affected_by_stale_nodes/{j}", track=False)
            flagged.add(ref)
        if status == "approved_by_human" and not list(_iter_nodes(ds, "commitments")):
            add("DECISION_NO_COMMITMENTS", "утверждённое решение не содержит обязательств (commitments)",
                "/decision_support_and_reassessment/commitments")

    if idx is not None:
        stale_used = _unique(r for r, _ in used if idx.is_stale(r))
        if stale_used:
            if status in ("audited", "approved_by_human"):
                add("T08_STALE_DECISION",
                    f"решение со статусом {status} опирается на устаревшие основания {', '.join(stale_used)}; "
                    f"требуется decision_status=needs_reassessment", "/decision_status")
            missing = [r for r in stale_used if r not in flagged]
            if missing:
                add("T08_STALE_NOT_FLAGGED",
                    f"устаревшие основания {', '.join(missing)} не перечислены в affected_by_stale_nodes",
                    "/decision_support_and_reassessment/affected_by_stale_nodes")
        for ref in sorted(flagged):
            if ref in idx and not idx.is_stale(ref):
                add("STALE_LIST_OUTDATED", f"{ref} указан в affected_by_stale_nodes, но в графе актуален",
                    "/decision_support_and_reassessment/affected_by_stale_nodes", "WARNING")
    return issues


def validate_decision(decision, graph, file=CASE_FILES["decision"], schemas=None):
    return schema_issues(decision, "decision", file, schemas) + decision_invariants(decision, graph, file)


# ---------------------------------------------------------------------------
# Инварианты состояния
# ---------------------------------------------------------------------------


def state_invariants(state, file=CASE_FILES["state"]):
    issues = []
    if not isinstance(state, dict):
        return issues

    def add(code, msg, path, severity="ERROR"):
        issues.append(Issue(code, msg, path, file, severity))

    created, updated = parse_datetime(state.get("created_at")), parse_datetime(state.get("updated_at"))
    if created and updated and updated < created:
        add("STATE_TIME_ORDER", "updated_at раньше created_at", "/updated_at")

    pf = _dict(state, "problem_framing") or {}
    wf = _dict(state, "workflow") or {}
    stage = wf.get("current_stage")
    si = _stage_index(stage)

    # T01: после INTAKE задача должна быть поставлена
    if si is not None and si > 0:
        for key in ("clarified_problem", "goal", "decision_recipient"):
            if not _nonblank(pf.get(key)):
                add("T01_FRAMING_INCOMPLETE", f"этап {stage}: поле problem_framing.{key} не заполнено",
                    f"/problem_framing/{key}")

    completed = [s for _, s in _iter_refs(wf, "completed_stages")]
    if si is not None:
        for k, s in _iter_refs(wf, "completed_stages"):
            ci = _stage_index(s)
            if ci is not None and ci >= si:
                add("WORKFLOW_COMPLETED_AHEAD",
                    f"этап {s} отмечен завершённым, но текущий этап {stage} не позже него; "
                    f"при возврате последующие этапы снимаются с completed_stages",
                    f"/workflow/completed_stages/{k}")
        skipped = [s for s in STAGES[:si] if s not in completed]
        if skipped:
            add("WORKFLOW_STAGE_SKIPPED", f"не отмечены завершёнными предшествующие этапы: {', '.join(skipped)}",
                "/workflow/completed_stages", "WARNING")

    prev_to, prev_ts, first = None, None, True
    for k, t in _iter_nodes(wf, "stage_history"):
        path = f"/workflow/stage_history/{k}"
        fr, to, kind = t.get("from_stage"), t.get("to_stage"), t.get("transition_type")
        fi, ti = _stage_index(fr), _stage_index(to)
        if first:
            if kind != "start" or fr is not None:
                add("WORKFLOW_BAD_TRANSITION", "первый переход должен иметь transition_type=start и from_stage=null",
                    path)
        else:
            if kind == "start":
                add("WORKFLOW_BAD_TRANSITION", "transition_type=start допустим только для первого перехода", path)
            if fr != prev_to:
                add("WORKFLOW_HISTORY_BROKEN", f"from_stage={fr} не совпадает с предыдущим to_stage={prev_to}",
                    f"{path}/from_stage")
            if kind == "forward" and fi is not None and ti is not None and ti <= fi:
                add("WORKFLOW_BAD_TRANSITION", f"forward-переход {fr} -> {to} не ведёт вперёд", path)
            if kind == "rollback" and fi is not None and ti is not None and ti > fi:
                add("WORKFLOW_BAD_TRANSITION", f"rollback-переход {fr} -> {to} ведёт вперёд", path)
        ts = parse_datetime(t.get("timestamp"))
        if ts and prev_ts and ts < prev_ts:
            add("WORKFLOW_HISTORY_ORDER", "переходы stage_history идут не в хронологическом порядке",
                f"{path}/timestamp")
        prev_ts = ts or prev_ts
        prev_to = to
        first = False
    if not first and prev_to != stage:
        add("WORKFLOW_HISTORY_MISMATCH", f"последний переход ведёт в {prev_to}, а current_stage = {stage}",
            "/workflow/current_stage")

    awaiting = _dict(wf, "awaiting_human_approval")
    if awaiting is not None:
        if awaiting.get("is_awaiting") is True and not _nonblank(awaiting.get("reason")):
            add("HUMAN_WAIT_NO_REASON", "ожидание решения человека без указания причины",
                "/workflow/awaiting_human_approval/reason")
        if stage == "HUMAN_DECISION" and awaiting.get("is_awaiting") is False:
            add("HUMAN_DECISION_NOT_AWAITING", "этап HUMAN_DECISION, но is_awaiting=false",
                "/workflow/awaiting_human_approval/is_awaiting", "WARNING")

    # T11: журнал затрат
    ledger = _dict(state, "cost_and_usage_ledger") or {}
    step_ids = set()
    duration = tokens = cost = 0
    for k, e in _iter_nodes(ledger, "entries"):
        sid = e.get("step_id")
        if isinstance(sid, str):
            if sid in step_ids:
                add("T11_DUPLICATE_STEP", f"step_id {sid} повторяется в журнале затрат",
                    f"/cost_and_usage_ledger/entries/{k}/step_id")
            step_ids.add(sid)
        duration += e["duration_sec"] if _is_number(e.get("duration_sec")) else 0
        tokens += e["tokens_in"] if _is_number(e.get("tokens_in")) else 0
        tokens += e["tokens_out"] if _is_number(e.get("tokens_out")) else 0
        cost += e["estimated_cost_usd"] if _is_number(e.get("estimated_cost_usd")) else 0
    totals = _dict(ledger, "totals")
    if totals is not None:
        for key, expected in (("total_duration_sec", duration), ("total_tokens", tokens),
                              ("total_estimated_cost_usd", cost)):
            actual = totals.get(key)
            if _is_number(actual) and abs(actual - expected) > FLOAT_TOLERANCE:
                add("T11_TOTALS_MISMATCH", f"totals.{key} = {actual}, а сумма по entries = {round(expected, 6)}",
                    f"/cost_and_usage_ledger/totals/{key}")

    # T07/T09: контрольные точки и восстановление
    cr = _dict(state, "checkpoints_and_recovery") or {}
    last = cr.get("last_completed_operation_id")
    op = _dict(cr, "in_progress_operation")
    if op is not None:
        oid = op.get("operation_id")
        if isinstance(oid, str) and oid == last:
            add("T09_OPERATION_STATE_CONFLICT",
                f"операция {oid} одновременно завершена и выполняется — возобновление приведёт к повтору",
                "/checkpoints_and_recovery/in_progress_operation/operation_id")
        if isinstance(oid, str) and oid in step_ids:
            add("T09_OPERATION_ALREADY_LEDGERED",
                f"незавершённая операция {oid} уже учтена в журнале затрат как выполненная — "
                f"возобновление незаметно повторит платный шаг",
                "/checkpoints_and_recovery/in_progress_operation/operation_id")
        if op.get("is_paid_or_heavy") is True and not _nonblank(op.get("idempotency_key")):
            add("T09_NO_IDEMPOTENCY_KEY", "платная/тяжёлая операция без idempotency_key",
                "/checkpoints_and_recovery/in_progress_operation/idempotency_key", "WARNING")
    if isinstance(last, str) and step_ids and last not in step_ids:
        add("LAST_OPERATION_NOT_IN_LEDGER", f"last_completed_operation_id {last} отсутствует в журнале затрат",
            "/checkpoints_and_recovery/last_completed_operation_id", "WARNING")
    seen_paths = set()
    for k, art in _iter_nodes(cr, "artifacts_integrity"):
        p = art.get("path")
        if isinstance(p, str):
            if _unsafe_path(p):
                add("UNSAFE_PATH", f"путь {p!r} должен быть относительным к каталогу кейса и без '..'",
                    f"/checkpoints_and_recovery/artifacts_integrity/{k}/path")
            norm = p.replace("\\", "/")
            if norm in seen_paths:
                add("DUPLICATE_ARTIFACT", f"артефакт {p} указан повторно",
                    f"/checkpoints_and_recovery/artifacts_integrity/{k}/path", "WARNING")
            seen_paths.add(norm)
    return issues


def validate_state(state, file=CASE_FILES["state"], schemas=None):
    return schema_issues(state, "state", file, schemas) + state_invariants(state, file)


# ---------------------------------------------------------------------------
# Проверка кейса целиком
# ---------------------------------------------------------------------------


def validate_documents(state, graph, decision, schemas=None):
    """Проверка трёх документов в памяти (без файловой системы)."""
    issues = []
    if state is not None:
        issues += validate_state(state, schemas=schemas)
    if graph is not None:
        issues += validate_evidence_graph(graph, schemas=schemas)
    if decision is not None:
        issues += validate_decision(decision, graph, schemas=schemas)
    docs = {k: d for k, d in (("state", state), ("evidence", graph), ("decision", decision)) if isinstance(d, dict)}
    case_ids = {k: d.get("case_id") for k, d in docs.items()}
    if len(set(case_ids.values())) > 1:
        detail = ", ".join(f"{CASE_FILES[k]}={v}" for k, v in case_ids.items())
        issues.append(Issue("CASE_ID_MISMATCH", f"case_id различается между файлами: {detail}", "/case_id"))
    if isinstance(state, dict) and isinstance(decision, dict) \
            and decision.get("decision_status") == "approved_by_human":
        stage = (_dict(state, "workflow") or {}).get("current_stage")
        if stage not in ("HUMAN_DECISION", "DECISION_MONITORING"):
            issues.append(Issue("DECISION_STAGE_MISMATCH",
                                f"решение утверждено человеком, но текущий этап кейса {stage}",
                                "/workflow/current_stage", CASE_FILES["state"]))
    return issues


def validate_case(case_dir, strict=False, schemas=None):
    """Проверяет каталог кейса. strict=True превращает предупреждения в ошибки."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        return [Issue("CASE_DIR_MISSING", f"каталог кейса не найден: {case_dir}")]
    issues, docs, present = [], {}, set()
    for kind, rel in CASE_FILES.items():
        path = case_dir / rel
        if not path.is_file():
            continue
        present.add(kind)
        try:
            docs[kind] = load_json(path)
        except JsonLoadError as e:
            issues.append(Issue("JSON_INVALID", str(e), "", rel))
    if "state" not in present:
        issues.append(Issue("CASE_FILE_MISSING", "отсутствует обязательный файл состояния", "", CASE_FILES["state"]))

    state, graph, decision = docs.get("state"), docs.get("evidence"), docs.get("decision")
    issues += validate_documents(state, graph, decision, schemas)

    if isinstance(state, dict):
        if state.get("case_id") != case_dir.name:
            issues.append(Issue("CASE_DIR_MISMATCH",
                                f"case_id={state.get('case_id')!r} не совпадает с именем каталога {case_dir.name!r}",
                                "/case_id", CASE_FILES["state"], "WARNING"))
        completed = {s for _, s in _iter_refs(_dict(state, "workflow") or {}, "completed_stages")}
        if "RESEARCH_PLANNING" in completed and "evidence" not in present:
            issues.append(Issue("CASE_FILE_MISSING", "этап RESEARCH_PLANNING завершён, но граф доказательств "
                                                     "отсутствует", "", CASE_FILES["evidence"]))
        if "OPTIONS_GENERATION" in completed and "decision" not in present:
            issues.append(Issue("CASE_FILE_MISSING", "этап OPTIONS_GENERATION завершён, но файл решения "
                                                     "отсутствует", "", CASE_FILES["decision"]))
        cr = _dict(state, "checkpoints_and_recovery") or {}
        base = case_dir.resolve()
        for k, art in _iter_nodes(cr, "artifacts_integrity"):
            rel, expected = art.get("path"), art.get("sha256")
            if not isinstance(rel, str) or _unsafe_path(rel) or not isinstance(expected, str):
                continue
            path = f"/checkpoints_and_recovery/artifacts_integrity/{k}"
            target = (case_dir / rel).resolve()
            if base != target and base not in target.parents:
                issues.append(Issue("UNSAFE_PATH", f"путь {rel} выходит за пределы каталога кейса",
                                    f"{path}/path", CASE_FILES["state"]))
                continue
            if not target.is_file():
                issues.append(Issue("INTEGRITY_FILE_MISSING", f"артефакт {rel} не найден",
                                    f"{path}/path", CASE_FILES["state"]))
                continue
            actual = artifact_sha256(target)
            if actual != expected.lower():
                issues.append(Issue("INTEGRITY_MISMATCH",
                                    f"хэш артефакта {rel} изменился после контрольной точки "
                                    f"(записан {expected[:12]}…, фактически {actual[:12]}…)",
                                    f"{path}/sha256", CASE_FILES["state"], "WARNING"))

    if isinstance(graph, dict):
        base = case_dir.resolve()
        repo_root = base
        has_repo = False
        cur = base
        while cur.parent != cur:
            if (cur / "AGENTS.md").is_file():
                repo_root = cur
                has_repo = True
                break
            cur = cur.parent

        for i, s in _iter_nodes(graph, "sources"):
            loc = s.get("location")
            if not isinstance(loc, str) or not loc.strip():
                continue
            if loc.startswith("http://") or loc.startswith("https://"):
                continue

            target = None
            loc_norm = loc.replace("\\", "/").strip()
            case_resolved = case_dir.resolve()

            # 1. Явный контракт для внешних/общих источников репозитория
            is_shared = loc_norm.startswith(("shared/", "external/"))
            if is_shared:
                if loc_norm.startswith("shared/"):
                    prefix_dir = "shared"
                    subpath = loc_norm[len("shared/"):].lstrip("/")
                else:
                    prefix_dir = "external"
                    subpath = loc_norm[len("external/"):].lstrip("/")

                # Определение разрешённого корня для общих источников:
                # В репозитории: repo_root / prefix_dir.
                # При переносе кейса за пределы репозитория:
                # разрешённым корнем считается локальный каталог case_dir / prefix_dir.
                if has_repo:
                    allowed_root = (repo_root / prefix_dir).resolve()
                else:
                    allowed_root = (case_dir / prefix_dir).resolve()

                cand = (allowed_root / subpath).resolve()
                try:
                    cand.relative_to(allowed_root)
                    is_inside = True
                except ValueError:
                    is_inside = False

                if not is_inside:
                    issues.append(Issue("SOURCE_PATH_OUTSIDE_ALLOWED_ROOT",
                                        f"путь общего источника {loc} выходит за пределы разрешённого каталога {prefix_dir}",
                                        f"/sources/{i}/location", CASE_FILES["evidence"]))
                elif not cand.is_file():
                    issues.append(Issue("SOURCE_FILE_MISSING",
                                        f"файл общего источника {loc} не найден",
                                        f"/sources/{i}/location", CASE_FILES["evidence"]))
                else:
                    target = cand
            else:
                # 2. Локальные источники кейса: разрешение строго привязано к проверяемому case_dir
                cand_paths = []
                parts = [p for p in loc_norm.split("/") if p]
                if len(parts) >= 3 and parts[0] == "projects":
                    # 'projects/<case_id>/<rel_path>' -> разрешаем '<rel_path>' внутри case_dir
                    cand_paths.append((case_dir / "/".join(parts[2:])).resolve())
                elif len(parts) >= 2 and parts[0] in (case_dir.name, graph.get("case_id")):
                    # '<case_id>/<rel_path>' -> разрешаем '<rel_path>' внутри case_dir
                    cand_paths.append((case_dir / "/".join(parts[1:])).resolve())

                # Прямой относительный путь внутри case_dir (например, 'sources/...')
                cand_paths.append((case_dir / loc_norm).resolve())

                inside_candidates = []
                for cp in cand_paths:
                    # Защита от path traversal: кандидат обязан находиться внутри case_dir
                    try:
                        cp.relative_to(case_resolved)
                        inside_candidates.append(cp)
                    except ValueError:
                        continue
                    if cp.is_file():
                        target = cp
                        break

                if target is None:
                    if not inside_candidates:
                        issues.append(Issue("SOURCE_PATH_OUTSIDE_CASE",
                                            f"путь источника {loc} выходит за пределы каталога кейса",
                                            f"/sources/{i}/location", CASE_FILES["evidence"]))
                    else:
                        issues.append(Issue("SOURCE_FILE_MISSING",
                                            f"файл источника {loc} не найден",
                                            f"/sources/{i}/location", CASE_FILES["evidence"]))

            if target is not None:
                expected = s.get("content_hash")
                if expected:
                    actual = "sha256:" + artifact_sha256(target)
                    if actual != expected.lower():
                        issues.append(Issue("SOURCE_HASH_MISMATCH",
                                            f"хэш источника {s.get('id')} ({loc}) не совпадает с content_hash: "
                                            f"ожидался {expected}, вычислен {actual}",
                                            f"/sources/{i}/content_hash", CASE_FILES["evidence"], "WARNING"))
    if strict:
        for issue in issues:
            if issue.severity == "WARNING":
                issue.severity = "ERROR"
                issue.message = "[strict] " + issue.message
    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_stdout():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="schema_validator.py",
        description="Детерминированная проверка JSON-схем и файлов кейса (только стандартная библиотека).")
    parser.add_argument("--check-schemas", action="store_true", help="самопроверка schemas/*.schema.json")
    parser.add_argument("--case", metavar="PATH", help="каталог кейса projects/<case>")
    parser.add_argument("--schemas-dir", metavar="PATH", default=str(SCHEMAS_DIR), help="каталог схем")
    parser.add_argument("--strict", action="store_true", help="предупреждения считаются ошибками")
    parser.add_argument("--json", action="store_true", help="машиночитаемый вывод результата проверки кейса")
    args = parser.parse_args(argv)
    _configure_stdout()

    if not args.check_schemas and not args.case:
        parser.print_usage(sys.stderr)
        print("ошибка: укажите --check-schemas и/или --case PATH", file=sys.stderr)
        return 2

    schema_errors = check_schemas(args.schemas_dir)
    if args.check_schemas or schema_errors:
        if not args.json:
            print(f"SCHEMA CHECK: {'FAIL' if schema_errors else 'PASS'} ({len(SCHEMA_FILES)} schemas)")
            for e in schema_errors:
                print(f"  - {e}")
        elif schema_errors or not args.case:
            print(json.dumps({"schema_check": "FAIL" if schema_errors else "PASS", "errors": schema_errors},
                             ensure_ascii=False, indent=2))
    if schema_errors:
        return 1
    if not args.case:
        return 0

    try:
        issues = validate_case(args.case, strict=args.strict, schemas=load_schemas(args.schemas_dir))
    except SchemaError as e:
        print(f"ошибка схем: {e}", file=sys.stderr)
        return 2
    errs, warns = errors_of(issues), warnings_of(issues)
    status = "FAIL" if errs else "PASS"
    if args.json:
        print(json.dumps({"case": str(args.case), "status": status,
                          "errors": [i.to_dict() for i in errs],
                          "warnings": [i.to_dict() for i in warns]}, ensure_ascii=False, indent=2))
    else:
        print(f"CASE CHECK: {status} ({args.case}: {len(errs)} errors, {len(warns)} warnings)")
        for issue in errs + warns:
            print(f"  - {issue}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
