"""Пакет сквозных приёмочных испытаний T01–T12 (tests/scenarios)."""
import sys
from pathlib import Path


def load_tests(loader, standard_tests, pattern):
    scenarios_dir = Path(__file__).resolve().parent
    pat = pattern or "test*.py"
    top_dir = str(scenarios_dir.parent)
    standard_tests.addTests(loader.discover(start_dir=str(scenarios_dir), pattern=pat, top_level_dir=top_dir))
    # При запуске `python -m unittest discover -s tests` подключаем также tests/unit
    argv_norm = [a.replace("\\", "/").rstrip("/") for a in sys.argv]
    if "tests" in argv_norm:
        unit_dir = scenarios_dir.parent / "unit"
        if unit_dir.is_dir():
            if str(unit_dir) not in sys.path:
                sys.path.insert(0, str(unit_dir))
            standard_tests.addTests(loader.discover(start_dir=str(unit_dir), pattern=pat, top_level_dir=str(unit_dir)))
    return standard_tests
