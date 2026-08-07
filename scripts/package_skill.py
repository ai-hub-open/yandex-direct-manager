#!/usr/bin/env python3
"""
package_skill.py — упаковывает папку yandex-direct-manager в .skill файл для распространения.

.skill — это просто ZIP с расширением .skill, структура:
    yandex-direct-manager/             ← папка скилла внутри zip
    ├── SKILL.md
    ├── README.md
    ├── requirements.txt
    ├── install.py
    ├── scripts/
    └── references/

Исключаются:
    - __pycache__/, *.pyc, node_modules/
    - .DS_Store, .git*
    - evals/ (тестовые промпты — только для разработчиков скилла)
    - assets/, yd-campaign-*/ (это рабочие папки кампаний, не скилл)

Использование:
    # Стандартное (создаст yandex-direct-manager.skill рядом с папкой скилла)
    python -m scripts.package_skill

    # Указать путь к скиллу
    python -m scripts.package_skill --skill-path C:\\path\\to\\yandex-direct-manager

    # Указать куда сохранить .skill
    python -m scripts.package_skill --output C:\\Users\\me\\Downloads

    # С версией в имени файла
    python -m scripts.package_skill --version 1.0.0
"""

import argparse
import fnmatch
import re
import sys
import zipfile
from pathlib import Path


# Что исключаем при упаковке
EXCLUDE_DIRS = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "dist",
}
EXCLUDE_GLOBS = {"*.pyc", "*.pyo", "*.swp", "*.bak", "*.tmp"}
EXCLUDE_FILES = {".DS_Store", ".gitignore", "Thumbs.db"}

# Секреты. .skill рассылается коллегам и клиентам, поэтому файлы с ключами
# не просто пропускаются — их наличие останавливает упаковку (см. scan_secrets).
# .gitignore защищает только git; до этой проверки упаковку не защищало ничто.
SECRET_FILES = {".env", ".env.local", ".env.production", ".envrc", ".netrc",
                "credentials.json", "secrets.json", "service-account.json"}
SECRET_GLOBS = {".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "*.keystore"}
# Шаблоны без значений — их наличие в пакете нужно и безопасно.
SECRET_ALLOWLIST = {".env.example", ".env.sample", ".env.template", ".env.dist"}

# Паттерны живых ключей для проверки содержимого. Длина обязательна, чтобы
# плейсхолдеры из документации ("sk-...", "r8_...") не давали ложных срабатываний.
SECRET_PATTERNS = [
    ("OpenAI",            re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("Anthropic",         re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("Yandex OAuth",      re.compile(r"\by0_[A-Za-z0-9_-]{20,}")),
    ("Yandex Cloud API",  re.compile(r"\bAQVN[A-Za-z0-9_-]{20,}")),
    ("Replicate",         re.compile(r"\br8_[A-Za-z0-9]{20,}")),
    ("GitHub",            re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Google API",        re.compile(r"\bAIza[A-Za-z0-9_-]{30,}")),
]
SCAN_SUFFIXES = {".py", ".md", ".txt", ".json", ".sh", ".bat", ".yml", ".yaml", ".cfg", ".ini", ""}

# Только в корне скилла исключаем
ROOT_EXCLUDE_DIRS = {"tests"}  # тесты нужны только разработчикам; assets/ поставляем —
                               # схема 08_creatives.json нужна скиллу в рантайме


def is_secret_name(name: str) -> bool:
    """True, если имя файла выглядит как хранилище секретов (шаблоны — не в счёт)."""
    if name in SECRET_ALLOWLIST:
        return False
    if name in SECRET_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_GLOBS)


def scan_secrets(skill_path: Path) -> list:
    """Ищет секреты до упаковки: по имени файла и по содержимому.

    Возвращает список человекочитаемых находок. Непустой список = упаковка
    останавливается: молча выкинуть файл нельзя, автор должен узнать, что
    в рабочей папке лежит ключ.
    """
    findings = []
    for fp in skill_path.rglob("*"):
        if not fp.is_file():
            continue
        rel = fp.relative_to(skill_path)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue

        if is_secret_name(fp.name):
            findings.append(f"{rel} — файл с секретами (по имени)")
            continue

        if fp.suffix.lower() not in SCAN_SUFFIXES:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS:
            m = pattern.search(text)
            if m:
                shown = m.group(0)[:8] + "…"
                findings.append(f"{rel} — похоже на ключ {label} ({shown})")
                break
    return findings


def should_exclude(rel_path: Path) -> bool:
    """Проверяет нужно ли исключить файл."""
    parts = rel_path.parts

    # Секреты — вторая линия обороны на случай, если scan_secrets обошли.
    if is_secret_name(rel_path.name):
        return True

    # Любая часть пути совпадает с EXCLUDE_DIRS
    if any(part in EXCLUDE_DIRS for part in parts):
        return True

    # Корневые папки скилла исключаемые (parts[0] = название скилла, parts[1] = первая подпапка)
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True

    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    if any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS):
        return True

    # Исключаем рабочие папки кампаний если случайно попали внутрь
    if any(part.startswith("vk-campaign-") for part in parts):
        return True

    return False


def validate_skill(skill_path: Path) -> tuple:
    """Минимальная валидация перед упаковкой."""
    if not skill_path.exists():
        return False, f"Папка не существует: {skill_path}"
    if not skill_path.is_dir():
        return False, f"Не папка: {skill_path}"

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, f"Не найден SKILL.md в {skill_path}"

    # Проверка YAML frontmatter
    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "SKILL.md должен начинаться с YAML frontmatter (---)"

    # Достаём frontmatter
    fm_match = re.match(r"^---\n(.+?)\n---", content, re.DOTALL)
    if not fm_match:
        return False, "SKILL.md frontmatter не закрыт `---`"

    fm = fm_match.group(1)
    if not re.search(r"^name:\s*\S+", fm, re.MULTILINE):
        return False, "В SKILL.md frontmatter нет `name:`"
    if not re.search(r"^description:\s*\S+", fm, re.MULTILINE):
        return False, "В SKILL.md frontmatter нет `description:`"

    # README рекомендуется
    if not (skill_path / "README.md").exists():
        print("⚠ README.md не найден (не критично, но рекомендуется)")

    return True, "OK"


def package_skill(skill_path: Path, output_dir: Path = None, version: str = None) -> Path:
    """Упаковывает папку скилла в .skill (zip-архив)."""
    skill_path = skill_path.resolve()

    valid, msg = validate_skill(skill_path)
    if not valid:
        print(f"❌ Валидация не прошла: {msg}", file=sys.stderr)
        return None
    print(f"✅ Валидация прошла")

    secrets = scan_secrets(skill_path)
    if secrets:
        print("\n❌ УПАКОВКА ОСТАНОВЛЕНА — в папке скилла найдены секреты:", file=sys.stderr)
        for s in secrets:
            print(f"     - {s}", file=sys.stderr)
        print(
            "\n   .skill рассылается коллегам и клиентам — ключи из него не отозвать.\n"
            "   Убери файлы из папки скилла (держи .env вне репозитория или в другом каталоге)\n"
            "   и запусти упаковку заново.",
            file=sys.stderr,
        )
        return None
    print("✅ Секретов в папке не найдено")

    skill_name = "yandex-direct-manager"  # фиксировано: не зависит от имени рабочей папки
    if output_dir is None:
        output_dir = skill_path.parent
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{skill_name}-{version}.skill" if version else f"{skill_name}.skill"
    output_file = output_dir / filename

    added_count = 0
    skipped_count = 0
    skipped_list = []

    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in skill_path.rglob("*"):
            if not fp.is_file():
                continue
            arcname = Path(skill_name) / fp.relative_to(skill_path)
            if should_exclude(arcname):
                skipped_count += 1
                skipped_list.append(str(arcname))
                continue
            zf.write(fp, arcname)
            added_count += 1

    size_kb = output_file.stat().st_size / 1024
    print(f"\n📦 Готово: {output_file}")
    print(f"   Размер: {size_kb:.1f} KB")
    print(f"   Файлов: {added_count} (пропущено: {skipped_count})")

    if skipped_list and len(skipped_list) <= 20:
        print(f"\n   Пропущенные:")
        for s in skipped_list:
            print(f"     - {s}")

    return output_file


def main():
    # Когда stdout перенаправлен в пайп (агент запускает скрипт через subprocess,
    # `package.sh > log.txt`, CI), Python берёт кодировку локали — на Windows это
    # cp1251, где нет '✅'/'📦'. Без этого печать падала UnicodeEncodeError
    # до начала работы.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Упаковщик скилла в .skill файл")
    parser.add_argument(
        "--skill-path",
        default=None,
        help="Путь к папке скилла (по умолчанию — папка где лежит скрипт)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Куда сохранить .skill (по умолчанию — папка рядом со скиллом)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Версия для имени файла (например 1.0.0 → yandex-direct-manager-1.0.0.skill)",
    )
    args = parser.parse_args()

    if args.skill_path:
        # resolve() обязателен: package.sh передаёт "--skill-path .", и без него
        # skill_path.name пустой — подсказки ниже печатали "python /install.py".
        skill_path = Path(args.skill_path).resolve()
    else:
        # По умолчанию — папка-родитель этого скрипта
        skill_path = Path(__file__).parent.parent.resolve()

    output_dir = Path(args.output) if args.output else None

    print(f"📦 Упаковка скилла: {skill_path.name}")
    print(f"   Источник: {skill_path}")
    if output_dir:
        print(f"   Назначение: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir=output_dir, version=args.version)

    if result is None:
        sys.exit(1)

    print(f"\n✨ Установка для коллеги:")
    print(f"   1. Распакуй {result.name} как обычный zip")
    print(f"   2. Положи папку {skill_path.name}/ куда удобно (например ~/Documents/)")
    print(f"   3. Запусти один раз: python {skill_path.name}/install.py")
    print(f"   4. Открой Cowork — скилл будет доступен")
    sys.exit(0)


if __name__ == "__main__":
    main()
