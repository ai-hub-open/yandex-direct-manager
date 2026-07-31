"""Проверки лимитов Директа перед заливкой через MCP.

Тесты бизнес-правил, а не формата вывода: если сообщение переформулируют,
падать они не должны — важно, что нарушение поймано и классифицировано.
"""
import json

from scripts.preflight import (
    LIMITS,
    resolve_creatives_path,
    validate_combined_ad,
    validate_creatives,
    validate_images_exist,
    validate_keywords,
    validate_negatives,
)


def _ok_combined_ad():
    return {
        "titles": ["Заголовок один", "Короткий", "Ещё вариант"],
        "texts": ["Текст выгоды и призыв к действию.", "Второй текст с другим акцентом."],
        "href": "https://example.com/lp",
        "display_url_path": "path",
        "images": [],
        "videos": [],
        "sitelinks": [{"title": "Цены", "description": "от 990", "url": "https://example.com/pricing"}],
        "callouts": ["Без карты"],
    }


def _errors(findings):
    return [f for f in findings if f.level == "error"]


def _warnings(findings):
    return [f for f in findings if f.level == "warning"]


def _messages(findings):
    return " | ".join(f.message for f in findings)


# --- объявление: количество ---------------------------------------------------

def test_valid_ad_passes():
    assert validate_combined_ad(_ok_combined_ad(), "G") == []


def test_too_many_titles_is_error():
    ad = _ok_combined_ad()
    ad["titles"] = [f"Заголовок {i}" for i in range(8)]
    assert "заголовков 8" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_too_many_texts_is_error():
    ad = _ok_combined_ad()
    ad["texts"] = ["a", "b", "c", "d"]
    assert "текстов 4" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_no_titles_is_error():
    ad = _ok_combined_ad()
    ad["titles"] = []
    assert "нет ни одного заголовка" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_no_texts_is_error():
    """Раньше не проверялось совсем: объявление без текстов уходило в API и падало там."""
    ad = _ok_combined_ad()
    ad["texts"] = []
    assert "нет ни одного текста" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_too_few_titles_is_warning_not_error():
    ad = _ok_combined_ad()
    ad["titles"] = ["Единственный заголовок"]
    findings = validate_combined_ad(ad, "G")
    assert not _errors(findings)
    assert _warnings(findings)


# --- объявление: длины --------------------------------------------------------

def test_long_title_is_error():
    ad = _ok_combined_ad()
    ad["titles"] = ["Я" * (LIMITS["title"] + 1)]
    assert _errors(validate_combined_ad(ad, "G"))


def test_long_word_in_title_is_error():
    """Директ отвергает слово длиннее 22 символов, даже если заголовок влезает."""
    ad = _ok_combined_ad()
    ad["titles"] = ["Слово " + "Я" * (LIMITS["title_word"] + 1)]
    assert "слово" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_long_word_in_text_is_error():
    ad = _ok_combined_ad()
    ad["texts"] = ["Обычный текст " + "Я" * (LIMITS["text_word"] + 1)]
    assert "слово" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_long_display_url_path_is_error():
    ad = _ok_combined_ad()
    ad["display_url_path"] = "a" * (LIMITS["display_url_path"] + 1)
    assert "display_url_path" in _messages(_errors(validate_combined_ad(ad, "G")))


# --- объявление: посадочная и расширения --------------------------------------

def test_missing_href_and_business_id_is_error():
    """ads_add_responsive требует href или business_id — иначе объявление не создастся."""
    ad = _ok_combined_ad()
    ad.pop("href")
    assert "business_id" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_business_id_replaces_href():
    ad = _ok_combined_ad()
    ad.pop("href")
    ad["business_id"] = 12345
    assert validate_combined_ad(ad, "G") == []


def test_too_many_sitelinks_is_error():
    ad = _ok_combined_ad()
    ad["sitelinks"] = [
        {"title": f"Ссылка {i}", "url": "https://example.com"}
        for i in range(LIMITS["sitelinks_max"] + 1)
    ]
    assert "быстрых ссылок" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_eight_sitelinks_allowed():
    """Раньше скилл резал до 4 — API допускает 8."""
    ad = _ok_combined_ad()
    ad["sitelinks"] = [
        {"title": f"Ссылка {i}", "url": "https://example.com"}
        for i in range(LIMITS["sitelinks_max"])
    ]
    assert validate_combined_ad(ad, "G") == []


def test_sitelink_without_url_is_error():
    ad = _ok_combined_ad()
    ad["sitelinks"] = [{"title": "Цены"}]
    assert _errors(validate_combined_ad(ad, "G"))


def test_long_callout_is_error():
    ad = _ok_combined_ad()
    ad["callouts"] = ["Я" * (LIMITS["callout"] + 1)]
    assert "уточнение" in _messages(_errors(validate_combined_ad(ad, "G")))


def test_videos_are_warning_not_error():
    """MCP не создаёт видео — залить нечем, но заливку это не блокирует."""
    ad = _ok_combined_ad()
    ad["videos"] = ["promo.mp4"]
    findings = validate_combined_ad(ad, "G")
    assert not _errors(findings)
    assert "видео" in _messages(_warnings(findings))


# --- изображения --------------------------------------------------------------

def test_missing_image_file_is_error(tmp_path):
    """adimages_add падает на несуществующем файле — ловим заранее."""
    ad = {"images": ["img/nope.jpg"]}
    assert _errors(validate_images_exist(ad, "G", tmp_path))


def test_existing_image_file_passes(tmp_path):
    img = tmp_path / "img" / "banner.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    assert validate_images_exist({"images": ["img/banner.jpg"]}, "G", tmp_path) == []


# --- ключевые и минус-фразы ---------------------------------------------------

def test_too_many_keywords_in_group_is_error():
    group = {"keywords": [f"ключ {i}" for i in range(LIMITS["keywords_per_group"] + 1)]}
    assert _errors(validate_keywords(group, "G"))


def test_long_keyword_phrase_is_error():
    group = {"keywords": ["одна фраза из очень многих слов подряд идущих здесь"]}
    assert _errors(validate_keywords(group, "G"))


def test_operators_do_not_count_as_words():
    group = {"keywords": ['"купить !диван +в москве"']}
    assert validate_keywords(group, "G") == []


def test_campaign_negatives_over_limit_is_error():
    phrases = ["минусслово"] * 3000  # ~30 000 символов без пробелов
    assert _errors(validate_negatives({"negative_keywords": phrases}))


def test_group_negatives_over_limit_is_error():
    creatives = {"groups": [{"name": "G", "negative_keywords": ["минусслово"] * 800}]}
    assert _errors(validate_negatives(creatives))


def test_negatives_within_limit_pass():
    creatives = {
        "negative_keywords": ["бесплатно", "скачать"],
        "groups": [{"name": "G", "negative_keywords": ["курс"]}],
    }
    assert validate_negatives(creatives) == []


# --- артефакт целиком ---------------------------------------------------------

def _ok_creatives():
    return {
        "campaign_key": "premium",
        "campaign_name": "ЕПК — Премиум",
        "default_url": "https://example.com",
        "negative_keywords": ["бесплатно"],
        "groups": [{
            "name": "G",
            "url": "https://example.com/lp",
            "keywords": ['"купить диван"'],
            "negative_keywords": ["дёшево"],
            "combined_ad": _ok_combined_ad(),
        }],
    }


def test_full_artifact_passes():
    assert validate_creatives(_ok_creatives()) == []


def test_href_inherited_from_group():
    """href может прийти из группы или корня — ложной ошибки быть не должно."""
    creatives = _ok_creatives()
    creatives["groups"][0]["combined_ad"].pop("href")
    assert not _errors(validate_creatives(creatives))


def test_missing_campaign_key_is_warning():
    creatives = _ok_creatives()
    creatives.pop("campaign_key")
    findings = validate_creatives(creatives)
    assert not _errors(findings)
    assert "campaign_key" in _messages(_warnings(findings))


def test_missing_combined_ad_is_error():
    creatives = _ok_creatives()
    creatives["groups"][0].pop("combined_ad")
    assert "combined_ad" in _messages(_errors(validate_creatives(creatives)))


def test_no_groups_is_error():
    creatives = _ok_creatives()
    creatives["groups"] = []
    assert _errors(validate_creatives(creatives))


def test_callouts_across_groups_counted_against_account_limit():
    creatives = _ok_creatives()
    group = creatives["groups"][0]
    group["combined_ad"]["callouts"] = [f"Уточнение {i}" for i in range(LIMITS["callouts_account_max"] + 1)]
    assert "уточнений" in _messages(_errors(validate_creatives(creatives)))


# --- разрешение пути ----------------------------------------------------------

def test_resolves_canonical_name_first(tmp_path):
    (tmp_path / "08_creatives.json").write_text("{}", encoding="utf-8")
    (tmp_path / "creatives.json").write_text("{}", encoding="utf-8")
    assert resolve_creatives_path(tmp_path, None).name == "08_creatives.json"


def test_falls_back_to_legacy_name(tmp_path):
    (tmp_path / "creatives.json").write_text("{}", encoding="utf-8")
    assert resolve_creatives_path(tmp_path, None).name == "creatives.json"


def test_explicit_path_wins(tmp_path):
    explicit = tmp_path / "custom.json"
    explicit.write_text(json.dumps({}), encoding="utf-8")
    assert resolve_creatives_path(tmp_path, str(explicit)) == explicit


# --- схлопывание минус-фраз (то, что реально уйдёт в campaigns_add) -----------

def _neg_artifact():
    return {
        "account_level": ["бесплатно", "скачать"],
        "campaigns": {
            "premium": {
                "search": ["обучение"],
                "rsya": ["дёшево"],
                "cross_minus_from_other_campaigns": ["срочно"],
            }
        },
    }


def test_collapse_merges_all_three_levels():
    from scripts.preflight import collapse_campaign_negatives
    merged = collapse_campaign_negatives(_neg_artifact(), "premium")
    assert set(merged) == {"бесплатно", "скачать", "обучение", "дёшево", "срочно"}


def test_collapse_takes_both_search_and_rsya():
    """В ЕПК Поиск и сети — одна кампания, берутся обе группы минусов."""
    from scripts.preflight import collapse_campaign_negatives
    merged = collapse_campaign_negatives(_neg_artifact(), "premium")
    assert "обучение" in merged and "дёшево" in merged


def test_collapse_deduplicates():
    from scripts.preflight import collapse_campaign_negatives
    art = _neg_artifact()
    art["campaigns"]["premium"]["search"].append("Бесплатно")
    assert len(collapse_campaign_negatives(art, "premium")) == 5


def test_collapsed_set_over_limit_is_error():
    from scripts.preflight import validate_negatives_artifact
    # Фразы уникальны: одинаковые схлопнулись бы в одну и лимит не превысили.
    art = {"account_level": [f"минусслово{i}" for i in range(3000)], "campaigns": {"premium": {}}}
    findings = validate_negatives_artifact(art, "premium")
    assert [f for f in findings if f.level == "error"]


def test_unknown_campaign_key_is_warning():
    from scripts.preflight import validate_negatives_artifact
    findings = validate_negatives_artifact(_neg_artifact(), "srochno")
    assert findings and all(f.level == "warning" for f in findings)


def test_missing_campaign_key_is_warning():
    from scripts.preflight import validate_negatives_artifact
    findings = validate_negatives_artifact(_neg_artifact(), None)
    assert findings and findings[0].level == "warning"
