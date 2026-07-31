"""
generate_ads_xlsx.py — Превращает 08_creatives.json в таблицы для маркетолога
и для фолбека в Директ Коммандер.

Штатный путь заливки — MCP (см. references/mcp-account-integration.md, Use case 5).
Эти файлы нужны, чтобы человек мог посмотреть кампанию целиком, и как запасной
канал импорта, когда MCP недоступен.

По умолчанию пытается собрать .xlsx через openpyxl. Если openpyxl нет — мягко
падает в .csv (Direct Commander поддерживает CSV-импорт). В любом случае
проверяет лимиты символов Директа и кладёт warnings.txt с результатом проверки.

Использование:
    python -m scripts.generate_ads_xlsx --workspace <path>
                                        [--creatives-json <path>]
                                        [--output-dir <path>]
                                        [--format xlsx|csv|auto]   (по умолч. auto)

JSON-схема — см. assets/creatives_schema_combined_example.json.
Полная проверка лимитов перед заливкой — python -m scripts.preflight.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.preflight import LIMITS, resolve_creatives_path
from scripts.preflight import validate_combined_ad as _validate_combined_ad


# Лимиты Директа живут в одном месте — scripts/preflight.py.
COMBINED_LIMITS = LIMITS

# Колонок под быстрые ссылки и уточнения в таблице меньше, чем допускает API
# (8 и 50): файл читает человек, а не Директ. Всё, что не поместилось,
# попадает в warnings.txt, а не теряется молча.
SITELINK_COLUMNS = 4
CALLOUT_COLUMNS = 4


COMBINED_HEADERS = [
    "Campaign", "Group",
    "Title1", "Title2", "Title3", "Title4", "Title5", "Title6", "Title7",
    "Text1", "Text2", "Text3",
    "Href", "DisplayUrlPath", "Images", "Videos",
    "Sitelink1_Title", "Sitelink1_Desc", "Sitelink1_Url",
    "Sitelink2_Title", "Sitelink2_Desc", "Sitelink2_Url",
    "Sitelink3_Title", "Sitelink3_Desc", "Sitelink3_Url",
    "Sitelink4_Title", "Sitelink4_Desc", "Sitelink4_Url",
    "Callout1", "Callout2", "Callout3", "Callout4",
]


def validate_combined_ad(ad: dict, group_name: str) -> list[str]:
    """Обёртка над проверкой из preflight: строки для warnings.txt."""
    return [f.render() for f in _validate_combined_ad(ad, group_name)]


def assemble_combined_ad_rows(creatives: dict) -> tuple[list[list], list[str]]:
    rows: list[list] = []
    all_warnings: list[str] = []
    campaign_name = creatives.get("campaign_name", "")
    default_url = creatives.get("default_url", "")

    for group in creatives.get("groups", []):
        ad = group.get("combined_ad")
        if not ad:
            all_warnings.append(f"[{group['name']}] нет объекта combined_ad — объявление не собрано")
            continue
        # Посадочная берётся по цепочке объявление → группа → корень артефакта.
        # Проверять надо итоговую, иначе получим ложную ошибку «нет href».
        href = ad.get("href") or group.get("url") or default_url
        all_warnings.extend(validate_combined_ad({**ad, "href": href}, group["name"]))

        titles = ad.get("titles", [])[:COMBINED_LIMITS["titles_max"]]
        texts = ad.get("texts", [])[:COMBINED_LIMITS["texts_max"]]

        row = [campaign_name, group["name"]]
        for i in range(COMBINED_LIMITS["titles_max"]):
            row.append(titles[i] if i < len(titles) else "")
        for i in range(COMBINED_LIMITS["texts_max"]):
            row.append(texts[i] if i < len(texts) else "")
        row.append(href)
        row.append(ad.get("display_url_path", ""))
        row.append(" | ".join(ad.get("images", [])[:COMBINED_LIMITS["images_max"]]))
        row.append(" | ".join(ad.get("videos", [])[:COMBINED_LIMITS["videos_max"]]))

        all_sitelinks = ad.get("sitelinks", [])
        if len(all_sitelinks) > SITELINK_COLUMNS:
            all_warnings.append(
                f"[{group['name']}] быстрых ссылок {len(all_sitelinks)}, в таблицу попадут первые "
                f"{SITELINK_COLUMNS} — остальные добавь при заливке через MCP или в Коммандере"
            )
        sitelinks = all_sitelinks[:SITELINK_COLUMNS]
        for i in range(SITELINK_COLUMNS):
            if i < len(sitelinks):
                row.extend([
                    sitelinks[i].get("title", ""),
                    sitelinks[i].get("description", ""),
                    sitelinks[i].get("url", ""),
                ])
            else:
                row.extend(["", "", ""])

        all_callouts = ad.get("callouts", [])
        if len(all_callouts) > CALLOUT_COLUMNS:
            all_warnings.append(
                f"[{group['name']}] уточнений {len(all_callouts)}, в таблицу попадут первые "
                f"{CALLOUT_COLUMNS} — остальные добавь при заливке через MCP или в Коммандере"
            )
        callouts = all_callouts[:CALLOUT_COLUMNS]
        for i in range(CALLOUT_COLUMNS):
            row.append(callouts[i] if i < len(callouts) else "")
        rows.append(row)
    return rows, all_warnings


def select_assembler(creatives: dict) -> tuple[list[list], list[str], list[str]]:
    # Модель одна — комбинаторное объявление. Отсутствие поля трактуем как комбинаторное.
    rows, warnings = assemble_combined_ad_rows(creatives)
    return rows, warnings, COMBINED_HEADERS


def assemble_keyword_rows(creatives: dict) -> list[list]:
    rows: list[list] = []
    campaign_name = creatives.get("campaign_name", "")
    for group in creatives.get("groups", []):
        for kw in group.get("keywords", []):
            rows.append([campaign_name, group["name"], kw, "phrase"])
        for nkw in group.get("negative_keywords", []):
            rows.append([campaign_name, group["name"], nkw, "negative_group"])
    for nkw in creatives.get("negative_keywords", []):
        rows.append([campaign_name, "", nkw, "negative_campaign"])
    return rows


def write_xlsx(ad_rows: list[list], keyword_rows: list[list], output_dir: Path, headers: list[str]) -> tuple[Path, Path]:
    import openpyxl

    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ads"
    ws.append(headers)
    for row in ad_rows:
        ws.append(row)
    wb.save(ads_path)

    keywords_path = output_dir / "keywords.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Keywords"
    ws.append(["Campaign", "Group", "Keyword", "Type"])
    for row in keyword_rows:
        ws.append(row)
    wb.save(keywords_path)

    return ads_path, keywords_path


def write_csv(ad_rows: list[list], keyword_rows: list[list], output_dir: Path, headers: list[str]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.csv"
    with ads_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in ad_rows:
            writer.writerow(row)

    keywords_path = output_dir / "keywords.csv"
    with keywords_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Campaign", "Group", "Keyword", "Type"])
        for row in keyword_rows:
            writer.writerow(row)

    return ads_path, keywords_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--creatives-json", default=None,
                        help="Путь к 08_creatives.json. По умолч. — <workspace>/08_creatives.json")
    parser.add_argument("--output-dir", default=None,
                        help="Куда сохранить ads и keywords. По умолч. — <workspace>")
    parser.add_argument(
        "--format", choices=["xlsx", "csv", "auto"], default="auto",
        help="auto — попробовать xlsx, при отсутствии openpyxl упасть в csv."
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    creatives_json = resolve_creatives_path(workspace, args.creatives_json)
    output_dir = Path(args.output_dir) if args.output_dir else workspace

    if not creatives_json.exists():
        raise SystemExit(
            f"Файл креативов не найден: {creatives_json}. "
            f"Ожидается {workspace}/08_creatives.json — скилл формирует его на Шаге 8."
        )

    creatives = json.loads(creatives_json.read_text(encoding="utf-8"))
    ad_rows, warnings, headers = select_assembler(creatives)
    keyword_rows = assemble_keyword_rows(creatives)

    chosen_format = args.format
    if chosen_format == "auto":
        try:
            import openpyxl  # noqa: F401
            chosen_format = "xlsx"
        except ImportError:
            chosen_format = "csv"
            print("openpyxl не установлен -> фолбек на CSV (Direct Commander умеет CSV-импорт).")
            print("   Чтобы получить xlsx: pip install openpyxl --break-system-packages")

    if chosen_format == "xlsx":
        try:
            ads_path, keywords_path = write_xlsx(ad_rows, keyword_rows, output_dir, headers)
        except ImportError:
            raise SystemExit(
                "openpyxl недоступен. Установи: pip install openpyxl --break-system-packages "
                "ИЛИ запусти скрипт с --format csv"
            )
    else:
        ads_path, keywords_path = write_csv(ad_rows, keyword_rows, output_dir, headers)

    warn_path = output_dir / "warnings.txt"
    if warnings:
        warn_path.write_text(
            "ПРЕВЫШЕНИЯ ЛИМИТОВ ДИРЕКТА (нужно сократить):\n\n" + "\n".join(warnings),
            encoding="utf-8",
        )
    else:
        warn_path.write_text(
            "OK — все объявления и поля в пределах лимитов Директа.\n"
            f"Объявлений: {len(ad_rows)}, ключей и минусов: {len(keyword_rows)}.\n",
            encoding="utf-8",
        )

    print(f"Формат: {chosen_format}")
    print(f"Объявления: {ads_path}")
    print(f"Ключи и минус-слова: {keywords_path}")
    print(f"Предупреждения: {warn_path}")
    print(f"  -> {warn_path.read_text(encoding='utf-8')[:300]}")


if __name__ == "__main__":
    main()
