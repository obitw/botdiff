from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger("botdiff.embeds.utils")

# ── Data Dragon ───────────────────
DDRAGON_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
_cached_ddragon_version = "14.6.1"
_last_version_check = 0.0
VERSION_CHECK_INTERVAL = 3600

async def _get_latest_version(session: aiohttp.ClientSession) -> str:
    global _cached_ddragon_version, _last_version_check
    now = time.time()
    if now - _last_version_check < VERSION_CHECK_INTERVAL:
        return _cached_ddragon_version
    try:
        async with session.get(DDRAGON_VERSION_URL) as resp:
            if resp.status == 200:
                versions = await resp.json()
                if versions and isinstance(versions, list):
                    _cached_ddragon_version = str(versions[0])
                    _last_version_check = now
    except Exception as exc:
        logger.warning("Impossible de récupérer la version Data Dragon: %s", exc)
    return _cached_ddragon_version

DDRAGON_CHAMPION_ICON = "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion}.png"
DDRAGON_CHAMPION_SPLASH = "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{champion}_0.jpg"
DDRAGON_PROFILE_ICON = "https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/{icon_id}.png"
DDRAGON_ITEM_ICON = "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png"
DDRAGON_SPELL_ICON = "https://ddragon.leagueoflegends.com/cdn/{version}/img/spell/{spell}.png"
CD_RANK_ICON = "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblem/emblem-{tier}.png"
DPM_PROFILE_URL = "https://dpm.lol/{riot_id}-{tag}"

COLOR_WIN = 0x2ECC71
COLOR_LOSS = 0xE74C3C

RANK_COLORS = {
    "IRON": 0x514A44, "BRONZE": 0x8C523A, "SILVER": 0x80989D,
    "GOLD": 0xCD8837, "PLATINUM": 0x4E9996, "EMERALD": 0x27B366,
    "DIAMOND": 0x576BCE, "MASTER": 0x9D5ADE, "GRANDMASTER": 0xCD4545,
    "CHALLENGER": 0xF4C066, "UNRANKED": 0x34495E,
}

QUEUE_NAMES = {
    420: "Classée Solo/Duo", 440: "Classée Flex", 400: "Normal Draft",
    430: "Normal Blind", 450: "ARAM", 490: "Normal (Quickplay)",
    700: "Clash", 720: "ARAM Clash", 900: "URF",
    1020: "One for All", 1300: "Nexus Blitz", 1700: "Arena",
}

SUMMONER_SPELL_NAMES = {
    1: "Purification", 3: "Épuisement", 4: "Flash", 6: "Fantôme",
    7: "Soin", 11: "Châtiment", 12: "Téléportation", 13: "Clarté",
    14: "Embrasement", 21: "Barrière", 30: "To the King!",
    31: "Poro", 32: "Boule de neige",
}

RANK_EMOJIS = {
    "IRON": "🟤", "BRONZE": "🟫", "SILVER": "⚪", "GOLD": "🟡",
    "PLATINUM": "🟢", "EMERALD": "✳️", "DIAMOND": "💎",
    "MASTER": "🟣", "GRANDMASTER": "🔴", "CHALLENGER": "👑",
}

TEAM_CONFIG = {
    100: {"name": "🔵 Bleu", "icon": "🔹", "bar": "🟦"},
    200: {"name": "🔴 Rouge", "icon": "🔸", "bar": "🟥"},
    0: {"name": "Équipe ?", "icon": "◽", "bar": "⬜"},
}

ITEM_ICON_SIZE = 48
ITEM_SPACING = 4

def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"

def _find_participant(match_data: dict[str, Any], puuid: str) -> dict[str, Any] | None:
    for p in match_data["info"]["participants"]:
        if p["puuid"] == puuid:
            return p
    return None

def _format_spells(participant: dict[str, Any]) -> str:
    s1 = participant.get("summoner1Id", 0)
    s2 = participant.get("summoner2Id", 0)
    return f"{SUMMONER_SPELL_NAMES.get(s1, '?')} / {SUMMONER_SPELL_NAMES.get(s2, '?')}"

def _get_item_ids(participant: dict[str, Any]) -> list[int]:
    return [participant.get(f"item{i}", 0) for i in range(7) if participant.get(f"item{i}", 0) != 0]
