# Sleeper — collecteur « Enchères du Domaine »

Outil en ligne de commande qui, à chaque exécution, énumère les ventes de
véhicules d'**encheres-domaine.gouv.fr** (Direction nationale d'interventions
domaniales), extrait la fiche complète de chaque lot — dont la mention
**« Réservé aux professionnels »**, la mise à prix et l'enchère en cours —
applique un filtre géographique et des règles d'exclusion métier, puis produit
un JSON validé et un digest Markdown.

L'outil **ne calcule aucune cotation et n'enchérit jamais.** Il collecte,
filtre, restitue. L'analyse de marché est faite en aval.

```
ventes ouvertes → lots de chaque vente → fiche détaillée (si besoin)
    → règles d'exclusion → périmètre → état persistant → JSON + digest
```

---

## Sommaire

- [Ce que fait l'outil](#ce-que-fait-loutil)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Lire la sortie](#lire-la-sortie)
- [Planifier une exécution quotidienne](#planifier-une-exécution-quotidienne)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Développement](#développement)
- [Limites assumées](#limites-assumées)
- [Dépendances et justifications](#dépendances-et-justifications)
- [Harnais ECC — version épinglée](#harnais-ecc--version-épinglée)

---

## Ce que fait l'outil

| | |
|---|---|
| **Balaye** | toutes les ventes en cours (`statut 3`) et à venir (`statut 2`) comportant la catégorie « Véhicules » |
| **Extrait** | pour chaque lot : mention professionnels, mise à prix, enchère en cours, marque, modèle, kilométrage, énergie, boîte, VIN, carte grise, clés, contrôle technique, lieu de retrait, dates de visite, description intégrale |
| **Filtre** | sur le **lieu de retrait** (jamais le siège de la vente) et sur dix règles d'exclusion métier |
| **Mémorise** | dans SQLite : nouveautés, historique des enchères, ventes clôturées, cache des fiches |
| **Produit** | un JSON horodaté validé contre son JSON Schema, plus un digest Markdown |

L'information la plus importante du projet est `reserve_aux_professionnels` :
les particuliers sont exclus de ces lots, la concurrence y est structurellement
plus faible. **Si ce champ n'est pas lisible pour un lot, celui-ci est signalé
incomplet — jamais livré avec une valeur par défaut**, et le run se termine avec
un code de sortie non nul.

---

## Installation

L'outil tourne sur Linux, macOS et Windows. Il exige **Python 3.12+** et
**[uv](https://docs.astral.sh/uv/)**.

### 1. Installer uv

<details open>
<summary><b>Linux / macOS</b></summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Ou, sur macOS avec Homebrew :

```bash
brew install uv
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Ou avec winget :

```powershell
winget install --id=astral-sh.uv -e
```
</details>

### 2. Récupérer le projet et ses dépendances

```bash
git clone https://github.com/William-Stoops/Sleeper.git
cd Sleeper
uv sync --extra discovery
```

`uv sync` crée l'environnement et installe les versions exactes de `uv.lock`.
L'extra `discovery` ajoute Playwright, **nécessaire** : le site sert un
challenge JavaScript avant toute donnée, et un vrai navigateur est requis pour
obtenir la session (voir [Limites assumées](#limites-assumées)).

### 3. Installer le navigateur

```bash
uv run playwright install chromium
```

<details>
<summary><b>Linux : dépendances système du navigateur</b></summary>

```bash
uv run playwright install --with-deps chromium
```

Sur une distribution non couverte, installer manuellement `libnss3`,
`libatk-bridge2.0-0`, `libcups2`, `libdrm2`, `libxkbcommon0`, `libxcomposite1`,
`libxdamage1`, `libxfixes3`, `libxrandr2`, `libgbm1`, `libasound2`.
</details>

### 4. Régler la configuration

```bash
cp config/default.toml config/local.toml
```

**Une seule valeur est à changer impérativement** : `reseau.user_agent`, qui
doit porter une adresse de contact réellement relevée. L'outil refuse de
démarrer avec un User-Agent anonyme.

### 5. Vérifier

```bash
uv run sleeper valider-config -c config/local.toml
```

Cette commande n'émet aucune requête réseau.

---

## Utilisation

```bash
# Le run quotidien
uv run sleeper collecter -c config/local.toml

# Contrôler la configuration, sans toucher au réseau
uv run sleeper valider-config -c config/local.toml

# Republier le JSON Schema de sortie après une évolution des modèles
uv run sleeper schema
```

### Codes de sortie

| Code | Signification | Ce qu'il faut faire |
|---|---|---|
| `0` | Run complet, rien à signaler | rien |
| `1` | Erreur métier : configuration invalide, sortie non conforme, ou **au moins un lot incomplet** | lire `run.erreurs` dans le JSON |
| `3` | **Le site a présenté un challenge anti-robot.** L'outil s'est arrêté volontairement | espacer les exécutions, vérifier la cadence, relancer plus tard |

Ces codes sont distincts pour qu'une tâche planifiée puisse alerter
différemment. Un code `3` n'est pas une panne : c'est l'outil qui refuse de
forcer.

---

## Lire la sortie

Chaque exécution dépose dans `sortie.repertoire` :

```
var/sorties/
├── sleeper-2026-08-25T04-30-00_02-00.json   ← le run horodaté
├── sleeper-2026-08-25T04-30-00_02-00.md     ← le digest horodaté
├── latest.json  →  le dernier JSON
└── latest.md    →  le dernier digest
```

`latest.*` est un lien symbolique, ou une copie là où les liens symboliques ne
sont pas disponibles (Windows sans privilège).

### Le digest

À lire en trente secondes, le matin. Quatre questions dans l'ordre : ce qui est
**nouveau**, sur quoi les **enchères ont bougé**, quels lots sont **réservés aux
professionnels**, et ce qui a **mal tourné**. Un bandeau en tête signale les
lots incomplets, qui ont leur propre tableau.

### Le JSON

Structure complète dans [`schemas/sortie-1.0.json`](schemas/sortie-1.0.json).
Le document est **validé contre ce fichier avant écriture** : si les modèles et
le schéma publié divergent, le run échoue plutôt que de livrer.

```jsonc
{
  "schema_version": "1.0",
  "run":     { "horodatage": …, "lots_vus": …, "lots_retenus": …, "erreurs": [] },
  "ventes":  [ { "id": …, "dans_perimetre": true, "nb_lots": … } ],
  "lots":    [ { "reserve_aux_professionnels": true, "mise_a_prix": 1500.0, … } ],
  "ecartes": [ { "id": …, "titre": …, "motif": "sans_cle" } ]
}
```

Trois conventions à connaître :

- **`null` signifie « information absente de la source »**, jamais « on n'a pas
  su lire ». Un échec d'extraction alimente `champs_manquants` sur le lot et
  `run.erreurs` sur l'exécution.
- **`description_integrale` conserve le texte source brut**, sans reformulation.
  C'est la matière première de l'analyse aval.
- **`hors_perimetre: true` ne veut pas dire « écarté »**. Le lot est conservé :
  c'est à vous de décider si une affaire exceptionnelle justifie la route.

### Champs toujours nuls

`nb_encherisseurs` et `frais_acheteur_pct` n'existent pas dans l'API publique du
site. Ils valent `null` par absence de source, pas par échec de lecture. Voir
[`docs/api.md` §4](docs/api.md).

---

## Planifier une exécution quotidienne

**Une seule exécution par jour.** Le site est un service public protégé par un
pare-feu applicatif ; une cadence plus élevée déclenche un CAPTCHA et l'outil
s'arrête (code `3`).

<details open>
<summary><b>Linux / macOS — cron</b></summary>

```bash
crontab -e
```

```cron
# Sleeper : collecte quotidienne à 04h30
30 4 * * * cd /chemin/vers/Sleeper && /usr/bin/env uv run sleeper collecter -c config/local.toml >> var/sleeper.log 2>&1
```

Le chemin absolu vers le projet est indispensable : cron ne démarre pas dans
votre répertoire de travail.
</details>

<details>
<summary><b>Linux — systemd timer (recommandé sur serveur)</b></summary>

`~/.config/systemd/user/sleeper.service` :

```ini
[Unit]
Description=Collecte des enchères du Domaine
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/Sleeper
ExecStart=%h/.local/bin/uv run sleeper collecter -c config/local.toml
# Le code 3 (challenge anti-robot) n'est pas un échec du service.
SuccessExitStatus=3
```

`~/.config/systemd/user/sleeper.timer` :

```ini
[Unit]
Description=Collecte quotidienne des enchères du Domaine

[Timer]
OnCalendar=*-*-* 04:30:00
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now sleeper.timer
systemctl --user list-timers sleeper.timer
journalctl --user -u sleeper.service -n 50
```

`RandomizedDelaySec` évite de taper le site à la seconde près chaque jour.
`loginctl enable-linger $USER` permet l'exécution sans session ouverte.
</details>

<details>
<summary><b>macOS — launchd (survit au redémarrage)</b></summary>

`~/Library/LaunchAgents/fr.sleeper.collecte.plist` :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>fr.sleeper.collecte</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string><string>sleeper</string><string>collecter</string>
    <string>-c</string><string>config/local.toml</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/VOTRE_NOM/Sleeper</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/VOTRE_NOM/Sleeper/var/sleeper.log</string>
  <key>StandardErrorPath</key><string>/Users/VOTRE_NOM/Sleeper/var/sleeper.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/fr.sleeper.collecte.plist
launchctl list | grep sleeper
```
</details>

<details>
<summary><b>Windows — Planificateur de tâches</b></summary>

En PowerShell **administrateur**, depuis le dossier du projet :

```powershell
$action  = New-ScheduledTaskAction -Execute "uv" `
             -Argument "run sleeper collecter -c config/local.toml" `
             -WorkingDirectory "C:\Chemin\Vers\Sleeper"
$trigger = New-ScheduledTaskTrigger -Daily -At 4:30am
$reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -RandomDelay (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "Sleeper - encheres du Domaine" `
  -Action $action -Trigger $trigger -Settings $reglages `
  -Description "Collecte quotidienne des ventes de vehicules du Domaine"
```

Vérifier, puis lancer une fois à la main :

```powershell
Get-ScheduledTask -TaskName "Sleeper - encheres du Domaine"
Start-ScheduledTask -TaskName "Sleeper - encheres du Domaine"
Get-ScheduledTaskInfo -TaskName "Sleeper - encheres du Domaine"
```

`LastTaskResult` vaut `0` en cas de succès, `3` si le site a présenté un
challenge anti-robot.
</details>

---

## Configuration

Tout le métier est dans [`config/default.toml`](config/default.toml), commenté
section par section. **Aucune valeur n'est en dur dans le code.** La
configuration est validée au démarrage : une erreur arrête l'outil avec un
message explicite plutôt que de produire un scan silencieusement vide.

| Section | Ce qu'on y règle |
|---|---|
| `[reseau]` | URL, User-Agent, cadence, reprises, durée de session, `navigateur_headless` |
| `[perimetre]` | départements retenus, pays étrangers |
| `[exclusions]` | règles actives, **formulations supplémentaires** |
| `[filtres]` | catégorie, statuts de vente, taille de page |
| `[sortie]` | répertoire, noms des liens courants, digest |
| `[etat]` | chemin de la base SQLite |
| `[journalisation]` | niveau, format `json` ou `console` |

### Enrichir les règles sans toucher au code

Quand vous croisez une formulation non couverte :

```toml
[exclusions.formulations_supplementaires]
moteur_hors_service = ["bloc moteur fendu", "turbo à remplacer"]
choc_ou_accident = ["pare-chocs arraché"]
```

Une clé inconnue fait **échouer le démarrage** : une faute de frappe ne doit pas
se traduire par une règle silencieusement inopérante.

La liste complète des formulations reconnues est dans
[`docs/regles-metier.md`](docs/regles-metier.md), **généré depuis le code** —
il ne peut donc pas mentir sur ce que l'outil fait.

### Garde-fous de politesse

Le code impose des plafonds que la configuration ne peut pas franchir :
`concurrence_max ≤ 3`, `delai_entre_requetes_s ≥ 0.5`, et un User-Agent
identifiable obligatoire.

---

## Architecture

Quatre couches indépendantes. On peut tester les règles métier sans navigateur,
et changer de format de sortie sans toucher au scraping.

```
src/sleeper/
├── domain/        ← LE MÉTIER, sans aucune dépendance technique
│   ├── models.py      contrat de sortie (Pydantic v2), source du JSON Schema
│   ├── texte.py       normalisation FR + extractions (VIN, km, CT, Crit'Air…)
│   ├── exclusions.py  les dix règles, leurs déclencheurs et contre-expressions
│   ├── perimetre.py   code postal → département, y compris Corse et outre-mer
│   └── codes.py       grammaire de la source (statuts, booléens, genres)
├── api/           ← LE TRANSPORT
│   ├── operations.py  requêtes GraphQL figées, identiques à celles du site
│   ├── session.py     acquisition et cache de la session navigateur
│   ├── client.py      httpx, cadenceur, reprises, refus du challenge
│   └── mapping.py     JSON → objets typés, échec bruyant si le schéma casse
├── state/         ← LA MÉMOIRE
│   ├── migrations.py  schéma SQLite versionné
│   └── store.py       nouveautés, historique d'enchères, cache de fiches
├── output/        ← LA RESTITUTION
│   ├── sink.py        destination (fichier local ; extensible)
│   ├── document.py    sérialisation + validation JSON Schema
│   └── digest.py      Markdown
├── pipeline.py    ← L'ORCHESTRATION
├── config.py      ← la configuration, validée
└── cli.py         ← trois commandes
```

Le pipeline ne connaît pas `ClientDomaine` : il dépend d'un `Protocol` à une
méthode. C'est ce qui permet de rejouer un run complet sur des fixtures.

### Ajouter une destination de sortie

`output/sink.py` définit un `Protocol` à deux méthodes. Une destination
distante (dépôt Git, stockage objet) s'ajoute en l'implémentant, sans toucher au
reste de la chaîne. Seule la destination fichier est implémentée aujourd'hui.

### L'état persistant a une valeur propre

SQLite ne sert pas qu'à détecter les nouveautés. La table `enchere` n'enregistre
une ligne **que lorsqu'un montant change**, ce qui construit une série
historique propre. Dans six mois, elle répondra à la question qui compte : à
quel pourcentage de la mise à prix les lots du Domaine partent-ils réellement ?
La table `adjudication` conserve les prix constatés à la clôture.

---

## Développement

```bash
uv sync --all-extras
uv run pre-commit install
```

| Commande | Rôle |
|---|---|
| `uv run pytest` | tous les tests, **aucun ne touche le réseau** |
| `uv run pytest --cov` | couverture (plancher : 90 %) |
| `uv run mypy` | typage strict, **zéro `# type: ignore`** |
| `uv run ruff check src tests tools` | lint |
| `uv run ruff format src tests tools` | format |
| `uv run python tools/verifier_fixtures.py` | aucune donnée personnelle dans les fixtures |
| `uv run python tools/generer_doc_regles.py > docs/regles-metier.md` | régénérer la doc des règles |

La CI GitHub Actions rejoue l'ensemble sur Linux, macOS et Windows, en Python
3.12 et 3.13, et vérifie en plus que le JSON Schema publié et la documentation
des règles suivent bien le code.

### Les tests ne touchent jamais le réseau

Les fixtures sont de **vraies réponses de l'API**, capturées le 2026-08-25 puis
**expurgées des données personnelles** — l'API renvoie l'IBAN du compte de
l'État ainsi que le nom, le courriel et le téléphone d'agents publics.
`tools/verifier_fixtures.py` refuse tout versionnement qui en réintroduirait,
et il tourne en pre-commit comme en CI.

### Rejouer la reconnaissance de l'API

Quand un run échoue en `SchemaAmontError`, c'est que le contrat amont a bougé :

```bash
uv run --extra discovery python tools/discover_api.py --out var/discovery
```

Procédure détaillée dans [`docs/api.md` §8](docs/api.md).

---

## Limites assumées

**Le site est protégé par un pare-feu applicatif UBIKA doublé d'un CAPTCHA
ALTCHA.** Cela impose trois choses, toutes délibérées :

1. **Un navigateur réel, et visible, obtient la session.** Le site sert un
   challenge JavaScript avant toute donnée ; un navigateur l'exécute comme le
   ferait n'importe quel visiteur. Cette acquisition est isolée dans
   `api/session.py`, mise en cache et renouvelée automatiquement. Le run
   lui-même se fait ensuite en HTTP direct, sans navigateur.

   **Le navigateur n'est pas en mode headless, et c'est délibéré.** En headless,
   Chromium annonce `HeadlessChrome/151…` dans son User-Agent, ce que le
   pare-feu du site refuse. Deux issues étaient possibles : masquer ce jeton, ou
   ouvrir un vrai navigateur. Masquer aurait été un déguisement ; l'outil ouvre
   donc une fenêtre, quelques secondes, une fois par exécution.

   <details>
   <summary>Sur un serveur sans affichage — xvfb</summary>

   ```bash
   sudo apt install xvfb                       # Debian / Ubuntu
   xvfb-run -a uv run sleeper collecter -c config/local.toml
   ```

   `xvfb-run` fournit un affichage virtuel : le navigateur se croit sur un
   écran, son User-Agent reste celui d'un Chrome ordinaire, et rien n'est
   masqué. Dans une unité systemd, préfixer `ExecStart` par
   `/usr/bin/xvfb-run -a`.
   </details>
2. **Les requêtes sont rejouées à l'identique.** Le pare-feu valide la forme des
   paramètres et rejette toute requête forgée, même sémantiquement équivalente
   (`400 — Bad query params length`). `operations.py` reproduit au caractère
   près les requêtes du site ; un test bloque toute divergence.
3. **Aucun CAPTCHA n'est résolu, jamais.** Une page ALTCHA fait lever
   `ProtectionAntiRobotError`, **sans aucune reprise**, et le run s'arrête avec
   le code `3`. Réessayer reviendrait à chercher à contourner.

   Le client distingue soigneusement deux pages qui se ressemblent :

   | Ce que le site sert | Ce que fait Sleeper |
   |---|---|
   | Le challenge JavaScript d'entrée (`/redirect_…`, « requires JS enabled ») | la session a expiré : il la **renouvelle une fois** et repart, comme le ferait un visiteur ordinaire |
   | Une page ALTCHA (« Check that you are not a robot ») | il **s'arrête**, sans reprise |

   Confondre les deux serait grave dans les deux sens : abandonner sur une
   simple expiration rendrait l'outil inutilisable, insister sur un CAPTCHA
   reviendrait à le contourner.

L'outil **ne crée pas de compte, n'enchérit pas, n'écrit rien sur le site**, et
ne stocke aucun identifiant.

`robots.txt` n'est pas servi par le site : l'URL renvoie la coquille de
l'application. Il n'existe donc aucune directive d'exclusion à respecter, ni
aucune autorisation explicite. Les CGU et CGV sont publiées en PDF sous
`/admin/media/documents/` et **restent à relire avant tout passage en production
soutenu**.

---

## Dépendances et justifications

Aucune dépendance n'est ajoutée sans raison écrite.

### Exécution

| Paquet | Pourquoi celui-là |
|---|---|
| **httpx** | client HTTP avec `MockTransport` intégré, ce qui permet de tester toute la couche transport **sans dépendance de test supplémentaire** ni serveur factice |
| **pydantic** v2 | modèles typés, validation, et **génération du JSON Schema** depuis les mêmes classes : le contrat de sortie a une seule source de vérité |
| **typer** | CLI typée dérivée des annotations, cohérente avec `mypy --strict` |
| **rich** | tableau de bilan lisible en fin de run |
| **structlog** | journalisation structurée JSON, indispensable pour une tâche planifiée non surveillée |
| **jsonschema** | valide le document contre le schéma **publié sur disque**. Ce détour est volontaire : il fait échouer le run si le schéma versionné et les modèles divergent, là où une validation Pydantic ne validerait le document que contre lui-même |

### Découverte (extra `discovery`)

| Paquet | Pourquoi |
|---|---|
| **playwright** | seul moyen d'exécuter le challenge JavaScript du site pour obtenir une session, et outil de la phase de reconnaissance |

### Développement

`pytest`, `pytest-cov`, `mypy`, `ruff`, `pre-commit`, `types-jsonschema`.

### Écarté délibérément

| Envisagé | Pourquoi non |
|---|---|
| `pytest-recording` / `vcrpy` | `httpx.MockTransport` couvre le besoin sans dépendance supplémentaire, et les fixtures restent des fichiers JSON lisibles et expurgeables à la main |
| `respx` | idem : `MockTransport` est fourni par httpx |
| `sqlite-utils` | la bibliothèque standard suffit ; les migrations sont explicites et versionnées |
| `beautifulsoup4` / `lxml` | l'API renvoie du JSON structuré. Aucun sélecteur CSS n'est utilisé nulle part |
| `pandas` | aucun calcul tabulaire : l'outil collecte, il n'analyse pas |
| `pydantic-settings` | la configuration vient d'un TOML versionné, pas de l'environnement |

Bibliothèque standard pour le reste : `tomllib`, `sqlite3`, `hashlib`,
`unicodedata`, `concurrent.futures`.

---

## Harnais ECC — version épinglée

Le projet s'appuie sur le harnais [ECC](https://github.com/affaan-m/ecc)
(agents, skills, commands, hooks).

| Élément | Valeur |
|---|---|
| Marketplace | `affaan-m/ecc` |
| Plugin | `ecc@ecc` |
| Version déclarée | `2.2.0` |
| **Commit épinglé (SHA)** | `d8409a4b0813771235555e32e3d8046a73988bfa` |
| Date du commit | 2026-08-19T23:31:56Z |
| Portée d'installation | `user` |
| Hooks | profil **`minimal`** |

### Pourquoi une épingle manuelle

`claude plugin marketplace add` ne prend **aucun paramètre de révision** : il
clone la branche par défaut du dépôt amont. Il n'existe pas de mécanisme natif
de verrouillage. L'épingle est donc **déclarative et vérifiable** :

```bash
test "$(git -C ~/.claude/plugins/marketplaces/ecc rev-parse HEAD)" = "d8409a4b0813771235555e32e3d8046a73988bfa" && echo "ECC conforme au SHA epingle" || echo "DERIVE: ECC a change, relire les hooks avant de continuer"
```

En cas de dérive : relire `hooks/hooks.json` et `scripts/hooks/` du dépôt amont
**avant** de reprendre le travail, puis mettre à jour le SHA de ce tableau dans
le même commit. Restauration explicite :

```bash
git -C ~/.claude/plugins/marketplaces/ecc checkout d8409a4b0813771235555e32e3d8046a73988bfa
```

### Hooks

Le profil `minimal` est appliqué : cycle de vie et traçabilité seulement. Huit
hooks actifs, dont un seul bloquant — `pre:bash:block-no-verify`, qui interdit
`git commit --no-verify`, et va donc dans le sens de ce projet.

L'inventaire complet, l'analyse de sécurité (ce qui s'exécute automatiquement,
ce qui est écrit sur le disque, ce qui sort de la machine) et la liste exacte
des hooks actifs sont dans
[`docs/ecc-hooks-review.md`](docs/ecc-hooks-review.md).

Coupure d'urgence : `ECC_HOOKS_ENABLED=0 claude`.

---

## Licence

MIT.
