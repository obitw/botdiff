from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import aiohttp
import discord

from .utils import (
    QUEUE_NAMES, COLOR_WIN, COLOR_LOSS, _find_participant, _format_duration,
    _get_latest_version, DDRAGON_CHAMPION_ICON, DPM_PROFILE_URL
)
from .images import _build_game_strip

logger = logging.getLogger("botdiff.embeds.history")

async def build_history_embed(
    riot_id: str, tag: str, puuid: str, matches: list[dict[str, Any]],
    platform: str = "euw1", session: aiohttp.ClientSession | None = None,
) -> tuple[list[discord.Embed], list[discord.File], discord.ui.View]:
    own_session = session is None
    if own_session: session = aiohttp.ClientSession()

    try:
        embeds, files = [], []
        title_embed = discord.Embed(title=f"📜  {riot_id}#{tag}", color=0x3498DB)
        banner_path = Path(__file__).parent.parent / "assets" / "history_banner.png"
        if banner_path.exists():
            files.append(discord.File(str(banner_path), filename="history_banner.png"))
            title_embed.set_image(url="attachment://history_banner.png")
        embeds.append(title_embed)

        for game_idx, match_data in enumerate(matches):
            participant = _find_participant(match_data, puuid)
            if participant is None: continue
            info = match_data["info"]
            champion = participant["championName"]
            kills, deaths, assists = participant["kills"], participant["deaths"], participant["assists"]
            kda_ratio = (kills + assists) / max(deaths, 1)
            cs = participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0)
            game_duration = info.get("gameDuration", 0)
            cs_per_min = cs / max(game_duration / 60, 1)
            vision = participant["visionScore"]
            won = participant["win"]
            queue_name = QUEUE_NAMES.get(info.get("queueId", 0), f"Queue {info.get('queueId', 0)}")
            
            is_remake = participant.get("gameEndedInEarlySurrender", False) or game_duration < 240
            color = 0x95A5A6 if is_remake else (COLOR_WIN if won else COLOR_LOSS)
            result_text = "Remake" if is_remake else ("Victoire" if won else "Défaite")
            result_emoji = "🏳️" if is_remake else ("🏆" if won else "💀")

            version = await _get_latest_version(session)
            embed = discord.Embed(color=color, description=(
                f"### {result_emoji} {champion} — {result_text}\n"
                f"**{kills} / {deaths} / {assists}**  ({kda_ratio:.2f} KDA)\n"
                f"CS {cs} ({cs_per_min:.1f}/min)  •  👁 {vision}"
            ))
            embed.set_thumbnail(url=DDRAGON_CHAMPION_ICON.format(version=version, champion=champion))
            embed.set_footer(text=f"{queue_name}  •  {_format_duration(game_duration)}")

            strip_buf = await _build_game_strip(session, participant)
            if strip_buf:
                filename = f"game_{game_idx}.png"
                files.append(discord.File(strip_buf, filename=filename))
                embed.set_image(url=f"attachment://{filename}")
            embeds.append(embed)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=f"DPM.LOL — {riot_id}", url=DPM_PROFILE_URL.format(riot_id=riot_id.replace(" ", ""), tag=tag), style=discord.ButtonStyle.link))
        return embeds, files, view
    finally:
        if own_session and session:
            await session.close()

class HistoryButton(discord.ui.Button):
    def __init__(self, tp: dict[str, Any], platform: str):
        super().__init__(label="Historique", style=discord.ButtonStyle.secondary, emoji="📜")
        self.tp = tp
        self.platform = platform

    async def callback(self, interaction: discord.Interaction):
        from bot import BotDiff
        import asyncio
        bot: BotDiff = interaction.client
        await interaction.response.defer(thinking=True)
        riot_id, tag, puuid = self.tp["riot_id"], self.tp["tag"], self.tp["puuid"]
        try:
            match_ids = await bot.riot.get_match_ids(puuid, count=5)
            if not match_ids:
                return await interaction.followup.send(f"📭 Aucune partie récente trouvée pour **{riot_id}#{tag}**.")
            results = await asyncio.gather(*[bot.riot.get_match_detail(mid) for mid in match_ids], return_exceptions=True)
            matches = [res for mid, res in zip(match_ids, results) if not isinstance(res, Exception)]
            if not matches:
                return await interaction.followup.send(f"❌ Impossible de récupérer les détails des parties pour **{riot_id}#{tag}**.")
            embeds, files, view = await build_history_embed(riot_id, tag, puuid, matches, platform=bot.platform)
            await interaction.followup.send(content=f"📜 **{interaction.user.mention}** ressort les vieux dossiers...", embeds=embeds, files=files, view=view)
        except Exception as exc:
            logger.exception("Erreur lors du bouton historique")
            await interaction.followup.send(f"❌ Impossible de charger l'historique : `{exc}`")
