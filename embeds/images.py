from __future__ import annotations

import io
import logging
import pathlib
from typing import Any
import aiohttp
from PIL import Image, ImageDraw, ImageFont

from .utils import (
    _get_latest_version, DDRAGON_ITEM_ICON, DDRAGON_SPELL_ICON,
    DDRAGON_CHAMPION_ICON, ITEM_ICON_SIZE, ITEM_SPACING, _get_item_ids,
    RANK_COLORS,
)

logger = logging.getLogger("botdiff.embeds.images")

ASSETS_RANK_DIR = pathlib.Path(__file__).parent.parent / "assets" / "rank"

SUMMONER_SPELL_DDRAGON = {
    1: "SummonerBoost", 3: "SummonerExhaust", 4: "SummonerFlash",
    6: "SummonerHaste", 7: "SummonerHeal", 11: "SummonerSmite",
    12: "SummonerTeleport", 13: "SummonerMana", 14: "SummonerDot",
    21: "SummonerBarrier", 30: "SummonerPoroRecall", 31: "SummonerPoroThrow",
    32: "SummonerSnowball",
}

SPELL_ICON_SIZE = 32
SEPARATOR_WIDTH = 8

async def _download_image(session: aiohttp.ClientSession, url: str) -> Image.Image | None:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as exc:
        logger.warning("Impossible de télécharger l'image %s : %s", url, exc)
    return None

async def _build_items_strip(session: aiohttp.ClientSession, item_ids: list[int]) -> io.BytesIO | None:
    if not item_ids:
        return None
    version = await _get_latest_version(session)
    images = []
    for item_id in item_ids:
        url = DDRAGON_ITEM_ICON.format(version=version, item_id=item_id)
        img = await _download_image(session, url)
        if img:
            images.append(img.resize((ITEM_ICON_SIZE, ITEM_ICON_SIZE), Image.LANCZOS))
    if not images:
        return None
    total_width = len(images) * ITEM_ICON_SIZE + (len(images) - 1) * ITEM_SPACING
    strip = Image.new("RGBA", (total_width, ITEM_ICON_SIZE), (0, 0, 0, 0))
    x = 0
    for img in images:
        strip.paste(img, (x, 0))
        x += ITEM_ICON_SIZE + ITEM_SPACING
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    buf.seek(0)
    return buf

async def _build_game_strip(session: aiohttp.ClientSession, participant: dict[str, Any]) -> io.BytesIO | None:
    s1, s2 = participant.get("summoner1Id", 0), participant.get("summoner2Id", 0)
    item_ids = _get_item_ids(participant)
    if not item_ids and s1 == 0 and s2 == 0:
        return None
    version = await _get_latest_version(session)
    spell_images = []
    for spell_id in (s1, s2):
        spell_name = SUMMONER_SPELL_DDRAGON.get(spell_id)
        if spell_name:
            img = await _download_image(session, DDRAGON_SPELL_ICON.format(version=version, spell=spell_name))
            if img: spell_images.append(img.resize((SPELL_ICON_SIZE, SPELL_ICON_SIZE), Image.LANCZOS))
    item_images = []
    for item_id in item_ids:
        img = await _download_image(session, DDRAGON_ITEM_ICON.format(version=version, item_id=item_id))
        if img: item_images.append(img.resize((ITEM_ICON_SIZE, ITEM_ICON_SIZE), Image.LANCZOS))
    
    fixed_spells_w = 2 * (SPELL_ICON_SIZE + ITEM_SPACING)
    fixed_items_w = 7 * (ITEM_ICON_SIZE + ITEM_SPACING) - ITEM_SPACING
    total_width = fixed_spells_w + SEPARATOR_WIDTH + fixed_items_w
    strip = Image.new("RGBA", (total_width, ITEM_ICON_SIZE), (47, 49, 54, 255))
    x = 0
    spell_y = (ITEM_ICON_SIZE - SPELL_ICON_SIZE) // 2
    for img in spell_images:
        strip.paste(img, (x, spell_y))
        x += SPELL_ICON_SIZE + ITEM_SPACING
    x = fixed_spells_w + SEPARATOR_WIDTH
    for img in item_images:
        strip.paste(img, (x, 0))
        x += ITEM_ICON_SIZE + ITEM_SPACING
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    buf.seek(0)
    return buf

async def _build_top_champs_strip(session: aiohttp.ClientSession, top_champs: list[tuple[str, int]]) -> io.BytesIO | None:
    if not top_champs: return None
    version = await _get_latest_version(session)
    images = []
    for champ_name, _ in top_champs:
        img = await _download_image(session, DDRAGON_CHAMPION_ICON.format(version=version, champion=champ_name))
        if img: images.append(img.resize((64, 64), Image.LANCZOS))
    if not images: return None
    spacing = 10
    total_width = len(images) * 64 + (len(images) - 1) * spacing
    strip = Image.new("RGBA", (total_width, 64), (0, 0, 0, 0))
    x = 0
    for img in images:
        strip.paste(img, (x, 0))
        x += 64 + spacing
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    buf.seek(0)
    return buf


def build_rank_change_image(
    old_tier: str,
    new_tier: str,
    old_rank: str,
    new_rank: str,
    is_promotion: bool,
) -> io.BytesIO | None:
    """Compose une image bannière pour un changement de tier (ex: Silver → Gold).

    Retourne un BytesIO PNG ou None si les assets sont introuvables.
    """
    old_path = ASSETS_RANK_DIR / f"{old_tier.lower()}.png"
    new_path = ASSETS_RANK_DIR / f"{new_tier.lower()}.png"

    if not old_path.exists() or not new_path.exists():
        logger.warning("Assets rank introuvables : %s ou %s", old_path, new_path)
        return None

    EMBLEM_SIZE = 200
    ARROW_ZONE = 110
    PADDING_X = 40
    PADDING_TOP = 20
    LABEL_HEIGHT = 60
    WIDTH = EMBLEM_SIZE * 2 + ARROW_ZONE + PADDING_X * 2
    HEIGHT = EMBLEM_SIZE + LABEL_HEIGHT + PADDING_TOP + 20

    # ── Dégradé horizontal : couleur ancien rang → couleur nouveau rang (assombries)
    def _hex_to_dark_rgb(hex_color: int, factor: float = 0.25) -> tuple[int, int, int]:
        r = int(((hex_color >> 16) & 0xFF) * factor)
        g = int(((hex_color >> 8) & 0xFF) * factor)
        b = int((hex_color & 0xFF) * factor)
        return (max(r, 18), max(g, 18), max(b, 18))

    old_rgb = _hex_to_dark_rgb(RANK_COLORS.get(old_tier.upper(), 0x2C2F33))
    new_rgb = _hex_to_dark_rgb(RANK_COLORS.get(new_tier.upper(), 0x2C2F33))

    bg = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw_bg = ImageDraw.Draw(bg)
    for x in range(WIDTH):
        t = x / (WIDTH - 1)
        r = int(old_rgb[0] + (new_rgb[0] - old_rgb[0]) * t)
        g = int(old_rgb[1] + (new_rgb[1] - old_rgb[1]) * t)
        b = int(old_rgb[2] + (new_rgb[2] - old_rgb[2]) * t)
        draw_bg.line([(x, 0), (x, HEIGHT)], fill=(r, g, b, 255))

    # Charger et coller les emblèmes
    old_img = Image.open(old_path).convert("RGBA").resize((EMBLEM_SIZE, EMBLEM_SIZE), Image.LANCZOS)
    new_img = Image.open(new_path).convert("RGBA").resize((EMBLEM_SIZE, EMBLEM_SIZE), Image.LANCZOS)

    old_x = PADDING_X
    new_x = PADDING_X + EMBLEM_SIZE + ARROW_ZONE
    emblem_y = PADDING_TOP

    bg.paste(old_img, (old_x, emblem_y), old_img)
    bg.paste(new_img, (new_x, emblem_y), new_img)

    draw = ImageDraw.Draw(bg)

    # ── Flèche dessinée avec PIL (pas d'unicode) ──────────────
    arrow_color = (80, 230, 110) if is_promotion else (230, 70, 70)
    cx = PADDING_X + EMBLEM_SIZE + ARROW_ZONE // 2
    cy = PADDING_TOP + EMBLEM_SIZE // 2

    if is_promotion:
        # Flèche horizontale →
        lw = 5          # épaisseur trait
        body_len = 36   # longueur du corps
        head_w = 18     # demi-hauteur de la tête
        head_len = 18   # longueur de la tête

        x0 = cx - (body_len + head_len) // 2
        x_mid = x0 + body_len
        x1 = x_mid + head_len

        # Corps
        draw.rectangle([x0, cy - lw // 2, x_mid, cy + lw // 2], fill=arrow_color)
        # Tête (triangle)
        draw.polygon([
            (x_mid, cy - head_w),
            (x1,    cy),
            (x_mid, cy + head_w),
        ], fill=arrow_color)
    else:
        # Flèche vers le bas ↓
        lw = 5
        body_len = 36
        head_w = 18
        head_len = 18

        y0 = cy - (body_len + head_len) // 2
        y_mid = y0 + body_len
        y1 = y_mid + head_len

        # Corps
        draw.rectangle([cx - lw // 2, y0, cx + lw // 2, y_mid], fill=arrow_color)
        # Tête (triangle)
        draw.polygon([
            (cx - head_w, y_mid),
            (cx,          y1),
            (cx + head_w, y_mid),
        ], fill=arrow_color)

    # ── Labels sous les emblèmes ──────────────────────────────
    try:
        font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    except OSError:
        font_label = ImageFont.load_default()

    label_y = PADDING_TOP + EMBLEM_SIZE + 8
    old_label = f"{old_tier.title()} {old_rank}"
    new_label = f"{new_tier.title()} {new_rank}"

    label_color = (220, 220, 220, 255)

    bbox_old = draw.textbbox((0, 0), old_label, font=font_label)
    tw_old = bbox_old[2] - bbox_old[0]
    draw.text(
        (old_x + (EMBLEM_SIZE - tw_old) // 2, label_y),
        old_label, font=font_label, fill=label_color,
    )

    bbox_new = draw.textbbox((0, 0), new_label, font=font_label)
    tw_new = bbox_new[2] - bbox_new[0]
    draw.text(
        (new_x + (EMBLEM_SIZE - tw_new) // 2, label_y),
        new_label, font=font_label, fill=label_color,
    )

    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    buf.seek(0)
    return buf

