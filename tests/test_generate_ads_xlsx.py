from scripts.generate_ads_xlsx import (
    COMBINED_HEADERS,
    validate_combined_ad,
    assemble_combined_ad_rows,
    select_assembler,
)


def _ok_combined_ad():
    return {
        "titles": ["Заголовок один", "Короткий", "Ещё вариант"],
        "texts": ["Текст выгоды и призыв к действию.", "Второй текст с другим акцентом."],
        "display_url_path": "path",
        "images": ["a.jpg", "b.jpg"],
        "videos": [],
        "sitelinks": [{"title": "Цены", "description": "от 990", "url": "u"}],
        "callouts": ["Без карты"],
    }


def test_validate_combined_ad_ok():
    assert validate_combined_ad(_ok_combined_ad(), "G") == []


def test_validate_combined_ad_flags_too_many_titles():
    ad = _ok_combined_ad()
    ad["titles"] = [f"t{i}" for i in range(8)]  # 8 > 7
    warns = validate_combined_ad(ad, "G")
    assert any("заголовк" in w and "> 7" in w for w in warns)


def test_validate_combined_ad_flags_too_many_texts():
    ad = _ok_combined_ad()
    ad["texts"] = ["a", "b", "c", "d"]  # 4 > 3
    warns = validate_combined_ad(ad, "G")
    assert any("текст" in w and "> 3" in w for w in warns)


def test_validate_combined_ad_flags_long_title():
    ad = _ok_combined_ad()
    ad["titles"] = ["Я" * 57]  # 57 > 56
    warns = validate_combined_ad(ad, "G")
    assert any("заголовок 1" in w and "> 56" in w for w in warns)


def test_validate_combined_ad_flags_no_titles():
    ad = _ok_combined_ad()
    ad["titles"] = []
    warns = validate_combined_ad(ad, "G")
    assert any("нет ни одного заголовка" in w for w in warns)


def test_assemble_combined_ad_rows_shape_and_placement():
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "combined_ad": _ok_combined_ad()}],
    }
    rows, warnings = assemble_combined_ad_rows(creatives)
    assert warnings == []
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == len(COMBINED_HEADERS) == 32
    assert row[0] == "C"          # Campaign
    assert row[1] == "G"          # Group
    assert row[2] == "Заголовок один"  # Title1
    assert row[8] == ""           # Title7 пусто (было 3 заголовка)
    assert row[9] == "Текст выгоды и призыв к действию."  # Text1
    assert row[14] == "a.jpg | b.jpg"  # Images (join через " | ")


def test_assemble_combined_ad_rows_truncates_images_to_max():
    ad = _ok_combined_ad()
    ad["images"] = [f"img{i}.jpg" for i in range(6)]  # 6 > images_max (5)
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "combined_ad": ad}],
    }
    rows, warnings = assemble_combined_ad_rows(creatives)
    row = rows[0]
    images_cell = row[14]  # Images
    assert len(images_cell.split(" | ")) == 5


def test_assemble_combined_ad_rows_warns_on_missing_combined_ad():
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x"}],  # нет combined_ad
    }
    rows, warnings = assemble_combined_ad_rows(creatives)
    assert rows == []
    assert any("нет объекта combined_ad" in w for w in warnings)


def test_select_assembler_picks_combined():
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "combined_ad": _ok_combined_ad()}],
    }
    rows, warnings, headers = select_assembler(creatives)
    assert headers == COMBINED_HEADERS
    assert len(rows) == 1


def test_select_assembler_defaults_to_combined():
    """Вход без ad_model идёт в комбинаторную модель — единственную существующую."""
    rows, warnings, headers = select_assembler({"groups": []})
    assert headers is COMBINED_HEADERS
    assert rows == []
