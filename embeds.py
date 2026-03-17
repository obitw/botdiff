"""
embeds.py — Construction des Embeds Discord pour les résultats de match.

Produit un Embed riche :
  • Couleur verte / rouge selon victoire / défaite
  • Champs par joueur traqué : champion, KDA, CS, dégâts, vision
  • Lien OP.GG par joueur
  • Infos du match en footer (mode, durée)
"""

from __future__ import annotations

from typing import Any

import discord

# ── Data Dragon (dernière version stable) ───────────────────
DDRAGON_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
# On fixe une version par défaut ; le bot peut la mettre à jour.
DDRAGON_VERSION = "14.6.1"
DDRAGON_CHAMPION_ICON = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion}.png"
)

OPGG_PROFILE_URL = "https://www.op.gg/summoners/{platform}/{riot_id}-{tag}"

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


def build_match_embed(
    match_data: dict[str, Any],
    tracked_players: list[dict[str, Any]],
    platform: str = "euw1",
) -> tuple[discord.Embed, discord.ui.View]:
    """
    Construit un Embed + View (boutons OP.GG) pour un match terminé.

    Parameters
    ----------
    match_data : dict
        Réponse complète de Match-V5 (/matches/{id}).
    tracked_players : list[dict]
        Liste de dicts ``{"riot_id": ..., "tag": ..., "puuid": ...}``
        pour tous les joueurs *traqués* présents dans ce match.
    platform : str
        Plateforme pour le lien OP.GG (euw1, na1, kr, …).

    Returns
    -------
    (discord.Embed, discord.ui.View)
    """

    info = match_data["info"]
    game_duration = info.get("gameDuration", 0)
    queue_id = info.get("queueId", 0)
    queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")

    # ── Déterminer la couleur globale (victoire du premier joueur traqué) ──
    first_participant = _find_participant(match_data, tracked_players[0]["puuid"])
    won = first_participant["win"] if first_participant else False
    color = COLOR_WIN if won else COLOR_LOSS
    result_text = "✅ Victoire" if won else "❌ Défaite"

    embed = discord.Embed(
        title=f"{'🏆' if won else '💀'}  Partie terminée — {result_text}",
        color=color,
    )

    # ── Champs pour chaque joueur traqué ────────────────────
    for tp in tracked_players:
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

        icon_url = DDRAGON_CHAMPION_ICON.format(
            version=DDRAGON_VERSION, champion=champion
        )

        player_result = "✅" if player_won else "❌"
        field_name = f"{player_result}  {tp['riot_id']}#{tp['tag']}  —  {champion}"

        field_value = (
            f"**KDA** : {kills}/{deaths}/{assists}  ({kda_ratio:.2f})\n"
            f"**CS** : {cs}  ({cs_per_min:.1f}/min)\n"
            f"**Dégâts** : {damage:,}\n"
            f"**Vision** : {vision}"
        )

        embed.add_field(name=field_name, value=field_value, inline=False)
        embed.set_thumbnail(url=icon_url)

    # ── Footer ──────────────────────────────────────────────
    embed.set_footer(text=f"{queue_name}  •  Durée : {_format_duration(game_duration)}")

    # ── Boutons OP.GG ───────────────────────────────────────
    view = discord.ui.View()
    for tp in tracked_players:
        opgg_url = OPGG_PROFILE_URL.format(
            platform=platform,
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

    return embed, view
