"""
main.py — Point d'entrée de BotDiff.

Charge les variables d'environnement et lance le bot Discord.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from bot import BotDiff
from database import Database
from riot_api import RiotAPI


def main() -> None:
    # ── Chargement de la configuration ──────────────────────
    load_dotenv()

    discord_token = os.getenv("DISCORD_TOKEN")
    riot_api_key = os.getenv("RIOT_API_KEY")
    riot_region = os.getenv("RIOT_REGION", "europe")
    riot_platform = os.getenv("RIOT_PLATFORM", "euw1")

    if not discord_token:
        sys.exit("❌  Variable d'environnement DISCORD_TOKEN manquante.")
    if not riot_api_key:
        sys.exit("❌  Variable d'environnement RIOT_API_KEY manquante.")

    # ── Logging ─────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Instanciation ──────────────────────────────────────
    riot = RiotAPI(api_key=riot_api_key, region=riot_region)
    db = Database()
    bot = BotDiff(riot_api=riot, db=db, platform=riot_platform)

    # ── Lancement ──────────────────────────────────────────
    logging.info("Démarrage de BotDiff…")
    bot.run(discord_token, log_handler=None)


if __name__ == "__main__":
    main()
