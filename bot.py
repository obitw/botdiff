"""
bot.py — Bot Discord BotDiff.

Contient :
  • Les 4 commandes slash (/track, /untrack, /list, /setup_channel)
  • La boucle de tracking (tasks.loop toutes les 2 min)
  • La déduplication premade (un seul embed par match partagé)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import Database, TrackedPlayer
from embeds import build_history_embed, build_match_embed, build_profile_embed
from riot_api import RiotAPI, RiotAPIError

logger = logging.getLogger("botdiff.bot")

TIER_ORDER = {
    "IRON": 0,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "PLATINUM": 4,
    "EMERALD": 5,
    "DIAMOND": 6,
    "MASTER": 7,
    "GRANDMASTER": 8,
    "CHALLENGER": 9,
}
RANK_ORDER = {"IV": 0, "III": 1, "II": 2, "I": 3}


def get_rank_value(tier: str, rank: str) -> int:
    return TIER_ORDER.get(tier, 0) * 10 + RANK_ORDER.get(rank, 0)


class BotDiff(commands.Bot):
    """Bot Discord qui surveille les parties League of Legends."""

    def __init__(
        self,
        riot_api: RiotAPI,
        db: Database,
        platform: str = "euw1",
        **kwargs: Any,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents, **kwargs)

        self.riot = riot_api
        self.db = db
        self.platform = platform

    # ── Lifecycle ───────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Appelé automatiquement au démarrage. Synchronise les commandes."""
        self.tree.add_command(add)
        self.tree.add_command(remove)
        self.tree.add_command(list_players)
        self.tree.add_command(setup_channel)
        self.tree.add_command(history)
        self.tree.add_command(profile)
        self.tree.add_command(test_alert)

        await self.tree.sync()
        logger.info("Commandes slash synchronisées.")

        # Démarre la boucle de tracking.
        self.check_matches_loop.start()

    async def on_ready(self) -> None:
        logger.info("Connecté en tant que %s (ID: %s)", self.user, self.user.id)

    async def close(self) -> None:
        self.check_matches_loop.cancel()
        await self.riot.close()
        self.db.close()
        await super().close()

    # ── Boucle de Tracking ──────────────────────────────────

    @tasks.loop(minutes=2)
    async def check_matches_loop(self) -> None:
        """Vérifie toutes les 2 min si de nouvelles parties sont terminées."""
        logger.debug("Début du cycle de vérification des matchs.")

        all_players = self.db.get_all_players()
        if not all_players:
            return

        # Regroupe les joueurs par guild pour traiter chaque serveur.
        guilds: dict[int, list[TrackedPlayer]] = defaultdict(list)
        for p in all_players:
            guilds[p.guild_id].append(p)

        for guild_id, players in guilds.items():
            channel_id = self.db.get_channel(guild_id)
            if channel_id is None:
                continue

            channel = self.get_channel(channel_id)
            if channel is None:
                continue

            # Collecte les nouveaux matchs par joueur.
            # new_matches_map : match_id -> [{riot_id, tag, puuid}, ...]
            new_matches_map: dict[str, list[dict[str, str]]] = defaultdict(list)

            for player in players:
                try:
                    match_ids = await self.riot.get_match_ids(player.puuid, count=5)
                except RiotAPIError as exc:
                    logger.error(
                        "Erreur API pour %s#%s : %s", player.riot_id, player.tag, exc
                    )
                    continue

                if not match_ids:
                    continue

                last_known = player.last_match_id

                # Initialisation : on enregistre le dernier match sans alerter.
                if last_known is None:
                    self.db.update_last_match_id(player.puuid, guild_id, match_ids[0])
                    # Initialiser le rang
                    try:
                        league_entries = await self.riot.get_league_entries_by_puuid(
                            self.platform, player.puuid
                        )
                        solo_q = next(
                            (
                                q
                                for q in league_entries
                                if q.get("queueType") == "RANKED_SOLO_5x5"
                            ),
                            None,
                        )
                        if solo_q:
                            self.db.update_rank(
                                player.puuid,
                                guild_id,
                                solo_q.get("tier", ""),
                                solo_q.get("rank", ""),
                            )
                    except RiotAPIError:
                        pass
                    continue

                new_matches_found = False
                # Identifie les matchs plus récents que le dernier connu.
                for mid in match_ids:
                    if mid == last_known:
                        break
                    new_matches_found = True
                    new_matches_map[mid].append(
                        {
                            "riot_id": player.riot_id,
                            "tag": player.tag,
                            "puuid": player.puuid,
                        }
                    )

                if new_matches_found:
                    # Met à jour le dernier match traité.
                    self.db.update_last_match_id(player.puuid, guild_id, match_ids[0])

                    # Vérifie les changements de rang
                    try:
                        league_entries = await self.riot.get_league_entries_by_puuid(
                            self.platform, player.puuid
                        )
                        solo_q = next(
                            (
                                q
                                for q in league_entries
                                if q.get("queueType") == "RANKED_SOLO_5x5"
                            ),
                            None,
                        )
                        if solo_q:
                            current_tier = solo_q.get("tier", "")
                            current_rank = solo_q.get("rank", "")

                            # Si on avait un rang stocké
                            if player.solo_tier and player.solo_rank:
                                old_val = get_rank_value(
                                    player.solo_tier, player.solo_rank
                                )
                                new_val = get_rank_value(current_tier, current_rank)

                                if new_val > old_val:
                                    # Rank UP
                                    await channel.send(
                                        f"📈 **{player.riot_id}#{player.tag}** a RANK UP ! ({player.solo_tier.title()} {player.solo_rank} ➔ **{current_tier.title()} {current_rank}**)"
                                    )
                                elif new_val < old_val:
                                    # Rank DOWN (Troll message)
                                    await channel.send(
                                        f"📉 **{player.riot_id}#{player.tag}** a RANK DOWN ! Décidément, LoL c'est pas fait pour tout le monde 🥶... Bienvenu en **{current_tier.title()} {current_rank}** !"
                                    )

                            # Met à jour la DB si le rang a changé ou si c'est la première fois
                            if (
                                not player.solo_tier
                                or player.solo_tier != current_tier
                                or player.solo_rank != current_rank
                            ):
                                self.db.update_rank(
                                    player.puuid, guild_id, current_tier, current_rank
                                )
                                player.solo_tier = current_tier
                                player.solo_rank = current_rank
                    except RiotAPIError as exc:
                        logger.error(
                            "Erreur récupération rank pour %s : %s", player.riot_id, exc
                        )
                    continue

                # Identifie les matchs plus récents que le dernier connu.
                for mid in match_ids:
                    if mid == last_known:
                        break
                    new_matches_map[mid].append(
                        {
                            "riot_id": player.riot_id,
                            "tag": player.tag,
                            "puuid": player.puuid,
                        }
                    )

                # Met à jour le dernier match traité.
                self.db.update_last_match_id(player.puuid, guild_id, match_ids[0])

            # Envoie un embed par match unique (déduplication premade).
            # Tri chrologique par match_id si le format est Region_Timestamp/ID
            ordered_matches = sorted(
                new_matches_map.items(),
                key=lambda x: int(x[0].split("_")[1]) if "_" in x[0] else 0,
            )
            for match_id, tracked_in_match in ordered_matches:
                try:
                    match_data = await self.riot.get_match_detail(match_id)
                except RiotAPIError as exc:
                    logger.error(
                        "Impossible de récupérer le match %s : %s", match_id, exc
                    )
                    continue

                # Mise à jour du streak pour chaque joueur surveillé dans ce match
                for p_dict in tracked_in_match:
                    player_obj = next(
                        (p for p in players if p.puuid == p_dict["puuid"]), None
                    )
                    if player_obj:
                        participant = next(
                            (
                                x
                                for x in match_data["info"]["participants"]
                                if x["puuid"] == player_obj.puuid
                            ),
                            None,
                        )
                        if participant:
                            is_remake = (
                                participant.get("gameEndedInEarlySurrender", False)
                                or match_data["info"].get("gameDuration", 0) < 240
                            )
                            if not is_remake:
                                won = participant["win"]
                                if won:
                                    player_obj.streak = (
                                        1
                                        if player_obj.streak < 0
                                        else player_obj.streak + 1
                                    )
                                else:
                                    player_obj.streak = (
                                        -1
                                        if player_obj.streak > 0
                                        else player_obj.streak - 1
                                    )
                                self.db.update_streak(
                                    player_obj.puuid, guild_id, player_obj.streak
                                )
                        p_dict["streak"] = player_obj.streak

                embeds, files, view = await build_match_embed(
                    match_data, tracked_in_match, platform=self.platform
                )

                # Message de notification.
                names = ", ".join(
                    f"**{p['riot_id']}#{p['tag']}**" for p in tracked_in_match
                )
                content = f"🎮 {names} vient de terminer une partie !"

                try:
                    await channel.send(
                        content=content, embeds=embeds, files=files, view=view
                    )  # type: ignore[union-attr]
                    logger.info(
                        "Alerte envoyée pour le match %s dans le guild %s.",
                        match_id,
                        guild_id,
                    )
                except discord.HTTPException as exc:
                    logger.error("Impossible d'envoyer le message : %s", exc)

    @check_matches_loop.before_loop
    async def before_check(self) -> None:
        """Attend que le bot soit prêt avant de lancer la boucle."""
        await self.wait_until_ready()


# ════════════════════════════════════════════════════════════
# Commandes Slash
# ════════════════════════════════════════════════════════════


@app_commands.command(
    name="add", description="Ajouter un joueur LoL à la surveillance."
)
@app_commands.describe(riot_id="Nom Riot du joueur (ex: Faker)", tag="Tagline (ex: T1)")
async def add(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
    """Ajoute un joueur à la base de données en résolvant son PUUID."""
    assert interaction.guild is not None
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    await interaction.response.defer(thinking=True)

    try:
        puuid = await bot.riot.get_puuid(riot_id, tag)
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Impossible de résoudre **{riot_id}#{tag}** : `{exc}`"
        )
        return

    added = bot.db.add_player(riot_id, tag, puuid, interaction.guild.id)
    if added:
        await interaction.followup.send(
            f"✅ **{riot_id}#{tag}** est maintenant surveillé !\n`PUUID : {puuid[:16]}…`"
        )
    else:
        await interaction.followup.send(
            f"⚠️ **{riot_id}#{tag}** est déjà dans la liste de surveillance."
        )


@app_commands.command(
    name="remove", description="Retirer un joueur de la surveillance."
)
@app_commands.describe(riot_id="Nom Riot du joueur", tag="Tagline")
async def remove(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
    """Retire un joueur de la surveillance."""
    assert interaction.guild is not None
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    removed = bot.db.remove_player(riot_id, tag, interaction.guild.id)
    if removed:
        await interaction.response.send_message(
            f"🗑️ **{riot_id}#{tag}** a été retiré de la surveillance."
        )
    else:
        await interaction.response.send_message(
            f"⚠️ **{riot_id}#{tag}** n'est pas dans la liste."
        )


@app_commands.command(
    name="list", description="Afficher la liste des joueurs surveillés."
)
async def list_players(interaction: discord.Interaction) -> None:
    """Affiche tous les joueurs traqués pour ce serveur."""
    assert interaction.guild is not None
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    players = bot.db.list_players(interaction.guild.id)
    if not players:
        await interaction.response.send_message(
            "📋 Aucun joueur surveillé pour le moment.\nUtilise `/track` pour en ajouter."
        )
        return

    lines = [f"• **{p.riot_id}#{p.tag}**" for p in players]
    embed = discord.Embed(
        title="📋  Joueurs surveillés",
        description="\n".join(lines),
        color=0x3498DB,
    )
    embed.set_footer(text=f"{len(players)} joueur(s)")
    await interaction.response.send_message(embed=embed)


@app_commands.command(
    name="setup_channel",
    description="Définir ce salon comme canal d'alertes de fin de partie.",
)
async def setup_channel(interaction: discord.Interaction) -> None:
    """Définit le salon actuel comme canal d'alerte."""
    assert interaction.guild is not None
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    bot.db.set_channel(interaction.guild.id, interaction.channel_id)
    await interaction.response.send_message(
        f"📢 Les alertes de fin de partie seront envoyées dans <#{interaction.channel_id}>."
    )


@app_commands.command(
    name="history",
    description="Afficher les 5 dernières parties d'un joueur.",
)
@app_commands.describe(riot_id="Nom Riot du joueur (ex: Faker)", tag="Tagline (ex: T1)")
async def history(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
    """Récupère et affiche les 5 dernières parties d'un joueur."""
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    await interaction.response.defer(thinking=True)

    # Résoudre le PUUID.
    try:
        puuid = await bot.riot.get_puuid(riot_id, tag)
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Impossible de résoudre **{riot_id}#{tag}** : `{exc}`"
        )
        return

    # Récupérer les 5 derniers match IDs.
    try:
        match_ids = await bot.riot.get_match_ids(puuid, count=5)
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Erreur lors de la récupération des matchs : `{exc}`"
        )
        return

    if not match_ids:
        await interaction.followup.send(
            f"📭 Aucune partie récente trouvée pour **{riot_id}#{tag}**."
        )
        return

    # Récupérer le détail de chaque match en parallèle.
    results = await asyncio.gather(
        *[bot.riot.get_match_detail(mid) for mid in match_ids],
        return_exceptions=True,
    )
    matches: list[dict] = []
    for mid, res in zip(match_ids, results):
        if isinstance(res, Exception):
            logger.warning("Impossible de récupérer le match %s : %s", mid, res)
        else:
            matches.append(res)

    if not matches:
        await interaction.followup.send(
            f"❌ Impossible de récupérer les détails des parties pour **{riot_id}#{tag}**."
        )
        return

    embeds, files, view = await build_history_embed(
        riot_id, tag, puuid, matches, platform=bot.platform
    )
    await interaction.followup.send(embeds=embeds, files=files, view=view)


@app_commands.command(
    name="profile",
    description="Afficher le profil complet et les statistiques d'un joueur.",
)
@app_commands.describe(riot_id="Nom Riot du joueur (ex: Faker)", tag="Tagline (ex: T1)")
async def profile(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
    """Récupère les infos de rang et les stats moyennes d'un joueur."""
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    await interaction.response.defer(thinking=True)

    try:
        # 1. Résoudre le PUUID
        puuid = await bot.riot.get_puuid(riot_id, tag)

        # 2. Récupérer les infos Summoner (pour level et icon) et les Match IDs en parallèle
        summoner_task = bot.riot.get_summoner_by_puuid(bot.platform, puuid)
        match_ids_task = bot.riot.get_match_ids(puuid, count=10)

        summoner, match_ids = await asyncio.gather(summoner_task, match_ids_task)

        # 3. Récupérer le classement et les détails des matchs en parallèle
        league_task = bot.riot.get_league_entries_by_puuid(bot.platform, puuid)
        matches_task = asyncio.gather(
            *[bot.riot.get_match_detail(mid) for mid in match_ids],
            return_exceptions=True,
        )

        league_entries, matches_results = await asyncio.gather(
            league_task, matches_task
        )

        # Filtrer les matchs valides
        valid_matches = [m for m in matches_results if not isinstance(m, Exception)]

        # 4. Construire l'embed
        embed, files, view = await build_profile_embed(
            riot_id,
            tag,
            summoner,
            league_entries,
            valid_matches,
            puuid,
            platform=bot.platform,
        )

        await interaction.followup.send(embed=embed, files=files, view=view)

    except RiotAPIError as exc:
        await interaction.followup.send(f"❌ Erreur API Riot : `{exc}`")
    except Exception as exc:
        logger.exception("Erreur lors de la commande /profile")
        await interaction.followup.send(f"❌ Une erreur interne est survenue : `{exc}`")


@app_commands.command(
    name="test_alert",
    description="Simuler une alerte de fin de partie (pour tester le rendu).",
)
@app_commands.describe(riot_id="Nom Riot du joueur (ex: Faker)", tag="Tagline (ex: T1)")
async def test_alert(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
    """Récupère la dernière partie d'un joueur et envoie l'alerte comme si elle venait d'être détectée."""
    bot: BotDiff = interaction.client  # type: ignore[assignment]

    await interaction.response.defer(thinking=True)

    # Résoudre le PUUID.
    try:
        puuid = await bot.riot.get_puuid(riot_id, tag)
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Impossible de résoudre **{riot_id}#{tag}** : `{exc}`"
        )
        return

    # Récupérer le dernier match ID.
    try:
        match_ids = await bot.riot.get_match_ids(puuid, count=1)
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Erreur lors de la récupération des matchs : `{exc}`"
        )
        return

    if not match_ids:
        await interaction.followup.send(
            f"📭 Aucune partie récente pour **{riot_id}#{tag}**."
        )
        return

    # Récupérer le détail du match.
    try:
        match_data = await bot.riot.get_match_detail(match_ids[0])
    except RiotAPIError as exc:
        await interaction.followup.send(
            f"❌ Impossible de récupérer le match : `{exc}`"
        )
        return

    tracked_info = [{"riot_id": riot_id, "tag": tag, "puuid": puuid}]
    embeds, files, view = await build_match_embed(
        match_data, tracked_info, platform=bot.platform
    )
    content = f"🎮 **{riot_id}#{tag}** vient de terminer une partie !"
    await interaction.followup.send(
        content=content,
        embeds=embeds,
        files=files,
        view=view,
    )
