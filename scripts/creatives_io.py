"""
creatives_io.py — разбор 08_creatives.json: одна кампания или пакет кампаний.

Все скрипты, которые читают 08_creatives.json (preflight, generate_ads_xlsx,
generate_creative_images, upload_creatives_to_storage), идут через этот модуль —
иначе генератор, проверка и заливка снова разойдутся по формату.

Два формата:
- одна кампания (как до 0.21.0): `campaign_key`, `campaign_name`, `default_url`,
  `negative_keywords`, `groups` — в корне;
- пакет: `campaigns: [{campaign_key, campaign_name, default_url?, negative_keywords?, groups}, ...]`.
  `default_url` корня — запасной для кампаний без своего.

Схемы — assets/creatives_schema_combined_example.json (одна кампания) и
assets/creatives_schema_package_example.json (пакет).
"""
from __future__ import annotations

from typing import Iterator


def is_package(creatives: dict) -> bool:
    return "campaigns" in creatives


def campaigns_of(creatives: dict) -> list[dict]:
    """Список кампаний. Группы — те же объекты, что в исходном dict: правки в них сохраняются."""
    if not is_package(creatives):
        return [creatives]
    root_url = creatives.get("default_url")
    out = []
    for campaign in creatives.get("campaigns") or []:
        if root_url and not campaign.get("default_url"):
            campaign = {**campaign, "default_url": root_url}
        out.append(campaign)
    return out


def iter_groups(creatives: dict) -> Iterator[tuple[dict, dict]]:
    """(кампания, группа) по всем кампаниям пакета по порядку."""
    for campaign in campaigns_of(creatives):
        for group in campaign.get("groups") or []:
            yield campaign, group
