# 🎮 BotDiff — Discord League of Legends Match Tracker

Bot Discord qui surveille les comptes League of Legends d'une liste de joueurs et envoie automatiquement un **embed riche** avec leurs statistiques dès qu'ils terminent une partie.

---

## 🚀 Installation (Recommandée avec Docker)

### 1. Pré-requis

- **Docker** et **Docker Compose** installés sur votre machine.
- Un **bot Discord** créé sur le [Portail Développeur Discord](https://discord.com/developers/applications)
  - Permissions requises : `Send Messages`, `Embed Links`, `Use Application Commands`
  - Scopes OAuth2 : `bot`, `applications.commands`
- Une **clé API Riot Games** depuis le [Portail Développeur Riot](https://developer.riotgames.com/)

### 2. Configuration

1. Cloner le projet :

   ```bash
   git clone git@github.com:obitw/botdiff.git
   cd botdiff
   ```

2. Configurer les variables d'environnement :
   ```bash
   cp .env.example .env
   ```
   Remplissez les champs nécessaires dans le fichier `.env` (Token Discord, Clé Riot, etc.).

### 3. Lancement

Lancez le bot en un clic avec Docker Compose :

```bash
docker compose up -d
```

Le bot est maintenant opérationnel et prêt à tracker vos parties !

---

## 🛠️ Gestion via Docker

- **Voir les logs** : `docker compose logs -f`
- **Arrêter le bot** : `docker compose stop`
- **Redémarrer le bot** : `docker compose restart`
- **Mettre à jour** :
  ```bash
  git pull
  docker compose up -d --build
  ```

---

## 🤖 Commandes Slash

| Commande                      | Description                                                          |
| ----------------------------- | -------------------------------------------------------------------- |
| `/add <riot_id> <tag>`        | Ajoute un joueur à la surveillance (résout le PUUID automatiquement) |
| `/remove <riot_id> <tag>`     | Retire un joueur de la surveillance                                  |
| `/list`                       | Affiche la liste des joueurs surveillés sur le serveur               |
| `/setup_channel`              | Définit le salon actuel comme destination des alertes                |
| `/profile <riot_id> <tag>`    | Affiche le profil complet (rangs, stats moyennes, favoris)           |
| `/history <riot_id> <tag>`    | Affiche les 5 dernières parties d'un joueur                          |
| `/test_alert <riot_id> <tag>` | Simule une notification pour la dernière partie d'un joueur          |

---

## ⚙️ Fonctionnement

1. La commande `/setup_channel` définit où le bot envoie les alertes.
2. `/add` ajoute des joueurs à surveiller.
3. Toutes les **2 minutes**, le bot vérifie l'historique récent de chaque joueur via l'API Match-V5.
4. Si un nouveau match est détecté, un **embed riche** est envoyé avec les statistiques détaillées.
5. **Déduplication premade** : si plusieurs joueurs traqués étaient dans la même partie, un **seul** embed est envoyé regroupant leurs stats.

---

## 📁 Structure du projet

```
botdiff/
├── bot.py            # Bot Discord, commandes slash, boucle de tracking
├── riot_api.py       # Client async API Riot (Account-V1, Match-V5)
├── database.py       # Persistance SQLite (joueurs, config)
├── embeds.py         # Construction des embeds Discord
├── main.py           # Point d'entrée
├── Dockerfile        # Image Docker du bot
├── docker-compose.yml # Orchestration Docker
├── requirements.txt  # Dépendances Python
├── .env.example      # Template des variables d'environnement
└── README.md         # Documentation
```

---

## ⚠️ Notes

- La **clé API de développement Riot** expire toutes les 24h. Pour un usage permanent, demandez une clé de production.
- Le bot gère automatiquement les erreurs **429 (Rate Limit)** en respectant le header `Retry-After`.
- La base de données SQLite (`botdiff.db`) est stockée dans un volume Docker par défaut (`botdiff_data`) pour assurer la persistance.
