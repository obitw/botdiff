from __future__ import annotations

import logging
from typing import Any
import aiohttp
import discord

from .utils import (
    QUEUE_NAMES, COLOR_WIN, COLOR_LOSS, _find_participant, _format_duration,
    _get_latest_version, DDRAGON_CHAMPION_ICON, DPM_PROFILE_URL, TEAM_CONFIG
)
from .images import _build_game_strip
from .profile import ProfileButton

logger = logging.getLogger("botdiff.embeds.match")

async def build_match_embed(
    match_data: dict[str, Any], tracked_players: list[dict[str, Any]],
    platform: str = "euw1", session: aiohttp.ClientSession | None = None,
) -> tuple[list[discord.Embed], list[discord.File], discord.ui.View]:
    own_session = session is None
    if own_session: session = aiohttp.ClientSession()
    try:
        info = match_data["info"]
        game_duration = info.get("gameDuration", 0)
        queue_name = QUEUE_NAMES.get(info.get("queueId", 0), f"Queue {info.get('queueId', 0)}")
        embeds, files = [], []

        for idx, tp in enumerate(tracked_players):
            participant = _find_participant(match_data, tp["puuid"])
            if participant is None: continue

            champion = participant["championName"]
            kills, deaths, assists = participant["kills"], participant["deaths"], participant["assists"]
            kda_ratio = (kills + assists) / max(deaths, 1)
            cs = participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0)
            cs_per_min = cs / max(game_duration / 60, 1)
            damage = participant["totalDamageDealtToChampions"]
            vision = participant["visionScore"]
            won = participant["win"]
            
            is_remake = participant.get("gameEndedInEarlySurrender", False) or game_duration < 240
            color = 0x95A5A6 if is_remake else (COLOR_WIN if won else COLOR_LOSS)
            result_text = "Remake" if is_remake else ("Victoire" if won else "Défaite")
            result_emoji = "🏳️" if is_remake else ("🏆" if won else "💀")

            streak = tp.get("streak", 0)
            streak_text = f"🥶 Loose streak: {-streak}\n" if streak <= -3 else (f"🔥 Win streak: {streak}\n" if streak >= 3 else "")

            embed = discord.Embed(color=color, description=(
                f"### {result_emoji} {champion} — {result_text}\n"
                f"{streak_text}"
                f"**{kills} / {deaths} / {assists}**  ({kda_ratio:.2f} KDA)\n"
                f"CS {cs} ({cs_per_min:.1f}/min)  •  {damage:,} dégâts  •  👁 {vision}"
            ))
            version = await _get_latest_version(session)
            embed.set_thumbnail(url=DDRAGON_CHAMPION_ICON.format(version=version, champion=champion))
            embed.set_footer(text=f"{queue_name}  •  {_format_duration(game_duration)}")

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
    def __init__(self, match_data: dict[str, Any], tracked_players: list[dict[str, Any]], platform: str = "euw1"):
        super().__init__(timeout=None)
        self.match_data = match_data
        self.tracked_players = tracked_players
        self.platform = platform
        
        details_button = self.children[0]
        self.clear_items()
        
        for tp in tracked_players: self.add_item(ProfileButton(tp, platform))
        self.add_item(details_button)
        for tp in tracked_players:
            self.add_item(discord.ui.Button(label="DPM.LOL", url=DPM_PROFILE_URL.format(riot_id=tp["riot_id"].replace(" ", ""), tag=tp["tag"]), style=discord.ButtonStyle.link))

    @discord.ui.button(label="Détails", style=discord.ButtonStyle.secondary, emoji="📊")
    async def show_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        info = self.match_data["info"]
        participants = info.get("participants", [])
        max_damage = max((p.get("totalDamageDealtToChampions", 0) for p in participants), default=0)

        team_data = {}
        for p in participants:
            tid = p.get("teamId", 0)
            if tid not in team_data: team_data[tid] = {"win": p.get("win", False), "players": []}
            p_name = p.get("riotIdGameName") or p.get("summonerName", "Inconnu")
            team_data[tid]["players"].append({
                "name": p_name[:15] + "…" if len(p_name) > 15 else p_name,
                "champion": p.get("championName", "Inconnu"),
                "kills": p.get("kills", 0), "deaths": p.get("deaths", 0), "assists": p.get("assists", 0),
                "damage": p.get("totalDamageDealtToChampions", 0),
                "puuid": p.get("puuid"),
            })

        tracked_puuids = {tp["puuid"] for tp in self.tracked_players}
        embed = discord.Embed(title="📊 Détails des Équipes", color=0x34495E)
        all_lines = ["◽ `CHAMP   ` `  KDA  ` `  DMG  `"]

        for idx, tid in enumerate(sorted(team_data.keys())):
            if idx > 0: all_lines.append("")
            conf = TEAM_CONFIG.get(tid, TEAM_CONFIG[0])
            for p in team_data[tid]["players"]:
                r = p["damage"] / max_damage if max_damage > 0 else 0
                filled = round(r * 4)
                bar = conf["bar"] * filled + "⬛" * (4 - filled)
                c_txt = f"`{p['champion'][:8]:<8}`"
                k_txt = f"`{p['kills']}/{p['deaths']}/{p['assists']:^7}`"
                dmg = p["damage"]
                d_txt = f"`{f'{dmg / 1000.0:.1f}k'.replace('.0k', 'k') if dmg >= 1000 else str(dmg):>5}`"
                if p["puuid"] in tracked_puuids:
                    c_txt, k_txt, d_txt = f"**{c_txt}**", f"**{k_txt}**", f"**{d_txt}**"
                all_lines.append(f"{conf['icon']} {c_txt} {k_txt} {bar} {d_txt}")

        embed.description = "\n".join(all_lines)
        await interaction.response.send_message(content=f"🤓 **{interaction.user.mention}** sort la calculatrice pour juger qui a fait le moins de dégâts...", embed=embed)
