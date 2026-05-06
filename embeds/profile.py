from __future__ import annotations

import io
import logging
from typing import Any
import aiohttp
import discord

from .utils import (
    RANK_COLORS, _get_latest_version, DDRAGON_PROFILE_ICON,
    CD_RANK_ICON, DPM_PROFILE_URL
)
from .images import _download_image, _build_top_champs_strip

logger = logging.getLogger("botdiff.embeds.profile")

async def build_profile_embed(
    riot_id: str, tag: str, summoner: dict[str, Any], league_entries: list[dict[str, Any]],
    last_matches: list[dict[str, Any]], puuid: str, platform: str = "euw1",
    session: aiohttp.ClientSession | None = None,
) -> tuple[discord.Embed, list[discord.File], discord.ui.View]:
    level = summoner["summonerLevel"]
    profile_icon_id = summoner["profileIconId"]
    own_session = session is None
    if own_session: session = aiohttp.ClientSession()

    try:
        ranked_solo = "Unranked"
        ranked_flex = "Unranked"
        best_tier = "UNRANKED"

        for entry in league_entries:
            tier, rank, lp, wins, losses = entry["tier"], entry["rank"], entry["leaguePoints"], entry["wins"], entry["losses"]
            wr = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
            info = f"**{tier.title()} {rank}** ({lp} LP)\n{wins}W / {losses}L — {wr:.1f}% WR"

            if entry["queueType"] == "RANKED_SOLO_5x5":
                ranked_solo = info
                best_tier = tier
            elif entry["queueType"] == "RANKED_FLEX_SR":
                ranked_flex = info
                if best_tier == "UNRANKED": best_tier = tier

        total_kills, total_deaths, total_assists = 0, 0, 0
        total_cs, total_min, total_damage = 0, 0, 0
        champions_count = {}

        count = 0
        for match in last_matches:
            parts = match["info"]["participants"]
            p = next((x for x in parts if x["puuid"] == puuid), None)
            if not p: continue
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

        embed = discord.Embed(color=RANK_COLORS.get(best_tier, 0x34495E), description=f"### 🎖️ Level {level}")
        version = await _get_latest_version(session)
        embed.set_author(name=f"{riot_id}#{tag}", icon_url=DDRAGON_PROFILE_ICON.format(version=version, icon_id=profile_icon_id))

        files = []
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

        embed.add_field(name="🏆 Ranked Solo/Duo", value=ranked_solo, inline=True)
        embed.add_field(name="⚔️ Ranked Flex", value=ranked_flex, inline=True)
        embed.add_field(name=f"📊 Moyennes ({count} parties)", value=stats_val, inline=False)
        if top_champs:
            embed.add_field(name="👑 Champions favoris", value=top_champs_str, inline=False)

        strip_buf = await _build_top_champs_strip(session, top_champs)
        if strip_buf:
            files.append(discord.File(strip_buf, filename="champs.png"))
            embed.set_image(url="attachment://champs.png")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="DPM.LOL", url=DPM_PROFILE_URL.format(riot_id=riot_id.replace(" ", ""), tag=tag), style=discord.ButtonStyle.link))
        return embed, files, view
    finally:
        if own_session and session:
            await session.close()

class ProfileButton(discord.ui.Button):
    def __init__(self, tp: dict[str, Any], platform: str):
        super().__init__(label="Profil", style=discord.ButtonStyle.secondary, emoji="👤")
        self.tp = tp
        self.platform = platform

    async def callback(self, interaction: discord.Interaction):
        from bot import BotDiff
        import asyncio
        bot: BotDiff = interaction.client
        await interaction.response.defer(thinking=True)
        riot_id, tag, puuid = self.tp["riot_id"], self.tp["tag"], self.tp["puuid"]
        try:
            summoner, match_ids = await asyncio.gather(
                bot.riot.get_summoner_by_puuid(bot.platform, puuid),
                bot.riot.get_match_ids(puuid, count=10)
            )
            league_entries, matches_results = await asyncio.gather(
                bot.riot.get_league_entries_by_puuid(bot.platform, puuid),
                asyncio.gather(*[bot.riot.get_match_detail(mid) for mid in match_ids], return_exceptions=True)
            )
            valid_matches = [m for m in matches_results if not isinstance(m, Exception)]
            embed, files, view = await build_profile_embed(riot_id, tag, summoner, league_entries, valid_matches, puuid, platform=bot.platform)
            await interaction.followup.send(content=f"🕵️‍♂️ **{interaction.user.mention}** est en train de stalker en cachette...", embed=embed, files=files, view=view)
        except Exception as exc:
            logger.exception("Erreur lors du bouton /profile")
            await interaction.followup.send(f"❌ Impossible de charger le profil : `{exc}`")
