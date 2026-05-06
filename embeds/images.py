from __future__ import annotations

import io
import logging
from typing import Any
import aiohttp
from PIL import Image

from .utils import (
    _get_latest_version, DDRAGON_ITEM_ICON, DDRAGON_SPELL_ICON,
    DDRAGON_CHAMPION_ICON, ITEM_ICON_SIZE, ITEM_SPACING, _get_item_ids
)

logger = logging.getLogger("botdiff.embeds.images")

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
