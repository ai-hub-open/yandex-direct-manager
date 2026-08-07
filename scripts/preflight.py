"""
preflight.py — проверка 08_creatives.json перед заливкой через MCP (Шаг 10).

MCP-мост не проверяет длины заголовков, текстов, быстрых ссылок и уточнений —
их отвергает уже сам Директ, на середине заливки. Этот модуль ловит такие
ошибки до первого write-вызова, когда откатывать ещё нечего.

Использование:
    python -m scripts.preflight --workspace <path>
                                [--creatives-json <path>]
                                [--json]              машиночитаемый вывод

Код возврата: 0 — можно заливать, 1 — есть ошибки, заливку не начинать.

JSON-схема входа — assets/creatives_schema_combined_example.json.
Лимиты — references/yandex-direct-specs.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


# Лимиты Директа. Источник — references/yandex-direct-specs.md.
LIMITS = {
    # Комбинаторное объявление
    "titles_max": 7,
    "titles_min": 1,
    "texts_max": 3,
    "texts_min": 1,
    "images_max": 5,
    "videos_max": 6,
    "title": 56,
    "title_word": 22,
    "text": 81,
    "text_word": 23,
    "display_url_path": 20,
    # Расширения
    "sitelinks_max": 8,
    "sitelink_title": 30,
    "sitelink_description": 60,
    "callout": 25,
    "callouts_account_max": 50,
    # Ключевые и минус-фразы
    "keywords_per_group": 200,
    "phrase_words": 7,
    "negative_campaign_chars": 20000,
    "negative_group_chars": 4096,
}

# Рекомендации скилла, а не жёсткие лимиты API.
RECOMMENDED_TITLES_MIN = 3
RECOMMENDED_TEXTS_MIN = 2


@dataclass
class Finding:
    level: str  # "error" — заливку не начинать; "warning" — залить можно, но знать надо
    scope: str  # где нашли: имя группы или "кампания"
    message: str

    def render(self) -> str:
        mark = "ОШИБКА" if self.level == "error" else "предупреждение"
        return f"[{mark}] [{self.scope}] {self.message}"


def _longest_word(phrase: str) -> str:
    words = phrase.split()
    return max(words, key=len) if words else ""


def _chars_without_spaces(phrases: list[str]) -> int:
    return sum(len(p.replace(" ", "")) for p in phrases)


def validate_combined_ad(ad: dict, group_name: str) -> list[Finding]:
    """Лимиты комбинаторного объявления ЕПК."""
    out: list[Finding] = []
    err = lambda msg: out.append(Finding("error", group_name, msg))
    warn = lambda msg: out.append(Finding("warning", group_name, msg))

    titles = ad.get("titles") or []
    texts = ad.get("texts") or []
    images = ad.get("images") or []
    videos = ad.get("videos") or []

    # Количество
    if not titles:
        err("нет ни одного заголовка")
    if not texts:
        err("нет ни одного текста")
    if len(titles) > LIMITS["titles_max"]:
        err(f"заголовков {len(titles)} > {LIMITS['titles_max']}")
    if len(texts) > LIMITS["texts_max"]:
        err(f"текстов {len(texts)} > {LIMITS['texts_max']}")
    if len(images) > LIMITS["images_max"]:
        err(f"изображений {len(images)} > {LIMITS['images_max']}")
    if len(videos) > LIMITS["videos_max"]:
        err(f"видео {len(videos)} > {LIMITS['videos_max']}")

    if titles and len(titles) < RECOMMENDED_TITLES_MIN:
        warn(f"заголовков {len(titles)} — Директу нужно от {RECOMMENDED_TITLES_MIN} для комбинаций")
    if texts and len(texts) < RECOMMENDED_TEXTS_MIN:
        warn(f"текстов {len(texts)} — рекомендуется от {RECOMMENDED_TEXTS_MIN}")

    # Длины
    for i, t in enumerate(titles, 1):
        if len(t) > LIMITS["title"]:
            err(f"заголовок {i}={t!r} > {LIMITS['title']} ({len(t)} симв)")
        word = _longest_word(t)
        if len(word) > LIMITS["title_word"]:
            err(f"заголовок {i}: слово {word!r} > {LIMITS['title_word']} символов")
    for i, t in enumerate(texts, 1):
        if len(t) > LIMITS["text"]:
            err(f"текст {i}={t!r} > {LIMITS['text']} ({len(t)} симв)")
        word = _longest_word(t)
        if len(word) > LIMITS["text_word"]:
            err(f"текст {i}: слово {word!r} > {LIMITS['text_word']} символов")

    dup = ad.get("display_url_path")
    if dup and len(dup) > LIMITS["display_url_path"]:
        err(f"display_url_path={dup!r} > {LIMITS['display_url_path']} ({len(dup)} симв)")

    # Посадочная: ads_add_responsive требует href или business_id
    if not (ad.get("href") or ad.get("business_id")):
        err("нет ни href, ни business_id — объявление не создастся")

    # Быстрые ссылки
    sitelinks = ad.get("sitelinks") or []
    if len(sitelinks) > LIMITS["sitelinks_max"]:
        err(f"быстрых ссылок {len(sitelinks)} > {LIMITS['sitelinks_max']}")
    for i, sl in enumerate(sitelinks, 1):
        if not sl.get("title"):
            err(f"sitelink{i}: пустой title — обязателен")
        if len(sl.get("title", "")) > LIMITS["sitelink_title"]:
            err(f"sitelink{i}.title={sl['title']!r} длиннее {LIMITS['sitelink_title']}")
        if len(sl.get("description", "")) > LIMITS["sitelink_description"]:
            err(f"sitelink{i}.description={sl['description']!r} длиннее {LIMITS['sitelink_description']}")
        if not (sl.get("url") or sl.get("turbo_page_id")):
            err(f"sitelink{i}: нет ни url, ни turbo_page_id")

    # Уточнения
    callouts = ad.get("callouts") or []
    for i, callout in enumerate(callouts, 1):
        if len(callout) > LIMITS["callout"]:
            err(f"уточнение {i}={callout!r} длиннее {LIMITS['callout']} ({len(callout)} симв)")

    # Видео: поле принимается, но залить его нечем
    if videos:
        warn(f"видео ({len(videos)} шт.) MCP не заливает — добавить через интерфейс, отметить в 10_launch_log.md")

    return out


def validate_images_exist(ad: dict, group_name: str, workspace: Path) -> list[Finding]:
    """adimages_add падает на несуществующем файле — проверяем заранее."""
    out: list[Finding] = []
    for path_str in ad.get("images") or []:
        candidate = Path(path_str)
        found = candidate.is_absolute() and candidate.exists()
        if not found:
            found = (workspace / path_str).exists()
        if not found:
            out.append(Finding(
                "error", group_name,
                f"файл изображения не найден: {path_str} (искал по абсолютному пути и от {workspace})"
            ))
    return out


def validate_keywords(group: dict, group_name: str) -> list[Finding]:
    out: list[Finding] = []
    keywords = group.get("keywords") or []
    if not keywords:
        out.append(Finding("warning", group_name, "нет ключевых фраз"))
    if len(keywords) > LIMITS["keywords_per_group"]:
        out.append(Finding(
            "error", group_name,
            f"ключевых фраз {len(keywords)} > {LIMITS['keywords_per_group']} — разбей на группы"
        ))
    for kw in keywords:
        # Операторы соответствия не считаются словами Директа, но для оценки достаточно.
        cleaned = kw.replace('"', "").replace("[", "").replace("]", "").replace("!", "").replace("+", "")
        if len(cleaned.split()) > LIMITS["phrase_words"]:
            out.append(Finding("error", group_name, f"фраза {kw!r} длиннее {LIMITS['phrase_words']} слов"))
    return out


def validate_negatives(creatives: dict) -> list[Finding]:
    """Минус-фразы: лимиты по объёму на кампанию и на группу."""
    out: list[Finding] = []

    campaign_negatives = creatives.get("negative_keywords") or []
    total = _chars_without_spaces(campaign_negatives)
    if total > LIMITS["negative_campaign_chars"]:
        out.append(Finding(
            "error", "кампания",
            f"минус-фразы кампании {total} символов без пробелов > {LIMITS['negative_campaign_chars']} — "
            "вынеси часть в Библиотеку минус-фраз вручную и отметь в 10_launch_log.md"
        ))
    for phrase in campaign_negatives:
        if len(phrase.split()) > LIMITS["phrase_words"]:
            out.append(Finding("error", "кампания", f"минус-фраза {phrase!r} длиннее {LIMITS['phrase_words']} слов"))

    for group in creatives.get("groups") or []:
        name = group.get("name", "без имени")
        group_negatives = group.get("negative_keywords") or []
        total = _chars_without_spaces(group_negatives)
        if total > LIMITS["negative_group_chars"]:
            out.append(Finding(
                "error", name,
                f"минус-фразы группы {total} символов без пробелов > {LIMITS['negative_group_chars']}"
            ))
        for phrase in group_negatives:
            if len(phrase.split()) > LIMITS["phrase_words"]:
                out.append(Finding("error", name, f"минус-фраза {phrase!r} длиннее {LIMITS['phrase_words']} слов"))

    return out


def collapse_campaign_negatives(neg_artifact: dict, campaign_key: str) -> list[str]:
    """Три уровня минусов скилла → один список минус-фраз кампании.

    Библиотеки минус-фраз в MCP нет, поэтому «аккаунт-уровень» уезжает в
    минусы каждой кампании. В ЕПК Поиск и сети — одна кампания, значит берутся
    обе группы (.search и .rsya), а не одна из них.
    """
    campaign = (neg_artifact.get("campaigns") or {}).get(campaign_key) or {}
    merged: list[str] = []
    for chunk in (
        neg_artifact.get("account_level") or [],
        campaign.get("search") or [],
        campaign.get("rsya") or [],
        campaign.get("cross_minus_from_other_campaigns") or [],
    ):
        merged.extend(chunk)

    seen: set[str] = set()
    unique: list[str] = []
    for phrase in merged:
        key = phrase.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(phrase)
    return unique


def validate_negatives_artifact(neg_artifact: dict, campaign_key: str | None) -> list[Finding]:
    """Проверяет объём минус-фраз, который реально уйдёт в campaigns_add."""
    out: list[Finding] = []
    if not campaign_key:
        out.append(Finding(
            "warning", "минус-фразы",
            "нет campaign_key — не могу сопоставить кампанию с 06_negative_keywords.json"
        ))
        return out

    if campaign_key not in (neg_artifact.get("campaigns") or {}):
        out.append(Finding(
            "warning", "минус-фразы",
            f"в 06_negative_keywords.json нет кампании {campaign_key!r} — "
            "в кампанию уйдут только минусы уровня аккаунта"
        ))

    collapsed = collapse_campaign_negatives(neg_artifact, campaign_key)
    total = _chars_without_spaces(collapsed)
    if total > LIMITS["negative_campaign_chars"]:
        out.append(Finding(
            "error", "минус-фразы",
            f"схлопнутый набор минус-фраз кампании — {total} символов без пробелов "
            f"({len(collapsed)} фраз) > {LIMITS['negative_campaign_chars']}. "
            "Обрежь по приоритету account_level → кросс-минусы → поисковые "
            "и вынеси остаток в Библиотеку минус-фраз вручную"
        ))
    for phrase in collapsed:
        if len(phrase.split()) > LIMITS["phrase_words"]:
            out.append(Finding(
                "error", "минус-фразы",
                f"минус-фраза {phrase!r} длиннее {LIMITS['phrase_words']} слов"
            ))
    return out


def validate_creatives(creatives: dict, workspace: Path | None = None) -> list[Finding]:
    """Полная проверка артефакта. workspace нужен, чтобы искать файлы изображений."""
    out: list[Finding] = []

    if not creatives.get("campaign_key"):
        out.append(Finding(
            "warning", "кампания",
            "нет campaign_key — заливка не свяжет минусы, цели и стратегию с этой кампанией"
        ))
    if not creatives.get("campaign_name"):
        out.append(Finding("error", "кампания", "нет campaign_name"))

    groups = creatives.get("groups") or []
    if not groups:
        out.append(Finding("error", "кампания", "нет ни одной группы"))

    # Общее количество уточнений в аккаунте ограничено — считаем уникальные по всем группам.
    all_callouts: set[str] = set()

    for group in groups:
        name = group.get("name", "без имени")
        ad = group.get("combined_ad")
        if not ad:
            out.append(Finding("error", name, "нет объекта combined_ad — объявление не собрано"))
        else:
            # href может прийти из группы или из корня артефакта
            resolved = dict(ad)
            if not resolved.get("href"):
                resolved["href"] = group.get("url") or creatives.get("default_url")
            out.extend(validate_combined_ad(resolved, name))
            if workspace is not None:
                out.extend(validate_images_exist(ad, name, workspace))
            all_callouts.update(ad.get("callouts") or [])
        out.extend(validate_keywords(group, name))

    if len(all_callouts) > LIMITS["callouts_account_max"]:
        out.append(Finding(
            "error", "кампания",
            f"уникальных уточнений {len(all_callouts)} > {LIMITS['callouts_account_max']} на аккаунт"
        ))

    out.extend(validate_negatives(creatives))
    return out


def resolve_creatives_path(workspace: Path, explicit: str | None) -> Path:
    """08_creatives.json — каноническое имя; creatives.json поддерживается для совместимости."""
    if explicit:
        return Path(explicit)
    canonical = workspace / "08_creatives.json"
    if canonical.exists():
        return canonical
    return workspace / "creatives.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка креативов перед заливкой через MCP")
    parser.add_argument("--workspace", required=True, help="Папка кампании direct-campaigns/<slug>")
    parser.add_argument("--creatives-json", default=None,
                        help="Путь к 08_creatives.json. По умолч. — <workspace>/08_creatives.json")
    parser.add_argument("--json", action="store_true", help="Машиночитаемый вывод")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    creatives_path = resolve_creatives_path(workspace, args.creatives_json)

    if not creatives_path.exists():
        print(f"Не найден файл креативов: {creatives_path}", file=sys.stderr)
        sys.exit(1)

    creatives = json.loads(creatives_path.read_text(encoding="utf-8"))
    findings = validate_creatives(creatives, workspace)

    # Минусы кампании собираются при заливке из 06_negative_keywords.json,
    # а не из креативов — проверяем именно тот набор, который уйдёт в API.
    negatives_path = workspace / "06_negative_keywords.json"
    if negatives_path.exists():
        neg_artifact = json.loads(negatives_path.read_text(encoding="utf-8"))
        findings.extend(validate_negatives_artifact(neg_artifact, creatives.get("campaign_key")))

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]

    if args.json:
        print(json.dumps({
            "ok": not errors,
            "errors": [asdict(f) for f in errors],
            "warnings": [asdict(f) for f in warnings],
        }, ensure_ascii=False, indent=2))
    else:
        for f in errors + warnings:
            print(f.render())
        print()
        if errors:
            print(f"Ошибок: {len(errors)}, предупреждений: {len(warnings)}. Заливку не начинать.")
        else:
            print(f"Ошибок нет, предупреждений: {len(warnings)}. Можно заливать.")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
