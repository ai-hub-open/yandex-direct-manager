"""Сборка таблиц для маркетолога и фолбека в Директ Коммандер.

Проверка лимитов Директа живёт в tests/test_preflight.py — здесь только
раскладка строк по колонкам и поведение при усечении.
"""
from scripts.generate_ads_xlsx import (
    CALLOUT_COLUMNS,
    COMBINED_HEADERS,
    SITELINK_COLUMNS,
    assemble_combined_ad_rows,
    select_assembler,
    validate_combined_ad,
)


def _ok_combined_ad():
    return {
        "titles": ["Заголовок один", "Короткий", "Ещё вариант"],
        "texts": ["Текст выгоды и призыв к действию.", "Второй текст с другим акцентом."],
        "href": "https://example.com/lp",
        "display_url_path": "path",
        "images": ["a.jpg", "b.jpg"],
        "videos": [],
        "sitelinks": [{"title": "Цены", "description": "от 990", "url": "https://example.com/pricing"}],
        "callouts": ["Без карты"],
    }


def _creatives(ad=None, group_extra=None):
    group = {"name": "G", "url": "https://example.com/lp", "combined_ad": ad or _ok_combined_ad()}
    group.update(group_extra or {})
    return {"campaign_name": "C", "groups": [group]}


def test_validate_returns_strings_for_warnings_file():
    """Обёртка над preflight отдаёт готовые строки для warnings.txt."""
    warns = validate_combined_ad(_ok_combined_ad(), "G")
    assert warns == []

    ad = _ok_combined_ad()
    ad["titles"] = [f"Заголовок {i}" for i in range(8)]
    warns = validate_combined_ad(ad, "G")
    assert warns and all(isinstance(w, str) for w in warns)


def test_row_shape_and_placement():
    rows, warnings = assemble_combined_ad_rows(_creatives())
    assert warnings == []
    assert len(rows) == 1

    row = rows[0]
    assert len(row) == len(COMBINED_HEADERS)
    assert row[COMBINED_HEADERS.index("Campaign")] == "C"
    assert row[COMBINED_HEADERS.index("Group")] == "G"
    assert row[COMBINED_HEADERS.index("Title1")] == "Заголовок один"
    assert row[COMBINED_HEADERS.index("Title7")] == ""
    assert row[COMBINED_HEADERS.index("Text1")] == "Текст выгоды и призыв к действию."
    assert row[COMBINED_HEADERS.index("Images")] == "a.jpg | b.jpg"


def test_href_falls_back_to_group_url():
    ad = _ok_combined_ad()
    ad.pop("href")
    rows, warnings = assemble_combined_ad_rows(_creatives(ad))
    assert warnings == []
    assert rows[0][COMBINED_HEADERS.index("Href")] == "https://example.com/lp"


def test_truncates_images_to_max():
    ad = _ok_combined_ad()
    ad["images"] = [f"img{i}.jpg" for i in range(6)]
    rows, _ = assemble_combined_ad_rows(_creatives(ad))
    images_cell = rows[0][COMBINED_HEADERS.index("Images")]
    assert len(images_cell.split(" | ")) == 5


def test_extra_sitelinks_are_reported_not_dropped_silently():
    """Колонок 4, а API допускает 8 — лишние должны попасть в warnings."""
    ad = _ok_combined_ad()
    ad["sitelinks"] = [
        {"title": f"Ссылка {i}", "description": "d", "url": "https://example.com"}
        for i in range(6)
    ]
    rows, warnings = assemble_combined_ad_rows(_creatives(ad))
    assert any("быстрых ссылок" in w for w in warnings)
    assert rows[0][COMBINED_HEADERS.index("Sitelink4_Title")] == "Ссылка 3"
    assert len(rows[0]) == len(COMBINED_HEADERS)


def test_extra_callouts_are_reported_not_dropped_silently():
    ad = _ok_combined_ad()
    ad["callouts"] = [f"Уточнение {i}" for i in range(6)]
    rows, warnings = assemble_combined_ad_rows(_creatives(ad))
    assert any("уточнений" in w for w in warnings)
    assert rows[0][COMBINED_HEADERS.index(f"Callout{CALLOUT_COLUMNS}")] == "Уточнение 3"


def test_warns_on_missing_combined_ad():
    creatives = {"campaign_name": "C", "groups": [{"name": "G", "url": "https://x"}]}
    rows, warnings = assemble_combined_ad_rows(creatives)
    assert rows == []
    assert any("нет объекта combined_ad" in w for w in warnings)


def test_keyword_and_sitelink_column_counts_agree():
    assert COMBINED_HEADERS.count("Callout1") == 1
    assert sum(h.startswith("Sitelink") and h.endswith("_Title") for h in COMBINED_HEADERS) == SITELINK_COLUMNS
    assert sum(h.startswith("Callout") for h in COMBINED_HEADERS) == CALLOUT_COLUMNS


def test_select_assembler_returns_combined_headers():
    rows, warnings, headers = select_assembler(_creatives())
    assert headers is COMBINED_HEADERS
    assert len(rows) == 1


def test_select_assembler_handles_empty_input():
    rows, warnings, headers = select_assembler({"groups": []})
    assert headers is COMBINED_HEADERS
    assert rows == []
