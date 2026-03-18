"""
bot.py — Bot Discord BotDiff.

Contient :
  • Les 4 commandes slash (/track, /untrack, /list, /setup_channel)
  • La boucle de tracking (tasks.loop toutes les 2 min)
  • La déduplication premade (un seul embed par match partagé)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import Database, TrackedPlayer
from embeds import build_history_embed, build_match_embed
from riot_api import RiotAPI, RiotAPIError

logger = logging.getLogger("botdiff.bot")


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
        self.tree.add_command(track)
        self.tree.add_command(untrack)
        self.tree.add_command(list_players)
        self.tree.add_command(setup_channel)
        self.tree.add_command(history)
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
                    self.db.update_last_match_id(
                        player.puuid, guild_id, match_ids[0]
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
            for match_id, tracked_in_match in new_matches_map.items():
                try:
                    match_data = await self.riot.get_match_detail(match_id)
                except RiotAPIError as exc:
                    logger.error("Impossible de récupérer le match %s : %s", match_id, exc)
                    continue

                embeds, files, view = await build_match_embed(
                    match_data, tracked_in_match, platform=self.platform
                )

                # Message de notification.
                names = ", ".join(
                    f"**{p['riot_id']}#{p['tag']}**" for p in tracked_in_match
                )
                content = f"🎮 {names} vient de terminer une partie !"

                try:
                    await channel.send(content=content, embeds=embeds, files=files, view=view)  # type: ignore[union-attr]
                    logger.info("Alerte envoyée pour le match %s dans le guild %s.", match_id, guild_id)
                except discord.HTTPException as exc:
                    logger.error("Impossible d'envoyer le message : %s", exc)


    @check_matches_loop.before_loop
    async def before_check(self) -> None:
        """Attend que le bot soit prêt avant de lancer la boucle."""
        await self.wait_until_ready()


# ════════════════════════════════════════════════════════════
# Commandes Slash
# ════════════════════════════════════════════════════════════


@app_commands.command(name="track", description="Ajouter un joueur LoL à la surveillance.")
@app_commands.describe(riot_id="Nom Riot du joueur (ex: Faker)", tag="Tagline (ex: T1)")
async def track(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
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


@app_commands.command(name="untrack", description="Retirer un joueur de la surveillance.")
@app_commands.describe(riot_id="Nom Riot du joueur", tag="Tagline")
async def untrack(interaction: discord.Interaction, riot_id: str, tag: str) -> None:
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


@app_commands.command(name="list", description="Afficher la liste des joueurs surveillés.")
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

    # Récupérer le détail de chaque match.
    matches: list[dict] = []
    for mid in match_ids:
        try:
            match_data = await bot.riot.get_match_detail(mid)
            matches.append(match_data)
        except RiotAPIError as exc:
            logger.warning("Impossible de récupérer le match %s : %s", mid, exc)

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

    # Construire l'embed d'alerte (identique à la boucle de tracking).
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
