"""
riot_api.py — Client asynchrone pour l'API Riot Games.

Fournit les méthodes pour :
  • Résoudre un Riot ID (nom + tag) en PUUID          (Account-V1)
  • Récupérer les derniers Match IDs d'un joueur      (Match-V5)
  • Récupérer le détail complet d'un match             (Match-V5)

Gère automatiquement les erreurs 429 (Rate Limit) en
attendant le délai indiqué par le header Retry-After.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger("botdiff.riot_api")

# ── URLs de base ────────────────────────────────────────────
ACCOUNT_V1_URL = "https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
MATCH_V5_IDS_URL = "https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
MATCH_V5_DETAIL_URL = "https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"


class RiotAPIError(Exception):
    """Exception levée quand l'API Riot renvoie une erreur inattendue."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"Riot API {status}: {message}")


class RiotAPI:
    """Client asynchrone vers l'API Riot Games."""

    # Nombre max de tentatives en cas de 429.
    MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        region: str = "europe",
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.api_key = api_key
        self.region = region
        self._session = session  # sera créée à la demande si non fournie

    # ── Gestion de la session ───────────────────────────────
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Ferme proprement la session HTTP."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Requête générique avec gestion du rate-limit ────────
    async def _request(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Effectue un GET et gère le rate-limit (429)."""
        session = await self._get_session()
        headers = {"X-Riot-Token": self.api_key}

        for attempt in range(1, self.MAX_RETRIES + 1):
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()

                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning(
                        "Rate-limité par Riot (429). Pause de %ds (tentative %d/%d)",
                        retry_after,
                        attempt,
                        self.MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # Erreur non-429 → on lève immédiatement.
                body = await resp.text()
                raise RiotAPIError(resp.status, body)

        # Toutes les tentatives épuisées.
        raise RiotAPIError(429, "Rate-limit toujours actif après plusieurs tentatives.")

    # ── Méthodes publiques ──────────────────────────────────

    async def get_puuid(self, game_name: str, tag_line: str) -> str:
        """Résout un Riot ID (nom#tag) en PUUID via Account-V1."""
        url = ACCOUNT_V1_URL.format(
            region=self.region,
            game_name=game_name,
            tag_line=tag_line,
        )
        data = await self._request(url)
        return data["puuid"]

    async def get_match_ids(
        self,
        puuid: str,
        count: int = 5,
        start: int = 0,
        queue: int | None = None,
    ) -> list[str]:
        """Récupère les `count` derniers Match IDs d'un joueur."""
        url = MATCH_V5_IDS_URL.format(region=self.region, puuid=puuid)
        params: dict[str, Any] = {"start": start, "count": count}
        if queue is not None:
            params["queue"] = queue
        return await self._request(url, params=params)

    async def get_match_detail(self, match_id: str) -> dict[str, Any]:
        """Récupère le détail complet d'un match via Match-V5."""
        url = MATCH_V5_DETAIL_URL.format(region=self.region, match_id=match_id)
        return await self._request(url)
