"""
embeds.py — Construction des Embeds Discord pour les résultats de match.

Produit un Embed riche :
  • Couleur verte / rouge selon victoire / défaite
  • Champs par joueur traqué : champion (icône), KDA, CS, dégâts, vision, items
  • Profil DPM.LOL par joueur
  • Infos du match en footer (mode, durée)
  • Images composites des items générées avec Pillow
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any


import aiohttp
import discord
import time
from PIL import Image

logger = logging.getLogger("botdiff.embeds")

# ── Data Dragon (dernière version stable) ───────────────────
DDRAGON_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"

_cached_ddragon_version = "14.6.1"
_last_version_check = 0.0
VERSION_CHECK_INTERVAL = 3600  # 1 heure


async def _get_latest_version(session: aiohttp.ClientSession) -> str:
    """Récupère la dernière version de Data Dragon et la cache pour 1h."""
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
                    logger.info("Version Data Dragon mise à jour : %s", _cached_ddragon_version)
    except Exception as exc:
        logger.warning(
            "Impossible de récupérer la version Data Dragon, utilisation de %s : %s",
            _cached_ddragon_version,
            exc,
        )

    return _cached_ddragon_version
DDRAGON_CHAMPION_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion}.png"
)
DDRAGON_CHAMPION_SPLASH = (
    "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{champion}_0.jpg"
)
DDRAGON_PROFILE_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/{icon_id}.png"
)
DDRAGON_ITEM_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png"
)
DDRAGON_SPELL_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/spell/{spell}.png"
)
CD_RANK_ICON = (
    "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblem/emblem-{tier}.png"
)

DPM_PROFILE_URL = "https://dpm.lol/{riot_id}-{tag}"

# ── Couleurs ────────────────────────────────────────────────
COLOR_WIN = 0x2ECC71   # Vert
COLOR_LOSS = 0xE74C3C  # Rouge

# ── Couleurs des rangs ──────────────────────────────────────
RANK_COLORS: dict[str, int] = {
    "IRON": 0x514A44,
    "BRONZE": 0x8C523A,
    "SILVER": 0x80989D,
    "GOLD": 0xCD8837,
    "PLATINUM": 0x4E9996,
    "EMERALD": 0x27B366,
    "DIAMOND": 0x576BCE,
    "MASTER": 0x9D5ADE,
    "GRANDMASTER": 0xCD4545,
    "CHALLENGER": 0xF4C066,
    "UNRANKED": 0x34495E,
}

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

# 🛠️ Nouveaux emojis pour les rangs (style Discord)
RANK_EMOJIS: dict[str, str] = {
    "IRON": "🟤",
    "BRONZE": "🟫",
    "SILVER": "⚪",
    "GOLD": "🟡",
    "PLATINUM": "🟢",
    "EMERALD": "✳️",
    "DIAMOND": "💎",
    "MASTER": "🟣",
    "GRANDMASTER": "🔴",
    "CHALLENGER": "👑",
}

# ── Emojis Teams ────────────────────────────────────────────
TEAM_CONFIG = {
    100: {"name": "🔵 Bleu", "icon": "🔹", "bar": "🟦"},
    200: {"name": "🔴 Rouge", "icon": "🔸", "bar": "🟥"},
    0:   {"name": "Équipe ?", "icon": "◽", "bar": "⬜"}
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
    version = await _get_latest_version(session)
    images: list[Image.Image] = []
    for item_id in item_ids:
        url = DDRAGON_ITEM_ICON.format(version=version, item_id=item_id)
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
    version = await _get_latest_version(session)
    spell_images: list[Image.Image] = []
    for spell_id in (s1, s2):
        spell_name = SUMMONER_SPELL_DDRAGON.get(spell_id)
        if spell_name:
            url = DDRAGON_SPELL_ICON.format(version=version, spell=spell_name)
            img = await _download_image(session, url)
            if img:
                img = img.resize((SPELL_ICON_SIZE, SPELL_ICON_SIZE), Image.LANCZOS)
                spell_images.append(img)

    # ── Télécharger les icônes d'items ──────────────────────
    item_images: list[Image.Image] = []
    for item_id in item_ids:
        url = DDRAGON_ITEM_ICON.format(version=version, item_id=item_id)
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


async def _build_top_champs_strip(
    session: aiohttp.ClientSession,
    top_champs: list[tuple[str, int]],
) -> io.BytesIO | None:
    """
    Génère une bande horizontale d'icônes de champions.
    """
    if not top_champs:
        return None

    version = await _get_latest_version(session)
    images: list[Image.Image] = []
    for champ_name, _ in top_champs:
        url = DDRAGON_CHAMPION_ICON.format(version=version, champion=champ_name)
        img = await _download_image(session, url)
        if img:
            img = img.resize((64, 64), Image.LANCZOS)
            images.append(img)

    if not images:
        return None

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


# ════════════════════════════════════════════════════════════
# build_match_embed — Alerte de fin de partie
# ════════════════════════════════════════════════════════════


async def build_profile_embed(
    riot_id: str,
    tag: str,
    summoner: dict[str, Any],
    league_entries: list[dict[str, Any]],
    last_matches: list[dict[str, Any]],
    puuid: str,
    platform: str = "euw1",
    session: aiohttp.ClientSession | None = None,
) -> tuple[discord.Embed, list[discord.File], discord.ui.View]:
    """Construit un embed de profil complet avec statistiques moyennes."""
    level = summoner["summonerLevel"]
    profile_icon_id = summoner["profileIconId"]
    
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        # 1. Traitement du classement
        ranked_solo = "Unranked"
        ranked_flex = "Unranked"
        best_tier = "UNRANKED"

        for entry in league_entries:
            tier = entry["tier"]
            rank = entry["rank"]
            lp = entry["leaguePoints"]
            wins = entry["wins"]
            losses = entry["losses"]
            wr = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
            
            info = f"**{tier.title()} {rank}** ({lp} LP)\n{wins}W / {losses}L — {wr:.1f}% WR"
            
            if entry["queueType"] == "RANKED_SOLO_5x5":
                ranked_solo = info
                best_tier = tier
            elif entry["queueType"] == "RANKED_FLEX_SR":
                ranked_flex = info
                if best_tier == "UNRANKED":
                    best_tier = tier

        # 2. Statistiques moyennes
        total_kills, total_deaths, total_assists = 0, 0, 0
        total_cs, total_min, total_damage = 0, 0, 0
        champions_count: dict[str, int] = {}
        
        count = 0
        for match in last_matches:
            parts = match["info"]["participants"]
            p = next((x for x in parts if x["puuid"] == puuid), None)
            if not p:
                continue
                
            count += 1
            total_kills += p["kills"]
            total_deaths += p["deaths"]
            total_assists += p["assists"]
            total_cs += p["totalMinionsKilled"] + p["neutralMinionsKilled"]
            total_min += (match["info"].get("gameDuration", 0)) / 60
            total_damage += p["totalDamageDealtToChampions"]
            
            champ = p["championName"]
            champions_count[champ] = champions_count.get(champ, 0) + 1

        if count > 0:
            avg_k, avg_d, avg_a = total_kills/count, total_deaths/count, total_assists/count
            avg_kda = (total_kills + total_assists) / max(total_deaths, 1)
            avg_cs_min = total_cs / total_min if total_min > 0 else 0
            avg_dmg = total_damage / count
            stats_val = (
                f"⚔️ **KDA:** {avg_k:.1f} / {avg_d:.1f} / {avg_a:.1f} — (**{avg_kda:.2f}**)\n"
                f"🌾 **CS/min:** {avg_cs_min:.1f}  •  💥 **Dégâts:** {int(avg_dmg):,}"
            )
        else:
            stats_val = "Aucune partie récente trouvée."

        top_champs = sorted(champions_count.items(), key=lambda x: x[1], reverse=True)[:3]
        top_champs_str = ", ".join([f"**{c}** ({n})" for c, n in top_champs])

        # 3. Construction de l'Embed
        color = RANK_COLORS.get(best_tier, 0x34495E)
        embed = discord.Embed(color=color, description=f"### 🎖️ Level {level}")
        
        # Author : Invocateur + Icône de profil
        version = await _get_latest_version(session)
        profile_icon_url = DDRAGON_PROFILE_ICON.format(version=version, icon_id=profile_icon_id)
        embed.set_author(name=f"{riot_id}#{tag}", icon_url=profile_icon_url)
        
        files: list[discord.File] = []

        # Thumbnail : Rang cropé
        if best_tier != "UNRANKED":
            url = CD_RANK_ICON.format(tier=best_tier.lower())
            img = await _download_image(session, url)
            if img:
                bbox = img.getbbox()
                if bbox: img = img.crop(bbox)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                files.append(discord.File(buf, filename="rank.png"))
                embed.set_thumbnail(url="attachment://rank.png")

        # Champs
        embed.add_field(name="🏆 Ranked Solo/Duo", value=ranked_solo, inline=True)
        embed.add_field(name="⚔️ Ranked Flex", value=ranked_flex, inline=True)
        
        embed.add_field(name=f"📊 Moyennes ({count} parties)", value=stats_val, inline=False)
        
        if top_champs:
            embed.add_field(name="👑 Champions favoris", value=top_champs_str, inline=False)

        # Image : Champions strip
        strip_buf = await _build_top_champs_strip(session, top_champs)
        if strip_buf:
            files.append(discord.File(strip_buf, filename="champs.png"))
            embed.set_image(url="attachment://champs.png")

        dpm_url = DPM_PROFILE_URL.format(riot_id=riot_id.replace(" ", ""), tag=tag)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="DPM.LOL", url=dpm_url, style=discord.ButtonStyle.link))
        
        return embed, files, view

    finally:
        if own_session and session:
            await session.close()


async def build_match_embed(
    match_data: dict[str, Any],
    tracked_players: list[dict[str, Any]],
    platform: str = "euw1",
    session: aiohttp.ClientSession | None = None,
) -> tuple[list[discord.Embed], list[discord.File], discord.ui.View]:
    """
    Construit un Embed par joueur traqué, dans le même style que l'historique :
      • Thumbnail champion à droite
      • Stats compactes dans la description
      • Image composite fixe : spells + items

    Returns
    -------
    (list[discord.Embed], list[discord.File], discord.ui.View)
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        info = match_data["info"]
        game_duration = info.get("gameDuration", 0)
        queue_id = info.get("queueId", 0)
        queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")

        def fmt_d(d: int) -> str:
            return f"{d/1000.0:.1f}k".replace(".0k", "k") if d >= 1000 else str(d)

        def get_bar(dmg: int, max_dmg: int, color: str, length: int = 5) -> str:
            if max_dmg <= 0: return "⬛" * length
            r = dmg / max_dmg
            filled = round(r * length)
            return color * filled + "⬛" * (length - filled)
            
        max_damage = max((p.get("totalDamageDealtToChampions", 0) for p in info.get("participants", [])), default=0)

        team_data: dict[int, dict[str, Any]] = {}
        for p in info.get("participants", []):
            tid = p.get("teamId", 0)
            if tid not in team_data:
                team_data[tid] = {
                    "win": p.get("win", False),
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "damage": 0,
                    "players": []
                }
            
            team_data[tid]["kills"] += p.get("kills", 0)
            team_data[tid]["deaths"] += p.get("deaths", 0)
            team_data[tid]["assists"] += p.get("assists", 0)
            dmg = p.get("totalDamageDealtToChampions", 0)
            team_data[tid]["damage"] += dmg
            
            champ = p.get("championName", "Inconnu")
            k, d, a = p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)
            p_name = p.get("riotIdGameName") or p.get("summonerName", "Inconnu")
            p_puuid = p.get("puuid")
            
            if len(p_name) > 15:
                p_name = p_name[:15] + "…"
            
            team_data[tid]["players"].append((champ, p_name, k, d, a, dmg, p_puuid))

        embeds: list[discord.Embed] = []
        files: list[discord.File] = []

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
            won = participant["win"]
            is_remake = participant.get("gameEndedInEarlySurrender", False) or game_duration < 240
            
            if is_remake:
                color = 0x95A5A6  # Gris
                result_text = "Remake"
                result_emoji = "🏳️"
            else:
                color = COLOR_WIN if won else COLOR_LOSS
                result_text = "Victoire" if won else "Défaite"
                result_emoji = "🏆" if won else "💀"

            version = await _get_latest_version(session)
            champion_icon = DDRAGON_CHAMPION_ICON.format(
                version=version, champion=champion
            )
            
            streak = tp.get("streak", 0)
            streak_text = ""
            if streak <= -3:
                streak_text = f"🥶 Loose streak: {-streak}\n"
            elif streak >= 3:
                streak_text = f"🔥 Win streak: {streak}\n"
            
            description = (
                f"### {result_emoji} {champion} — {result_text}\n"
                f"{streak_text}"
                f"**{kills} / {deaths} / {assists}**  ({kda_ratio:.2f} KDA)\n"
                f"CS {cs} ({cs_per_min:.1f}/min)  •  {damage:,} dégâts  •  👁 {vision}"
            )

            embed = discord.Embed(color=color, description=description)
            embed.set_thumbnail(url=champion_icon)
            embed.set_footer(text=f"{queue_name}  •  {_format_duration(game_duration)}")

            # Générer l'image composite spells + items (largeur fixe).
            strip_buf = await _build_game_strip(session, participant)
            if strip_buf:
                filename = f"match_{idx}.png"
                files.append(discord.File(strip_buf, filename=filename))
                embed.set_image(url=f"attachment://{filename}")

            embeds.append(embed)

        view = MatchDetailsView(match_data, tracked_players, platform)
        return embeds, files, view

    finally:
        if own_session and session:
            await session.close()


class MatchDetailsView(discord.ui.View):
    """Vue contenant un bouton pour afficher les détails du match en éphémère."""

    def __init__(
        self,
        match_data: dict[str, Any],
        tracked_players: list[dict[str, Any]],
        platform: str = "euw1",
    ) -> None:
        super().__init__(timeout=None)
        self.match_data = match_data
        self.tracked_players = tracked_players
        self.platform = platform

        # Ajouter le bouton DPM.LOL pour chaque joueur.
        for tp in tracked_players:
            dpm_url = DPM_PROFILE_URL.format(
                riot_id=tp["riot_id"].replace(" ", ""),
                tag=tp["tag"],
            )
            self.add_item(
                discord.ui.Button(
                    label="DPM.LOL",
                    url=dpm_url,
                    style=discord.ButtonStyle.link,
                )
            )

    @discord.ui.button(label="Détails", style=discord.ButtonStyle.secondary, emoji="📊")
    async def show_details(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Affiche les statistiques détaillées des équipes dans un message éphémère."""
        info = self.match_data["info"]
        participants = info.get("participants", [])
        max_damage = max((p.get("totalDamageDealtToChampions", 0) for p in participants), default=0)
        
        # On regroupe les joueurs par équipe.
        team_data: dict[int, dict[str, Any]] = {}
        for p in participants:
            tid = p.get("teamId", 0)
            if tid not in team_data:
                team_data[tid] = {"win": p.get("win", False), "players": []}
            
            p_name = p.get("riotIdGameName") or p.get("summonerName", "Inconnu")
            if len(p_name) > 15: p_name = p_name[:15] + "…"
            
            team_data[tid]["players"].append({
                "name": p_name,
                "champion": p.get("championName", "Inconnu"),
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0),
                "assists": p.get("assists", 0),
                "damage": p.get("totalDamageDealtToChampions", 0),
                "puuid": p.get("puuid")
            })

        tracked_puuids = {tp["puuid"] for tp in self.tracked_players}
        
        def fmt_d(d: int) -> str:
            return f"{d/1000.0:.1f}k".replace(".0k", "k") if d >= 1000 else str(d)

        def get_bar(dmg: int, max_dmg_val: int, b_color: str, length: int = 5) -> str:
            if max_dmg_val <= 0: return "⬛" * length
            r = dmg / max_dmg_val
            filled = round(r * length)
            return b_color * filled + "⬛" * (length - filled)

        embed = discord.Embed(title="📊 Détails des Équipes", color=0x34495E)
        all_lines = [f"◽ `CHAMP   ` `  KDA  ` `  DMG  `"]
        
        sorted_tids = sorted(team_data.keys())
        for idx, tid in enumerate(sorted_tids):
            data = team_data[tid]
            conf = TEAM_CONFIG.get(tid, TEAM_CONFIG[0])
            
            # Un petit séparateur si c'est la deuxième équipe
            if idx > 0:
                all_lines.append("")

            for p in data["players"]:
                is_tracked = p["puuid"] in tracked_puuids
                bar = get_bar(p["damage"], max_damage, conf["bar"], length=4)
                
                c_name = p['champion'][:8]
                kda_val = f"{p['kills']}/{p['deaths']}/{p['assists']}"
                dmg_val = fmt_d(p['damage'])
                
                c_txt = f"`{c_name:<8}`"
                k_txt = f"`{kda_val:^7}`"
                d_txt = f"`{dmg_val:>5}`"
                
                if is_tracked:
                    c_txt = f"**{c_txt}**"
                    k_txt = f"**{k_txt}**"
                    d_txt = f"**{d_txt}**"
                
                all_lines.append(f"{conf['icon']} {c_txt} {k_txt} {bar} {d_txt}")

        embed.description = "\n".join(all_lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)




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

        # Embed titre — nom du joueur en titre, bannière "HISTORIQUE" en image.
        title_embed = discord.Embed(
            title=f"📜  {riot_id}#{tag}",
            color=0x3498DB,
        )

        # Charger la bannière statique.
        banner_path = Path(__file__).parent / "assets" / "history_banner.png"
        if banner_path.exists():
            banner_file = discord.File(str(banner_path), filename="history_banner.png")
            files.append(banner_file)
            title_embed.set_image(url="attachment://history_banner.png")

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

            version = await _get_latest_version(session)
            champion_icon = DDRAGON_CHAMPION_ICON.format(
                version=version, champion=champion
            )

            won = participant["win"]
            is_remake = participant.get("gameEndedInEarlySurrender", False) or game_duration < 240
            
            if is_remake:
                color = 0x95A5A6  # Gris
                result_text = "Remake"
                result_emoji = "🏳️"
            else:
                color = COLOR_WIN if won else COLOR_LOSS
                result_text = "Victoire" if won else "Défaite"
                result_emoji = "🏆" if won else "💀"

            description = (
                f"### {result_emoji} {champion} — {result_text}\n"
                f"**{kills} / {deaths} / {assists}**  ({kda_ratio:.2f} KDA)\n"
                f"CS {cs} ({cs_per_min:.1f}/min)  •  👁 {vision}"
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

        # Bouton DPM.LOL.
        dpm_url = DPM_PROFILE_URL.format(
            riot_id=riot_id.replace(" ", ""),
            tag=tag,
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label=f"DPM.LOL — {riot_id}",
                url=dpm_url,
                style=discord.ButtonStyle.link,
            )
        )

        return embeds, files, view

    finally:
        if own_session and session:
            await session.close()
