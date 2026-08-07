"""
video_prompt_templates.py — шаблоны видео-промптов под РСЯ (видеодополнения ЕПК).

3 типа, все без текста в кадре (текст добавляет само объявление):
- pain_reframe     — «до/после» (из visual-концепции pain_split)
- product_showcase — продукт/услуга крупным планом (из product_offer, social_proof)
- brand_motion     — брендовая анимация (из abstract_brand)
"""

from textwrap import dedent

PAIN_REFRAME = dedent("""
    {orientation} {aspect} advertising video, {duration} seconds, for Russian ad network.

    - Opening (0-2s): stressful cluttered scene related to "{angle}" — muted grey palette,
      slow push-in conveying frustration
    - Transition (2-3s): smooth wipe to the right
    - Closing (remaining time): the same need solved with {product_name} — clean organized scene,
      brand colors {primary_color} and {accent_color}, calm satisfied mood

    Style: cinematic, professional. No people's faces. No on-screen text, no logos.
    Aspect ratio: {aspect} {orientation_lower}.
""").strip()

PRODUCT_SHOWCASE = dedent("""
    {orientation} {aspect} advertising video, {duration} seconds, for Russian ad network.

    - Hero shot of {product_name} product/service representing "{angle}": smooth slow camera orbit
      or dolly-in, shallow depth of field
    - Lighting: soft, premium; background tones {primary_color} with {accent_color} accents
    - Final beat (remaining time): composition settles, leaving clean space at the bottom
      (ad text will be overlaid by the ad platform)

    Style: polished commercial, photorealistic. No on-screen text, no logos, no people's faces.
    Aspect ratio: {aspect} {orientation_lower}.
""").strip()

BRAND_MOTION = dedent("""
    {orientation} {aspect} abstract brand animation, {duration} seconds, for Russian ad network.

    - Flowing geometric shapes and gradients in {primary_color} and {accent_color},
      evoking "{angle}"
    - Smooth loops, soft light, modern motion-design aesthetic
    - No text, no logos, no people

    Aspect ratio: {aspect} {orientation_lower}.
""").strip()

VIDEO_TYPE_BY_CONCEPT_TYPE = {
    "pain_split": "pain_reframe",
    "abstract_brand": "brand_motion",
    "product_offer": "product_showcase",
    "social_proof": "product_showcase",
    "ui_mockup": "product_showcase",
}

TEMPLATES = {
    "pain_reframe": PAIN_REFRAME,
    "product_showcase": PRODUCT_SHOWCASE,
    "brand_motion": BRAND_MOTION,
}


def detect_video_type(concept: dict) -> str:
    return VIDEO_TYPE_BY_CONCEPT_TYPE.get(concept.get("type", ""), "product_showcase")


def _get_orientation(aspect: str) -> tuple:
    """Вычисляет ориентацию по aspect ratio. Возвращает (orientation, orientation_lower)."""
    if aspect == "16:9":
        return ("Horizontal", "horizontal")
    elif aspect == "9:16":
        return ("Vertical", "vertical")
    elif aspect == "1:1":
        return ("Square", "square")
    else:
        return ("Horizontal", "horizontal")  # дефолт


def build_video_prompt(concept: dict, brand: dict, duration: int = 5, aspect: str = "16:9") -> str:
    vtype = detect_video_type(concept)
    orientation, orientation_lower = _get_orientation(aspect)
    return TEMPLATES[vtype].format(
        product_name=brand.get("product_name", "Product"),
        primary_color=brand.get("primary_color", "#2D5BFF"),
        accent_color=brand.get("accent_color", "#22C55E"),
        angle=concept.get("angle", "") or concept.get("usp_on_creative", ""),
        duration=duration,
        aspect=aspect,
        orientation=orientation,
        orientation_lower=orientation_lower,
    )
