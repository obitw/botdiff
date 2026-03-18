"""
database.py — Couche de persistance SQLite pour BotDiff.

Tables :
  • tracked_players  – joueurs surveillés (riot_id, tag, puuid, guild, last_match_id)
  • config           – paramètres par serveur (channel d'alerte)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "botdiff.db"



@dataclass
class TrackedPlayer:
    """Représente un joueur surveillé."""

    riot_id: str
    tag: str
    puuid: str
    guild_id: int
    last_match_id: str | None


class Database:
    """Interface synchrone vers la base SQLite (suffisant pour du léger)."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    # ── Initialisation ──────────────────────────────────────
    def _create_tables(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_players (
                    riot_id       TEXT    NOT NULL,
                    tag           TEXT    NOT NULL,
                    puuid         TEXT    NOT NULL,
                    guild_id      INTEGER NOT NULL,
                    last_match_id TEXT,
                    PRIMARY KEY (puuid, guild_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    guild_id   INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
                """
            )

    # ── Joueurs ─────────────────────────────────────────────

    def add_player(
        self,
        riot_id: str,
        tag: str,
        puuid: str,
        guild_id: int,
    ) -> bool:
        """Ajoute un joueur. Renvoie True si ajouté, False s'il existait déjà."""
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO tracked_players (riot_id, tag, puuid, guild_id) VALUES (?, ?, ?, ?)",
                    (riot_id, tag, puuid, guild_id),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_player(self, riot_id: str, tag: str, guild_id: int) -> bool:
        """Retire un joueur. Renvoie True si supprimé, False s'il n'existait pas."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM tracked_players WHERE LOWER(riot_id)=LOWER(?) AND LOWER(tag)=LOWER(?) AND guild_id=?",
                (riot_id, tag, guild_id),
            )
        return cursor.rowcount > 0

    def list_players(self, guild_id: int) -> list[TrackedPlayer]:
        """Liste tous les joueurs traqués pour un serveur donné."""
        rows = self.conn.execute(
            "SELECT riot_id, tag, puuid, guild_id, last_match_id FROM tracked_players WHERE guild_id=?",
            (guild_id,),
        ).fetchall()
        return [TrackedPlayer(**dict(r)) for r in rows]

    def get_all_players(self) -> list[TrackedPlayer]:
        """Liste tous les joueurs traqués, toutes guildes confondues."""
        rows = self.conn.execute(
            "SELECT riot_id, tag, puuid, guild_id, last_match_id FROM tracked_players"
        ).fetchall()
        return [TrackedPlayer(**dict(r)) for r in rows]

    # ── Last match ──────────────────────────────────────────

    def get_last_match_id(self, puuid: str, guild_id: int) -> str | None:
        """Récupère le dernier match traité pour un joueur."""
        row = self.conn.execute(
            "SELECT last_match_id FROM tracked_players WHERE puuid=? AND guild_id=?",
            (puuid, guild_id),
        ).fetchone()
        return row["last_match_id"] if row else None

    def update_last_match_id(
        self, puuid: str, guild_id: int, match_id: str
    ) -> None:
        """Met à jour le dernier match traité pour un joueur."""
        with self.conn:
            self.conn.execute(
                "UPDATE tracked_players SET last_match_id=? WHERE puuid=? AND guild_id=?",
                (match_id, puuid, guild_id),
            )

    # ── Configuration (salon d'alerte) ──────────────────────

    def set_channel(self, guild_id: int, channel_id: int) -> None:
        """Définit le salon d'alerte pour un serveur."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO config (guild_id, channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id
                """,
                (guild_id, channel_id),
            )

    def get_channel(self, guild_id: int) -> int | None:
        """Récupère le salon d'alerte configuré pour un serveur."""
        row = self.conn.execute(
            "SELECT channel_id FROM config WHERE guild_id=?",
            (guild_id,),
        ).fetchone()
        return row["channel_id"] if row else None

    def close(self) -> None:
        self.conn.close()
