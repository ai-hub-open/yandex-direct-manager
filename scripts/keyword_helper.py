"""
keyword_helper.py — Помощник для подготовки ключевых слов под Директ.

Возможности:
  - Раскладка по группам (из creatives.json или из cli).
  - Генерация вариаций с операторами Директа (фразовое соответствие, словоформа).
  - Чистка дублей.
  - Подготовка широкого списка минус-слов.

Использование:
    python -m scripts.keyword_helper --add-operators phrase \
        --input <path/to/keywords.txt> --output <path/to/out.txt>

    python -m scripts.keyword_helper --suggest-minus \
        --category general --output <path/to/minus.txt>
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable


GENERAL_MINUS = [
    "бесплатно", "торрент", "скачать", "своими руками", "своими", "руками",
    "реферат", "курсовая", "википедия", "wikipedia", "форум", "отзывы",
    "вакансия", "вакансии", "работа", "зарплата", "профессия",
    "мем", "мемы", "прикол", "приколы", "видео", "ютуб", "youtube",
    "купить бу", "бу", "б/у", "подержанный", "подержанные",
]

INFO_MINUS = [
    "как", "почему", "зачем", "что такое", "значение", "история", "википедия",
    "сравнение", "vs", "против", "лучше",
]


def add_phrase_operator(keywords: Iterable[str]) -> list[str]:
    result = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if kw.startswith('"') and kw.endswith('"'):
            result.append(kw)
        else:
            result.append(f'"{kw}"')
    return result


def add_wordform_operator(keywords: Iterable[str]) -> list[str]:
    result = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        words = [f"!{w}" if not w.startswith("!") else w for w in kw.split()]
        result.append(" ".join(words))
    return result


def add_pin_prepositions(keywords: Iterable[str]) -> list[str]:
    PREPS = {"в", "на", "к", "у", "с", "о", "из", "от", "до", "по", "за", "для"}
    result = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        words = [f"+{w}" if w in PREPS else w for w in kw.split()]
        result.append(" ".join(words))
    return result


def dedupe(keywords: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for kw in keywords:
        kw_norm = kw.lower().strip()
        if kw_norm and kw_norm not in seen:
            seen.add(kw_norm)
            out.append(kw.strip())
    return out


def suggest_minus(category: str) -> list[str]:
    if category == "general":
        return GENERAL_MINUS
    if category == "info":
        return INFO_MINUS
    if category == "all":
        return list(dict.fromkeys(GENERAL_MINUS + INFO_MINUS))
    raise ValueError(f"Неизвестная категория: {category}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Путь к файлу с ключами")
    parser.add_argument("--output", help="Куда писать результат")
    parser.add_argument(
        "--add-operators",
        choices=["phrase", "wordform", "pin_prepositions", "none"],
        default="phrase",
    )
    parser.add_argument(
        "--suggest-minus",
        choices=["general", "info", "all"],
        help="Вывести список общих минус-слов",
    )
    parser.add_argument("--dedupe", action="store_true")

    args = parser.parse_args()

    if args.suggest_minus:
        minus = suggest_minus(args.suggest_minus)
        text = "\n".join(minus)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"Записал {len(minus)} минус-слов в {args.output}")
        else:
            print(text)
        return

    if not args.input:
        raise SystemExit("Нужен --input или --suggest-minus")

    keywords = Path(args.input).read_text(encoding="utf-8").splitlines()

    if args.dedupe:
        keywords = dedupe(keywords)

    if args.add_operators == "phrase":
        keywords = add_phrase_operator(keywords)
    elif args.add_operators == "wordform":
        keywords = add_wordform_operator(keywords)
    elif args.add_operators == "pin_prepositions":
        keywords = add_pin_prepositions(keywords)

    text = "\n".join(keywords)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Записал {len(keywords)} ключей в {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
