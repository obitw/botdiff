"""
embeds.py — Construction des Embeds Discord pour les résultats de match.

Produit un Embed riche :
  • Couleur verte / rouge selon victoire / défaite
  • Champs par joueur traqué : champion (icône), KDA, CS, dégâts, vision, items
  • Lien OP.GG par joueur
  • Infos du match en footer (mode, durée)
  • Images composites des items générées avec Pillow
"""

from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp
import discord
from PIL import Image

logger = logging.getLogger("botdiff.embeds")

# ── Data Dragon (dernière version stable) ───────────────────
DDRAGON_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_VERSION = "14.6.1"
DDRAGON_CHAMPION_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion}.png"
)
DDRAGON_CHAMPION_SPLASH = (
    "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{champion}_0.jpg"
)
DDRAGON_ITEM_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png"
)
DDRAGON_SPELL_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/spell/{spell}.png"
)

OPGG_PROFILE_URL = "https://www.op.gg/lol/summoners/{region}/{riot_id}-{tag}"

# ── Mapping platform Riot → région OP.GG ────────────────────
PLATFORM_TO_OPGG: dict[str, str] = {
    "euw1": "euw",
    "eun1": "eune",
    "na1": "na",
    "kr": "kr",
    "jp1": "jp",
    "br1": "br",
    "la1": "lan",
    "la2": "las",
    "oc1": "oce",
    "tr1": "tr",
    "ru": "ru",
    "ph2": "ph",
    "sg2": "sg",
    "th2": "th",
    "tw2": "tw",
    "vn2": "vn",
    "me1": "me",
}

# ── Couleurs ────────────────────────────────────────────────
COLOR_WIN = 0x2ECC71   # Vert
COLOR_LOSS = 0xE74C3C  # Rouge

# ── Mapping des queues courantes ────────────────────────────
QUEUE_NAMES: dict[int, str] = {
    420: "Classée Solo/Duo",
    440: "Classée Flex",
    400: "Normal Draft",
    430: "Normal Blind",
    450: "ARAM",
    490: "Normal (Quickplay)",
    700: "Clash",
    720: "ARAM Clash",
    900: "URF",
    1020: "One for All",
    1300: "Nexus Blitz",
    1700: "Arena",
}

# ── Mapping des Summoner Spells ─────────────────────────────
SUMMONER_SPELL_NAMES: dict[int, str] = {
    1: "Purification",
    3: "Épuisement",
    4: "Flash",
    6: "Fantôme",
    7: "Soin",
    11: "Châtiment",
    12: "Téléportation",
    13: "Clarté",
    14: "Embrasement",
    21: "Barrière",
    30: "To the King!",
    31: "Poro",
    32: "Boule de neige",
}

# ── Taille des icônes pour le strip items ───────────────────
ITEM_ICON_SIZE = 48
ITEM_SPACING = 4


# ════════════════════════════════════════════════════════════
# Fonctions utilitaires
# ════════════════════════════════════════════════════════════


def _format_duration(seconds: int) -> str:
    """Renvoie une durée lisible `XXm YYs`."""
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


def _find_participant(match_data: dict[str, Any], puuid: str) -> dict[str, Any] | None:
    """Trouve le bloc participant correspondant au PUUID donné."""
    for p in match_data["info"]["participants"]:
        if p["puuid"] == puuid:
            return p
    return None


def _format_spells(participant: dict[str, Any]) -> str:
    """Renvoie les noms des deux summoner spells."""
    s1 = participant.get("summoner1Id", 0)
    s2 = participant.get("summoner2Id", 0)
    name1 = SUMMONER_SPELL_NAMES.get(s1, "?")
    name2 = SUMMONER_SPELL_NAMES.get(s2, "?")
    return f"{name1} / {name2}"


def _get_item_ids(participant: dict[str, Any]) -> list[int]:
    """Extrait les IDs d'items non-nuls (item0 à item6)."""
    return [
        participant.get(f"item{i}", 0)
        for i in range(7)
        if participant.get(f"item{i}", 0) != 0
    ]


async def _download_image(session: aiohttp.ClientSession, url: str) -> Image.Image | None:
    """Télécharge une image depuis une URL et la renvoie comme objet PIL."""
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as exc:
        logger.warning("Impossible de télécharger l'image %s : %s", url, exc)
    return None


async def _build_items_strip(
    session: aiohttp.ClientSession,
    item_ids: list[int],
) -> io.BytesIO | None:
    """
    Télécharge les icônes d'items et les assemble en une bande horizontale.
    Renvoie un BytesIO contenant l'image PNG, ou None si aucun item.
    """
    if not item_ids:
        return None

    # Télécharger toutes les icônes.
    images: list[Image.Image] = []
    for item_id in item_ids:
        url = DDRAGON_ITEM_ICON.format(version=DDRAGON_VERSION, item_id=item_id)
        img = await _download_image(session, url)
        if img:
            img = img.resize((ITEM_ICON_SIZE, ITEM_ICON_SIZE), Image.LANCZOS)
            images.append(img)

    if not images:
        return None

    # Assembler en une bande horizontale.
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


# ── Mapping Summoner Spell ID → nom Data Dragon ────────────
SUMMONER_SPELL_DDRAGON: dict[int, str] = {
    1: "SummonerBoost",
    3: "SummonerExhaust",
    4: "SummonerFlash",
    6: "SummonerHaste",
    7: "SummonerHeal",
    11: "SummonerSmite",
    12: "SummonerTeleport",
    13: "SummonerMana",
    14: "SummonerDot",
    21: "SummonerBarrier",
    30: "SummonerPoroRecall",
    31: "SummonerPoroThrow",
    32: "SummonerSnowball",
}

SPELL_ICON_SIZE = 32
SEPARATOR_WIDTH = 8


async def _build_game_strip(
    session: aiohttp.ClientSession,
    participant: dict[str, Any],
) -> io.BytesIO | None:
    """
    Génère une bande horizontale :
      [Spell1] [Spell2]  |  [Item0] [Item1] ... [Item6]
    Spells en 32px, items en 48px, fond sombre Discord.
    """
    s1 = participant.get("summoner1Id", 0)
    s2 = participant.get("summoner2Id", 0)
    item_ids = _get_item_ids(participant)

    if not item_ids and s1 == 0 and s2 == 0:
        return None

    # ── Télécharger les icônes de spells ────────────────────
    spell_images: list[Image.Image] = []
    for spell_id in (s1, s2):
        spell_name = SUMMONER_SPELL_DDRAGON.get(spell_id)
        if spell_name:
            url = DDRAGON_SPELL_ICON.format(version=DDRAGON_VERSION, spell=spell_name)
            img = await _download_image(session, url)
            if img:
                img = img.resize((SPELL_ICON_SIZE, SPELL_ICON_SIZE), Image.LANCZOS)
                spell_images.append(img)

    # ── Télécharger les icônes d'items ──────────────────────
    item_images: list[Image.Image] = []
    for item_id in item_ids:
        url = DDRAGON_ITEM_ICON.format(version=DDRAGON_VERSION, item_id=item_id)
        img = await _download_image(session, url)
        if img:
            img = img.resize((ITEM_ICON_SIZE, ITEM_ICON_SIZE), Image.LANCZOS)
            item_images.append(img)

    # ── Calcul des dimensions (largeur fixe) ──────────────────
    MAX_SPELL_SLOTS = 2
    MAX_ITEM_SLOTS = 7
    fixed_spells_w = MAX_SPELL_SLOTS * (SPELL_ICON_SIZE + ITEM_SPACING)
    fixed_items_w = MAX_ITEM_SLOTS * (ITEM_ICON_SIZE + ITEM_SPACING) - ITEM_SPACING
    total_width = fixed_spells_w + SEPARATOR_WIDTH + fixed_items_w
    total_height = ITEM_ICON_SIZE

    strip = Image.new("RGBA", (total_width, total_height), (47, 49, 54, 255))

    # Spells (centrées verticalement).
    x = 0
    spell_y = (ITEM_ICON_SIZE - SPELL_ICON_SIZE) // 2
    for img in spell_images:
        strip.paste(img, (x, spell_y))
        x += SPELL_ICON_SIZE + ITEM_SPACING

    # Sauter à la position fixe des items (après les 2 slots de spells + séparateur).
    x = fixed_spells_w + SEPARATOR_WIDTH

    # Items.
    for img in item_images:
        strip.paste(img, (x, 0))
        x += ITEM_ICON_SIZE + ITEM_SPACING

    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
# build_match_embed — Alerte de fin de partie
# ════════════════════════════════════════════════════════════


async def build_match_embed(
    match_data: dict[str, Any],
    tracked_players: list[dict[str, Any]],
    platform: str = "euw1",
    session: aiohttp.ClientSession | None = None,
) -> tuple[discord.Embed, list[discord.File], discord.ui.View]:
    """
    Construit un Embed + fichiers d'items + View pour un match terminé.

    Returns
    -------
    (discord.Embed, list[discord.File], discord.ui.View)
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        info = match_data["info"]
        game_duration = info.get("gameDuration", 0)
        queue_id = info.get("queueId", 0)
        queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")

        first_participant = _find_participant(match_data, tracked_players[0]["puuid"])
        won = first_participant["win"] if first_participant else False
        color = COLOR_WIN if won else COLOR_LOSS
        result_text = "✅ Victoire" if won else "❌ Défaite"

        embed = discord.Embed(
            title=f"{'🏆' if won else '💀'}  Partie terminée — {result_text}",
            color=color,
        )

        files: list[discord.File] = []
        last_champion = None

        for idx, tp in enumerate(tracked_players):
            participant = _find_participant(match_data, tp["puuid"])
            if participant is None:
                continue

            champion = participant["championName"]
            kills = participant["kills"]
            deaths = participant["deaths"]
            assists = participant["assists"]
            kda_ratio = (kills + assists) / max(deaths, 1)
            cs = participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0)
            cs_per_min = cs / max(game_duration / 60, 1)
            damage = participant["totalDamageDealtToChampions"]
            vision = participant["visionScore"]
            player_won = participant["win"]
            spells = _format_spells(participant)

            player_result = "✅" if player_won else "❌"
            field_name = f"{player_result}  {tp['riot_id']}#{tp['tag']}  —  {champion}"

            field_value = (
                f"**KDA** : {kills}/{deaths}/{assists}  ({kda_ratio:.2f})\n"
                f"**CS** : {cs}  ({cs_per_min:.1f}/min)\n"
                f"**Dégâts** : {damage:,}\n"
                f"**Vision** : {vision}\n"
                f"**Spells** : {spells}"
            )

            embed.add_field(name=field_name, value=field_value, inline=False)
            last_champion = champion

            # Générer l'image composite spells + items.
            strip_buf = await _build_game_strip(session, participant)
            if strip_buf:
                filename = f"match_{idx}.png"
                files.append(discord.File(strip_buf, filename=filename))

        # Images du dernier champion.
        if last_champion:
            embed.set_thumbnail(
                url=DDRAGON_CHAMPION_ICON.format(
                    version=DDRAGON_VERSION, champion=last_champion
                )
            )

        # Utiliser la dernière image spells+items comme image embed.
        if files:
            last_file = files[-1]
            embed.set_image(url=f"attachment://{last_file.filename}")

        embed.set_footer(text=f"{queue_name}  •  Durée : {_format_duration(game_duration)}")

        view = discord.ui.View()
        for tp in tracked_players:
            opgg_region = PLATFORM_TO_OPGG.get(platform, platform)
            opgg_url = OPGG_PROFILE_URL.format(
                region=opgg_region,
                riot_id=tp["riot_id"].replace(" ", "%20"),
                tag=tp["tag"],
            )
            view.add_item(
                discord.ui.Button(
                    label=f"OP.GG — {tp['riot_id']}",
                    url=opgg_url,
                    style=discord.ButtonStyle.link,
                )
            )

        return embed, files, view

    finally:
        if own_session and session:
            await session.close()


# ════════════════════════════════════════════════════════════
# build_history_embed — /history
# ════════════════════════════════════════════════════════════


async def build_history_embed(
    riot_id: str,
    tag: str,
    puuid: str,
    matches: list[dict[str, Any]],
    platform: str = "euw1",
    session: aiohttp.ClientSession | None = None,
) -> tuple[list[discord.Embed], list[discord.File], discord.ui.View]:
    """
    Construit un Embed par partie, chacun avec :
      • Thumbnail champion
      • Stats compactes (KDA, CS, dégâts, vision)
      • Image composite : spells + items

    Tous les embeds sont envoyés dans UN SEUL message Discord.

    Returns
    -------
    (list[discord.Embed], list[discord.File], discord.ui.View)
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        embeds: list[discord.Embed] = []
        files: list[discord.File] = []

        # Embed titre.
        title_embed = discord.Embed(
            title=f"📜  Historique — {riot_id}#{tag}",
            description=f"{len(matches)} partie(s) récente(s)",
            color=0x3498DB,
        )
        embeds.append(title_embed)

        for game_idx, match_data in enumerate(matches):
            participant = _find_participant(match_data, puuid)
            if participant is None:
                continue

            info = match_data["info"]
            champion = participant["championName"]
            kills = participant["kills"]
            deaths = participant["deaths"]
            assists = participant["assists"]
            kda_ratio = (kills + assists) / max(deaths, 1)
            cs = participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0)
            game_duration = info.get("gameDuration", 0)
            cs_per_min = cs / max(game_duration / 60, 1)
            damage = participant["totalDamageDealtToChampions"]
            vision = participant["visionScore"]
            won = participant["win"]
            queue_id = info.get("queueId", 0)
            queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")

            champion_icon = DDRAGON_CHAMPION_ICON.format(
                version=DDRAGON_VERSION, champion=champion
            )

            color = COLOR_WIN if won else COLOR_LOSS
            result_text = "Victoire" if won else "Défaite"
            result_emoji = "🏆" if won else "💀"

            description = (
                f"### {result_emoji} {champion} — {result_text}\n"
                f"**{kills} / {deaths} / {assists}**  ({kda_ratio:.2f} KDA)\n"
                f"CS {cs} ({cs_per_min:.1f}/min)  •  {damage:,} dégâts  •  👁 {vision}"
            )

            embed = discord.Embed(color=color, description=description)
            embed.set_thumbnail(url=champion_icon)
            embed.set_footer(text=f"{queue_name}  •  {_format_duration(game_duration)}")

            # Générer l'image composite spells + items.
            strip_buf = await _build_game_strip(session, participant)
            if strip_buf:
                filename = f"game_{game_idx}.png"
                files.append(discord.File(strip_buf, filename=filename))
                embed.set_image(url=f"attachment://{filename}")

            embeds.append(embed)

        # Bouton OP.GG.
        opgg_region = PLATFORM_TO_OPGG.get(platform, platform)
        opgg_url = OPGG_PROFILE_URL.format(
            region=opgg_region,
            riot_id=riot_id.replace(" ", "%20"),
            tag=tag,
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label=f"OP.GG — {riot_id}",
                url=opgg_url,
                style=discord.ButtonStyle.link,
            )
        )

        return embeds, files, view

    finally:
        if own_session and session:
            await session.close()
