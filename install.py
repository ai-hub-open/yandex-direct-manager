#!/usr/bin/env python3
"""
install.py — установка зависимостей скилла yandex-direct-manager.

Использование:
    python install.py

Что делает:
1. Проверяет версию Python (нужен 3.9+)
2. Ставит зависимости из requirements.txt
3. Делает smoke-тест: импортируются ли модули скилла и библиотеки
4. Печатает «всё ок» или конкретную проблему

Безопасно запускать несколько раз — pip install идемпотентен.
"""

import subprocess
import sys
from pathlib import Path


def fail(msg: str, exit_code: int = 1):
    print(f"\n❌ ERROR: {msg}", file=sys.stderr)
    sys.exit(exit_code)


def ok(msg: str):
    print(f"✓ {msg}")


def info(msg: str):
    print(f"  {msg}")


def check_python_version():
    if sys.version_info < (3, 9):
        fail(f"Нужен Python 3.9 или новее. У вас: {sys.version}")
    ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def install_requirements():
    skill_dir = Path(__file__).parent
    req = skill_dir / "requirements.txt"
    if not req.exists():
        fail(f"Не найден {req}")

    info(f"Устанавливаем из {req}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(req)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        fail("pip install не прошёл. Посмотрите ошибку выше.")
    ok("Зависимости установлены")


def smoke_test():
    """Проверяем, что модули скилла и библиотеки импортируются."""
    skill_dir = Path(__file__).parent
    sys.path.insert(0, str(skill_dir))

    failed = []

    for mod in (
        "scripts.preflight",
        "scripts.wordstat_api",
        "scripts.keyword_helper",
        "scripts.forecast_cpc",
        "scripts.generate_ads_xlsx",
        "scripts.generate_media_plan",
        "scripts.setup_yandex_direct_mcp",
        "scripts.credentials",
        "scripts.validate_assets",
        "scripts.prompt_templates",
    ):
        try:
            __import__(mod)
            ok(mod)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{mod}: {e}")

    # openpyxl и python-docx нужны только для файлов-артефактов маркетолога.
    # Кампания заливается через MCP, поэтому их отсутствие — не отказ установки.
    try:
        import openpyxl  # noqa: F401
        ok(f"openpyxl {openpyxl.__version__}")
    except Exception:  # noqa: BLE001
        print("   openpyxl не установлен — ads.xlsx будет сохранён как CSV")

    try:
        import docx  # noqa: F401
        ok("python-docx")
    except Exception:  # noqa: BLE001
        print("   python-docx не установлен — медиаплан будет сохранён как Markdown")

    if failed:
        print("\n⚠️  Некоторые модули не загрузились:", file=sys.stderr)
        for f in failed:
            print(f"  - {f}", file=sys.stderr)
        fail("Smoke-тест не прошёл. Попробуйте: pip install --upgrade -r requirements.txt")


def main():
    # Когда stdout перенаправлен в пайп (агент запускает скрипт через subprocess,
    # редирект в файл, CI), Python берёт кодировку локали — на Windows это cp1251,
    # где нет '✓'/'⚠'/эмодзи. Без этого печать падала UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    print("=" * 60)
    print("yandex-direct-manager — установка")
    print("=" * 60)
    print()

    check_python_version()
    install_requirements()
    print()
    print("Smoke-тест:")
    smoke_test()

    print()
    print("=" * 60)
    print("✅ Установка завершена.")
    print("=" * 60)
    print()
    print("Что дальше:")
    print("1. Откройте агентную среду (Claude Desktop, Cowork или другую)")
    print("2. Скажите: «Хочу запустить рекламу в Яндекс Директе на ...»")
    print("3. Агент поведёт по шагам; ключи API понадобятся на этапе подключения")
    print("   кабинета — до этого всё работает без них.")
    print()
    print("Подробности: README.md в этой папке.")


if __name__ == "__main__":
    main()
