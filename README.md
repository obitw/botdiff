# 🎮 BotDiff — Discord League of Legends Match Tracker

Bot Discord qui surveille les comptes League of Legends d'une liste de joueurs et envoie automatiquement un **embed riche** avec leurs statistiques dès qu'ils terminent une partie.

---

## 🚀 Installation

### 1. Pré-requis

- **Python 3.10+**
- Un **bot Discord** créé sur le [Portail Développeur Discord](https://discord.com/developers/applications)
  - Permissions requises : `Send Messages`, `Embed Links`, `Use Application Commands`
  - Scoops OAuth2 : `bot`, `applications.commands`
- Une **clé API Riot Games** depuis le [Portail Développeur Riot](https://developer.riotgames.com/)

### 2. Cloner le projet

```bash
git clone <url_du_repo>
cd botdiff
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

```bash
cp .env.example .env
```

Ouvre `.env` et renseigne tes tokens :

| Variable        | Description                              | Exemple                      |
| --------------- | ---------------------------------------- | ---------------------------- |
| `DISCORD_TOKEN` | Token de ton bot Discord                 | `MTIzNDU2Nzg5...`            |
| `RIOT_API_KEY`  | Clé API Riot Games                       | `RGAPI-xxxxxxxx-...`         |
| `RIOT_REGION`   | Région pour l'API Riot (Account / Match) | `europe`, `americas`, `asia` |
| `RIOT_PLATFORM` | Plateforme pour les liens OP.GG          | `euw1`, `na1`, `kr`          |

### 5. Lancer le bot

#### Avec Python directement

```bash
python main.py
```

#### Avec Docker (Recommandé)

```bash
docker-compose up -d
```

---

## 🤖 Commandes Slash

| Commande                   | Description                                                          |
| -------------------------- | -------------------------------------------------------------------- |
| `/add <riot_id> <tag>`     | Ajoute un joueur à la surveillance (résout le PUUID automatiquement) |
| `/remove <riot_id> <tag>`  | Retire un joueur de la surveillance                                  |
| `/list`                    | Affiche la liste des joueurs surveillés sur le serveur               |
| `/setup_channel`           | Définit le salon actuel comme destination des alertes                |
| `/history <riot_id> <tag>` | Affiche les 5 dernières parties d'un joueur                          |
| `/test_alert <riot_id> <tag>` | Simule une notification pour la dernière partie d'un joueur       |

---

## ⚙️ Fonctionnement

1. La commande `/setup_channel` définit où le bot envoie les alertes.
2. `/add` ajoute des joueurs à surveiller.
3. Toutes les **2 minutes**, le bot vérifie l'historique récent de chaque joueur via l'API Match-V5.
4. Si un nouveau match est détecté, un **embed riche** est envoyé avec :
   - 🟢 / 🔴 Couleur victoire / défaite
   - Champion joué (avec icône)
   - KDA, CS, CS/min, Dégâts, Vision
   - Boutons liens vers OP.GG et League of Graphs
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
├── requirements.txt  # Dépendances Python
├── .env.example      # Template des variables d'environnement
└── README.md         # Ce fichier
```

---

## ⚠️ Notes

- La **clé API de développement Riot** expire toutes les 24h. Pour un usage permanent, demandez une clé de production.
- Le bot gère automatiquement les erreurs **429 (Rate Limit)** en respectant le header `Retry-After`.
- La base de données SQLite (`botdiff.db`) est créée automatiquement au premier lancement.
