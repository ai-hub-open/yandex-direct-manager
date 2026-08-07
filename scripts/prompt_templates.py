"""
prompt_templates.py — шаблоны промптов для генерации РСЯ-картинок через OpenAI.

5 типов креативов под комбинаторное объявление ЕПК:
- product_offer  — оффер: крупное УТП + продукт (дефолт)
- pain_split     — split-screen «до / после»
- abstract_brand — брендовая композиция с коротким текстом
- social_proof   — цифры/результат («200+ клиентов»)
- ui_mockup      — плейсхолдер, нужен реальный скриншот (API не вызывается)

Форматы Яндекса: 1:1, 4:3, 16:9 (и опц. 3:4). OpenAI умеет только
1024x1024 / 1536x1024 / 1024x1536 — постпроцессинг PIL доводит до целевых.
"""

from textwrap import dedent

MAX_IMAGES_PER_AD = 5  # лимит ResponsiveAd.AdImageHashes

IMAGE_SPECS = {
    "1x1":  {"openai_size": "1024x1024", "target_size": (1080, 1080), "ratio_text": "1:1 square"},
    "4x3":  {"openai_size": "1536x1024", "target_size": (1440, 1080), "ratio_text": "4:3 landscape"},
    "16x9": {"openai_size": "1536x1024", "target_size": (1920, 1080), "ratio_text": "16:9 widescreen"},
    "3x4":  {"openai_size": "1024x1536", "target_size": (1080, 1440), "ratio_text": "3:4 portrait"},
}

DEFAULT_FIRST_CONCEPT_FORMATS = ["4x3", "16x9", "1x1"]
DEFAULT_OTHER_CONCEPT_FORMATS = ["4x3", "16x9"]

# Требования Яндекса, зашитые в каждый промпт (модерация + служебные наложения площадок)
YANDEX_RULES = dedent("""
    Composition safety (Yandex ad network requirements — MANDATORY):
    - Keep ALL text and logo inside the central 80% of the canvas: at least 10% margin from every edge
    - Text occupies no more than 20% of the image area, 10 words maximum
    - No ALL-CAPS words longer than 4 letters, at most one exclamation mark
    - No phone numbers, no URLs, no QR codes anywhere on the image
    - Small product wordmark "{product_name}" in a bottom corner

    DO NOT include:
    - Logos of real third-party brands, watermarks
    - Yandex UI elements or fake browser windows
    - Human faces (unless the concept explicitly requires people)
    - More than 10 words of text total
""").strip()

PRODUCT_OFFER = dedent("""
    Advertising banner for {product_name} (Russian ad network placement).

    Composition:
    - Central large bold headline in Russian: "{usp}"
    - Supporting visual: clean product/service scene representing "{angle}"
    - Background: solid or soft-gradient block using {primary_color}, accent details in {accent_color}
    - Style references: {style_refs}
    - Modern flat design with subtle depth, generous whitespace, readable at thumbnail size

    Aspect ratio: {ratio_text}.

    {yandex_rules}
""").strip()

PAIN_SPLIT = dedent("""
    Split-screen "before vs after" advertising banner for {product_name}.

    LEFT HALF ("before" — the problem, related to "{angle}"):
    - Cluttered, stressful scene; muted desaturated beige/grey palette

    RIGHT HALF ("after" — with {product_name}):
    - Clean, calm, organized scene; vibrant brand palette {primary_color} + {accent_color}

    CENTER: thin vertical divider with subtle gradient.
    TOP OVERLAY: one short bold Russian headline: "{usp}"

    Style: flat vector illustration with subtle shadows. Aspect ratio: {ratio_text}.

    {yandex_rules}
""").strip()

ABSTRACT_BRAND = dedent("""
    Abstract brand advertising banner for {product_name}.

    Composition:
    - Bold typographic Russian message: "{usp}"
    - Background: abstract geometric composition (flowing lines, soft shapes) evoking "{angle}"
    - Colors: {primary_color} (~60%), {accent_color} (~30%), light neutral (~10%)
    - Style references: {style_refs}

    Aspect ratio: {ratio_text}.

    {yandex_rules}
""").strip()

SOCIAL_PROOF = dedent("""
    Social-proof advertising banner for {product_name}.

    Composition:
    - One large bold number or fact in Russian as the hero element: "{usp}"
    - Below it: small supporting caption tied to "{angle}"
    - Minimal supporting graphics: subtle stars / laurel / simple chart motif — pick ONE
    - Colors: {primary_color} background block, {accent_color} for the hero number

    Style: confident, editorial, high contrast. Aspect ratio: {ratio_text}.

    {yandex_rules}
""").strip()

UI_MOCKUP_PLACEHOLDER = dedent("""
    [PLACEHOLDER — нужен реальный скриншот продукта, AI-генерация интерфейсов ненадёжна]

    ЗАПРОСИТЬ У КЛИЕНТА:
    - Реальный скриншот {product_name}: экран "{angle}"
    - Разрешение от 2160x2160, PNG
    - Далее вставить в макет вручную или через дизайнера

    Этот файл не отправляется в OpenAI — скрипт пометит креатив как needs_real_screenshot.
""").strip()

TEMPLATES = {
    "product_offer": PRODUCT_OFFER,
    "pain_split": PAIN_SPLIT,
    "abstract_brand": ABSTRACT_BRAND,
    "social_proof": SOCIAL_PROOF,
    "ui_mockup": UI_MOCKUP_PLACEHOLDER,
}


def build_format_plan(concepts):
    """[(concept, fmt), ...] — какие картинки генерить. Не больше MAX_IMAGES_PER_AD."""
    plan = []
    for i, concept in enumerate(concepts):
        fmts = concept.get("formats") or (
            DEFAULT_FIRST_CONCEPT_FORMATS if i == 0 else DEFAULT_OTHER_CONCEPT_FORMATS
        )
        for fmt in fmts:
            if len(plan) >= MAX_IMAGES_PER_AD:
                return plan
            if fmt in IMAGE_SPECS:
                plan.append((concept, fmt))
    return plan


def detect_creative_type(concept):
    """Явный type приоритетен; иначе — ключевые слова angle/notes; дефолт product_offer."""
    explicit = (concept.get("type") or "").strip()
    if explicit in TEMPLATES:
        return explicit
    text = " ".join([concept.get("angle", "") or "", concept.get("notes", "") or ""]).lower()
    if "скриншот" in text or "интерфейс" in text or "ui" in text:
        return "ui_mockup"
    if "до/после" in text or "до после" in text or "боль" in text:
        return "pain_split"
    if any(w in text for w in ("клиентов", "отзыв", "лет на рынке", "выполнено", "рейтинг")):
        return "social_proof"
    if "имидж" in text or "бренд" in text:
        return "abstract_brand"
    return "product_offer"


def build_prompt(concept, brand, group, fmt):
    """Собирает промпт для OpenAI Images API под конкретный формат."""
    ctype = detect_creative_type(concept)
    template = TEMPLATES[ctype]
    product_name = brand.get("product_name", "Product")
    spec = IMAGE_SPECS.get(fmt, IMAGE_SPECS["1x1"])

    if ctype == "ui_mockup":
        return template.format(
            product_name=product_name,
            angle=concept.get("angle", ""),
        )

    return template.format(
        product_name=product_name,
        usp=concept.get("usp_on_creative", "") or group.get("name", ""),
        angle=concept.get("angle", ""),
        primary_color=brand.get("primary_color", "#2D5BFF"),
        accent_color=brand.get("accent_color", "#22C55E"),
        style_refs=", ".join(brand.get("style_references", ["clean flat advertising design"])),
        ratio_text=spec["ratio_text"],
        yandex_rules=YANDEX_RULES.format(product_name=product_name),
    )
