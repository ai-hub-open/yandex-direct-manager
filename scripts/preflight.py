"""
preflight.py — проверка 08_creatives.json перед заливкой через MCP (Шаг 10).

MCP-мост не проверяет длины заголовков, текстов, быстрых ссылок и уточнений —
их отвергает уже сам Директ, на середине заливки. Этот модуль ловит такие
ошибки до первого write-вызова, когда откатывать ещё нечего.

Использование:
    python -m scripts.preflight --workspace <path>
                                [--creatives-json <path>]
                                [--json]              машиночитаемый вывод
                                [--negatives-only]    только 06_negative_keywords.json (Шаг 6)

Код возврата: 0 — можно заливать, 1 — есть ошибки, заливку не начинать.

Вход — одна кампания или пакет кампаний (`campaigns[]`), см. scripts/creatives_io.py.
JSON-схемы — assets/creatives_schema_combined_example.json и
assets/creatives_schema_package_example.json.
Лимиты — references/yandex-direct-specs.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from scripts.creatives_io import campaigns_of, is_package


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
    "text": 81,           # без учёта «узких» знаков
    "text_narrow": 15,    # «узких» знаков в тексте сверх 81
    "text_word": 23,
    "display_url_path": 20,
    # Расширения
    "sitelinks_max": 8,
    "sitelink_title": 30,
    "sitelink_description": 60,
    "sitelinks_titles_per_four": 66,  # заголовки 1–4 вместе, 5–8 вместе
    "callout": 25,
    "callouts_account_max": 50,
    # Ключевые и минус-фразы
    "keywords_per_group": 200,
    "phrase_words": 7,
    "negative_campaign_chars": 20000,
    "negative_group_chars": 4096,
}

# «Узкие» знаки по справке API ads.add: в тексте не входят в 81, в заголовке считаются.
NARROW_CHARS = frozenset('!,.;:"')

# Отображаемая ссылка: буквы, цифры, - / № % #; сдвоенные -- и // запрещены.
DISPLAY_URL_PATH_RE = re.compile(r"[^\W_]|[-/№%#]")

# Символы ключевых и минус-фраз. Справка Директа «Минус-фразы»: в минус-фразах
# поддерживаются только операторы " " [] ! +. В ключевой фразе ещё ( ) |.
# Остальное — буквы, цифры, пробел. Чужой символ («б/у») Директ отклоняет
# ошибкой 5002 — всю кампанию, а не одну фразу.
NEGATIVE_OPERATORS = frozenset('"[]!+')
KEYWORD_OPERATORS = frozenset('"[]!+()|')
# Справка не запрещает точку, апостроф и дефис («2.0», «mcdonald's», «онлайн-курс»,
# «-слово» как минус-слово) — пропускаем: ложная ошибка остановила бы заливку.
NEUTRAL_CHARS = frozenset(" .'-")

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


def _split_narrow(text: str) -> tuple[int, int]:
    """(обычных символов, «узких» знаков) — так Директ считает длину текста."""
    narrow = sum(1 for ch in text if ch in NARROW_CHARS)
    return len(text) - narrow, narrow


def _display_url_path_problem(path: str) -> str | None:
    bad = sorted({ch for ch in path if not DISPLAY_URL_PATH_RE.fullmatch(ch)})
    if bad:
        listed = " ".join(repr(ch) for ch in bad)
        return f"недопустимые символы {listed} — можно только буквы, цифры, -, /, №, %, #"
    for double in ("--", "//"):
        if double in path:
            return f"сдвоенные {double!r} запрещены"
    return None


def _chars_without_spaces(phrases: list[str]) -> int:
    return sum(len(p.replace(" ", "")) for p in phrases)


def _forbidden_chars(phrase: str, operators: frozenset) -> list[str]:
    return sorted({ch for ch in phrase if not (ch.isalnum() or ch in operators or ch in NEUTRAL_CHARS)})


def suggest_phrase_fix(phrase: str, operators: frozenset) -> str:
    """Замена для фразы с чужими символами: «б/у» → «бу», «seo/smm» → «seo smm».

    Символ между короткими частями (сокращение до двух букв) убираем, иначе — пробел.
    """
    out = []
    for i, ch in enumerate(phrase):
        if ch.isalnum() or ch in operators or ch in NEUTRAL_CHARS:
            out.append(ch)
            continue
        left = re.search(r"(\w*)$", phrase[:i]).group(1)
        right = re.match(r"\w*", phrase[i + 1:]).group(0)
        glue = left and right and len(left) <= 2 and len(right) <= 2
        out.append("" if glue else " ")
    return " ".join("".join(out).split())


def _charset_problem(phrase: str, kind: str, operators: frozenset) -> str | None:
    bad = _forbidden_chars(phrase, operators)
    if not bad:
        return None
    listed = " ".join(repr(ch) for ch in bad)
    return (f"{kind} {phrase!r}: недопустимые символы {listed} — Директ отклонит "
            f"(ошибка 5002). Замена: {suggest_phrase_fix(phrase, operators)!r}")


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
        regular, narrow = _split_narrow(t)
        if regular > LIMITS["text"]:
            err(f"текст {i}={t!r} > {LIMITS['text']} без «узких» знаков ({regular} симв)")
        if narrow > LIMITS["text_narrow"]:
            err(f"текст {i}={t!r}: «узких» знаков {narrow} > {LIMITS['text_narrow']}")
        word = _longest_word(t)
        if len(word) > LIMITS["text_word"]:
            err(f"текст {i}: слово {word!r} > {LIMITS['text_word']} символов")

    dup = ad.get("display_url_path")
    if dup and len(dup) > LIMITS["display_url_path"]:
        err(f"display_url_path={dup!r} > {LIMITS['display_url_path']} ({len(dup)} симв)")
    if dup:
        problem = _display_url_path_problem(dup)
        if problem:
            err(f"display_url_path={dup!r}: {problem}")

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
    for start in (0, 4):
        four = sitelinks[start:start + 4]
        total = sum(len(sl.get("title", "")) for sl in four)
        if total > LIMITS["sitelinks_titles_per_four"]:
            err(f"быстрые ссылки {start + 1}–{start + 4}: заголовки вместе {total} симв "
                f"> {LIMITS['sitelinks_titles_per_four']} — Директ отклонит набор")

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
        problem = _charset_problem(kw, "ключевая фраза", KEYWORD_OPERATORS)
        if problem:
            out.append(Finding("error", group_name, problem))
    return out


def _negative_phrase_problems(phrases: list[str], scope: str) -> list[Finding]:
    """Число слов и символы каждой минус-фразы."""
    out: list[Finding] = []
    for phrase in phrases:
        if len(phrase.split()) > LIMITS["phrase_words"]:
            out.append(Finding("error", scope, f"минус-фраза {phrase!r} длиннее {LIMITS['phrase_words']} слов"))
        problem = _charset_problem(phrase, "минус-фраза", NEGATIVE_OPERATORS)
        if problem:
            out.append(Finding("error", scope, problem))
    return out


def _group_scope(campaign_label: str | None, group_name: str) -> str:
    return f"{campaign_label} / {group_name}" if campaign_label else group_name


def validate_negatives(creatives: dict, campaign_label: str | None = None) -> list[Finding]:
    """Минус-фразы одной кампании: объём на кампанию и на группу, слова, символы."""
    out: list[Finding] = []
    campaign_scope = campaign_label or "кампания"

    campaign_negatives = creatives.get("negative_keywords") or []
    total = _chars_without_spaces(campaign_negatives)
    if total > LIMITS["negative_campaign_chars"]:
        out.append(Finding(
            "error", campaign_scope,
            f"минус-фразы кампании {total} символов без пробелов > {LIMITS['negative_campaign_chars']} — "
            "вынеси часть в Библиотеку минус-фраз вручную и отметь в 10_launch_log.md"
        ))
    out.extend(_negative_phrase_problems(campaign_negatives, campaign_scope))

    for group in creatives.get("groups") or []:
        name = _group_scope(campaign_label, group.get("name", "без имени"))
        group_negatives = group.get("negative_keywords") or []
        total = _chars_without_spaces(group_negatives)
        if total > LIMITS["negative_group_chars"]:
            out.append(Finding(
                "error", name,
                f"минус-фразы группы {total} символов без пробелов > {LIMITS['negative_group_chars']}"
            ))
        out.extend(_negative_phrase_problems(group_negatives, name))

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


SHARED_NEGATIVES_SCOPE = "минус-фразы account_level — общие для всех кампаний"


def validate_shared_negatives(neg_artifact: dict) -> list[Finding]:
    """Минусы account_level уходят в каждую кампанию пакета.

    Ошибка в них — общая причина отказа всех кампаний сразу, поэтому сообщаем о ней
    один раз, с подсказкой исправить источник, а не каждую кампанию.
    """
    out = _negative_phrase_problems(neg_artifact.get("account_level") or [], SHARED_NEGATIVES_SCOPE)
    for f in out:
        f.message += " — исправь в 06_negative_keywords.json один раз: фраза уходит во все кампании"
    return out


def validate_negatives_artifact(neg_artifact: dict, campaign_key: str | None,
                                check_shared: bool = True) -> list[Finding]:
    """Проверяет минус-фразы, которые реально уйдут в campaigns_add.

    check_shared=False — минусы account_level уже проверены validate_shared_negatives
    (пакет кампаний), здесь только объём и фразы самой кампании.
    """
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
    shared = {p.strip().lower() for p in neg_artifact.get("account_level") or []}
    own = collapsed if check_shared else [p for p in collapsed if p.strip().lower() not in shared]
    scope = "минус-фразы" if check_shared else f"минус-фразы {campaign_key}"
    out.extend(_negative_phrase_problems(own, scope))
    return out


def _validate_campaign(campaign: dict, workspace: Path | None,
                       campaign_label: str | None) -> tuple[list[Finding], set[str]]:
    """Одна кампания: (находки, уточнения её групп — для лимита на аккаунт)."""
    out: list[Finding] = []
    campaign_scope = campaign_label or "кампания"

    if not campaign.get("campaign_key"):
        out.append(Finding(
            "warning", campaign_scope,
            "нет campaign_key — заливка не свяжет минусы, цели и стратегию с этой кампанией"
        ))
    if not campaign.get("campaign_name"):
        out.append(Finding("error", campaign_scope, "нет campaign_name"))

    groups = campaign.get("groups") or []
    if not groups:
        out.append(Finding("error", campaign_scope, "нет ни одной группы"))

    callouts: set[str] = set()
    for group in groups:
        name = _group_scope(campaign_label, group.get("name", "без имени"))
        ad = group.get("combined_ad")
        if not ad:
            out.append(Finding("error", name, "нет объекта combined_ad — объявление не собрано"))
        else:
            # href может прийти из группы или из корня артефакта
            resolved = dict(ad)
            if not resolved.get("href"):
                resolved["href"] = group.get("url") or campaign.get("default_url")
            out.extend(validate_combined_ad(resolved, name))
            if workspace is not None:
                out.extend(validate_images_exist(ad, name, workspace))
            callouts.update(ad.get("callouts") or [])
        out.extend(validate_keywords(group, name))

    out.extend(validate_negatives(campaign, campaign_label))
    return out, callouts


def validate_creatives(creatives: dict, workspace: Path | None = None) -> list[Finding]:
    """Полная проверка артефакта: одной кампании или пакета.

    workspace нужен, чтобы искать файлы изображений.
    """
    out: list[Finding] = []
    # Общее количество уточнений в аккаунте ограничено — считаем уникальные по всем группам.
    all_callouts: set[str] = set()

    if not is_package(creatives):
        found, all_callouts = _validate_campaign(creatives, workspace, None)
        out.extend(found)
    else:
        campaigns = campaigns_of(creatives)
        if not campaigns:
            out.append(Finding("error", "пакет", "в campaigns нет ни одной кампании"))
        keys = [c.get("campaign_key") for c in campaigns if c.get("campaign_key")]
        for key in sorted({k for k in keys if keys.count(k) > 1}):
            out.append(Finding("error", "пакет", f"campaign_key {key!r} у нескольких кампаний — у каждой свой"))
        for i, campaign in enumerate(campaigns, 1):
            label = campaign.get("campaign_name") or campaign.get("campaign_key") or f"кампания {i}"
            found, callouts = _validate_campaign(campaign, workspace, label)
            out.extend(found)
            all_callouts |= callouts

    if len(all_callouts) > LIMITS["callouts_account_max"]:
        out.append(Finding(
            "error", "пакет" if is_package(creatives) else "кампания",
            f"уникальных уточнений {len(all_callouts)} > {LIMITS['callouts_account_max']} на аккаунт"
        ))
    return out


def validate_package_negatives(creatives: dict, neg_artifact: dict) -> list[Finding]:
    """Минусы из 06_negative_keywords.json по каждой кампании пакета (или одной кампании)."""
    if not is_package(creatives):
        return validate_negatives_artifact(neg_artifact, creatives.get("campaign_key"))
    out = validate_shared_negatives(neg_artifact)
    for campaign in campaigns_of(creatives):
        out.extend(validate_negatives_artifact(neg_artifact, campaign.get("campaign_key"), check_shared=False))
    return out


def validate_negatives_only(neg_artifact: dict) -> list[Finding]:
    """Шаг 6: минусы до объявлений — по кампаниям из самого 06_negative_keywords.json."""
    out = validate_shared_negatives(neg_artifact)
    for key in neg_artifact.get("campaigns") or {}:
        out.extend(validate_negatives_artifact(neg_artifact, key, check_shared=False))
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
    parser.add_argument("--negatives-only", action="store_true",
                        help="Только 06_negative_keywords.json — проверка на Шаге 6, до объявлений")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    negatives_path = workspace / "06_negative_keywords.json"

    if args.negatives_only:
        if not negatives_path.exists():
            print(f"Не найден файл минус-фраз: {negatives_path}", file=sys.stderr)
            sys.exit(1)
        findings = validate_negatives_only(json.loads(negatives_path.read_text(encoding="utf-8")))
    else:
        creatives_path = resolve_creatives_path(workspace, args.creatives_json)
        if not creatives_path.exists():
            print(f"Не найден файл креативов: {creatives_path}", file=sys.stderr)
            sys.exit(1)

        creatives = json.loads(creatives_path.read_text(encoding="utf-8"))
        findings = validate_creatives(creatives, workspace)

        # Минусы кампании собираются при заливке из 06_negative_keywords.json,
        # а не из креативов — проверяем именно тот набор, который уйдёт в API.
        if negatives_path.exists():
            neg_artifact = json.loads(negatives_path.read_text(encoding="utf-8"))
            findings.extend(validate_package_negatives(creatives, neg_artifact))

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
