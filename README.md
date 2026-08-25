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
| **Balaye** | toutes les ventes en cours (statut 3) et à venir (statut 2) comportant la catégorie « Véhicules » |
| **Extrait** | pour chaque lot : mention professionnels, mise à prix, enchère en cours, marque, modèle, kilométrage, énergie, boîte, VIN, carte grise, clés, contrôle technique, lieu de retrait, dates de visite, description intégrale |
| **Filtre** | sur le **lieu de retrait** (jamais le siège de la vente) et sur onze règles d'exclusion métier |
| **Mémorise** | dans SQLite : nouveautés, historique des enchères, **prix d'adjudication**, ventes clôturées, cache des fiches |
| **Classe** | un tri déterministe qui décide qui reçoit l'analyse coûteuse en aval |
| **Produit** | un JSON horodaté validé contre son JSON Schema, plus un digest Markdown |

> **Le classement est un tri, pas une cotation.** Il est grossier, rapide,
> entièrement déterministe, explicable ligne à ligne, et volontairement
> conservateur : il vaut mieux faire remonter un lot médiocre que d'en
> enterrer un bon. **Il ne décide d'aucun achat. Il décide seulement de qui
> reçoit l'analyse coûteuse.**

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
uv sync
```

`uv sync` crée l'environnement et installe les versions exactes de `uv.lock`.
Playwright fait partie des dépendances **du run lui-même**, pas d'un extra : le
site refuse tout client qui n'est pas un navigateur, et Sleeper émet donc ses
requêtes depuis la pile réseau d'un vrai navigateur. Voir
[Limites assumées](#limites-assumées).

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
démarrer avec une identification anonyme.

Cette chaîne n'écrase pas le User-Agent du navigateur — ce serait un
déguisement. Elle voyage à côté, dans l'en-tête `From` défini par la RFC 9110
pour l'adresse de la personne responsable d'un agent automatisé, et dans
`X-Robot-Identification`. Un administrateur du site peut ainsi vous joindre.

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

### Suivre un run en cours

Un run long n'est pas muet. Il émet, au fil de l'eau :

| Événement | Quand |
|---|---|
| `run.starting`, `session.ready` | au démarrage |
| `sale.starting` | à l'ouverture de chaque vente, avec son nombre de lots annoncé |
| `lots.listing` | toutes les 20 pages de la liste des lots |
| `listings.fetching` | quand commence le téléchargement des fiches, avec le nombre déjà en cache |
| `listings.progress` | **toutes les 20 fiches** — c'est le battement de cœur |
| `sale.finished` | à la fin de chaque vente : retenus, écartés, motifs cumulés |
| `run.finished`, `output.written` | au bilan |

Pour un affichage lisible plutôt que du JSON, passer `format = "console"` dans
`[journalisation]`.

### Le digest

À lire en trente secondes, le matin. Quatre questions dans l'ordre : ce qui est
**nouveau**, sur quoi les **enchères ont bougé**, quels lots sont **réservés aux
professionnels**, et ce qui a **mal tourné**. Un bandeau en tête signale les
lots incomplets, qui ont leur propre tableau.

### Le JSON

Structure complète dans [`schemas/sortie-2.0.json`](schemas/sortie-2.0.json),
migration depuis la 1.0 dans [`docs/schema.md`](docs/schema.md).
Le document est **validé contre ce fichier avant écriture** : si les modèles et
le schéma publié divergent, le run échoue plutôt que de livrer.

> **Un consommateur doit échouer bruyamment sur une `schema_version` inconnue,
> jamais lire en dégradé.** Un 1.0 dit `hors_perimetre: false` là où un 2.0 dit
> `perimetre: "inconnu"` : le lire comme un 2.0 transformerait « on n'a pas su »
> en « c'est dans le périmètre ». `sleeper.output.document.read_document`
> applique la règle.

```jsonc
{
  "schema_version": "2.0",
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
s'arrête (code `3`). Les requêtes partent **en séquence**, espacées de
`delai_entre_requetes_s` : il n'y a pas de réglage de concurrence, une limite
de débit globale étant une garantie plus stricte.

> ⚠️ **L'outil ouvre une fenêtre de navigateur** (voir
> [Limites assumées](#limites-assumées)). Une tâche planifiée doit donc
> disposer d'un affichage : session ouverte sur macOS et Windows, `xvfb-run`
> sur un serveur Linux. Les trois recettes ci-dessous en tiennent compte.

> ⏱️ **Durée.** Le premier run télécharge une fiche par lot, à la cadence
> configurée : comptez une trentaine de minutes pour un catalogue complet. Les
> suivants ne retéléchargent que les lots nouveaux ou modifiés, grâce au cache,
> et durent quelques minutes.

<details open>
<summary><b>Linux / macOS — cron</b></summary>

```bash
crontab -e
```

```cron
# Sleeper : collecte quotidienne à 04h30
30 4 * * * cd /chemin/vers/Sleeper && /usr/bin/env xvfb-run -a uv run sleeper collecter -c config/local.toml >> var/sleeper.log 2>&1
```

Le chemin absolu vers le projet est indispensable : cron ne démarre pas dans
votre répertoire de travail. `xvfb-run` fournit l'affichage virtuel dont le
navigateur a besoin ; sur macOS, le retirer et laisser une session ouverte.
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
ExecStart=/usr/bin/xvfb-run -a %h/.local/bin/uv run sleeper collecter -c config/local.toml
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
`loginctl enable-linger $USER` permet l'exécution sans session ouverte —
`xvfb-run` fournissant alors l'affichage.
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
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/fr.sleeper.collecte.plist
launchctl enable gui/$(id -u)/fr.sleeper.collecte
launchctl list | grep sleeper
```

`launchctl load` fonctionne encore mais est obsolète : `bootstrap` rattache
explicitement l'agent à votre session graphique, celle dont le navigateur a
besoin.

#### Si la machine dort la nuit

Deux pièges se referment l'un sur l'autre, et aucun ne se signale :

1. **Un Mac endormi n'exécute rien.** `StartCalendarInterval` ne rattrape
   l'exécution manquée qu'au réveil — la fenêtre du navigateur surgirait donc
   à l'ouverture du capot, en pleine journée.
2. **Un Mac réveillé par minuterie se rendort** après quelques minutes
   d'inactivité. La collecte, qui dure une trentaine de minutes au premier
   run, serait coupée en plein vol chaque nuit.

D'où la paire, et elle est indissociable :

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 04:25:00
```

```xml
<key>ProgramArguments</key>
<array>
  <string>/usr/bin/caffeinate</string><string>-i</string>
  <string>/opt/homebrew/bin/uv</string>
  <string>run</string><string>sleeper</string><string>collecter</string>
  <string>-c</string><string>config/local.toml</string>
</array>
```

`pmset` réveille la machine cinq minutes avant l'heure ; `caffeinate -i`
interdit la veille d'inactivité tant que le processus vit, et lève le verrou
en mourant — y compris si la collecte échoue.

> ⚠️ **Sur un portable, laissez l'alimentation branchée.** macOS ignore les
> réveils programmés sur batterie. Le capot peut rester fermé : la session
> graphique reste active, et c'est tout ce dont le navigateur a besoin.
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
             -RandomDelay (New-TimeSpan -Minutes 15) `
             -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# -LogonType Interactive est necessaire : le navigateur exige un bureau.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName "Sleeper - encheres du Domaine" `
  -Action $action -Trigger $trigger -Settings $reglages -Principal $principal `
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
| `[reseau]` | URL, identification du robot, cadence, reprises, durée de session, `navigateur_headless` |
| `[perimetre]` | départements retenus, pays étrangers |
| `[exclusions]` | règles actives, **formulations supplémentaires** |
| `[filtres]` | catégorie, statuts de vente, taille de page |
| `[sortie]` | répertoire, noms des liens courants, digest |
| `[etat]` | chemin de la base SQLite |
| `[journalisation]` | niveau, format `json` ou `console` |

### Le classement, et sa dette

Deux tables pilotent le tri, toutes deux dans `config/` :

| Fichier | Ce qu'il porte |
|---|---|
| [`config/cotes.csv`](config/cotes.csv) | valeur de revente indicative par famille de véhicule |
| [`config/reparations.csv`](config/reparations.csv) | forfaits de remise en état déclenchés par expression |

> ⚠️ **La calibration de `cotes.csv` est la principale dette du projet.**
> Chaque ligne porte `source = amorce_a_calibrer` : ces valeurs viennent d'une
> estimation du marché français, pas de comparables vérifiés un par un. Le tri
> ne vaut jamais mieux qu'elles. Elles sont faites pour être remplacées au fil
> du temps par des valeurs vérifiées.

Sur le run du 25/08, la table couvrait 189 des 338 lots retenus : **les 149
autres ne participent pas au classement** et ne remontent que par la clause du
prix bas. Élargir la table est le levier le plus rentable du projet.

Les forfaits de `reparations.csv`, eux, sont tirés des descriptions réelles de
ce run — ils ont été relevés sur le terrain, pas inventés.

Tous les coefficients vivent dans `[score]` de `config/default.toml`, aucun
n'est en dur.

#### Le score compte des euros

```
coût_acquisition   = mise_à_prix × (1 + frais_%/100)
marge_au_prix_de_départ = cote − coût_acquisition − remise_en_état
score              = marge_au_prix_de_départ × produit(coefficients)
```

**Des euros, pas un ratio.** La version précédente divisait la marge par la
cote, et cela classait la voiture bon marché en tête : réaliser 80 % d'une cote
de 3 000 € est facile, 80 % d'une cote de 30 000 € ne l'est pas. Sur le run du
25 août, un Kangoo à 2 919 € de marge se plaçait devant des utilitaires bien
plus rentables. Ce que l'opérateur dépense est un après-midi, et ce que cet
après-midi doit racheter, ce sont des euros.

**`marge_au_prix_de_depart` n'est pas une marge attendue.** C'est la marge *si
le lot part au prix de départ* : le meilleur cas, jamais le cas probable,
puisque le prix au marteau sera plus haut. Le nom le dit, pour que personne
n'ait à le deviner.

#### Le plancher de marge est une porte, pas un coefficient

```toml
[score]
marge_minimale_eur = 3500.0
marge_minimale_ratio = 0.20
```

Un lot dont la marge ne franchit pas `max(3 500 €, 20 % de la cote)` **quitte
le classement**. Il n'y descend pas : un coefficient se rattrape par un autre,
une porte fermée ne se rattrape pas. Le lot reste dans le JSON avec
`marge_sous_le_plancher: true` et son motif chiffré dans `score_explication`.

Les deux termes, et pourquoi il en faut deux : la somme fixe, parce que le
déplacement, la paperasse et l'argent immobilisé coûtent pareil sur n'importe
quel véhicule ; la part de la cote, parce que 3 500 € sur une cote de 40 000 €,
c'est du bruit. Le plus haut des deux l'emporte.

Sur le run du 25 août, **99 des 195 lots cotés tombent sous ce plancher** — le
Kangoo du rang 25 le premier, avec 2 919 € de marge.

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

### Chemins sous Windows

Dans une chaîne TOML entre guillemets, `\` ouvre une séquence d'échappement :
`repertoire = "C:\Users\moi\sorties"` échoue sur `Invalid hex value`. Deux
écritures correctes :

```toml
repertoire = "C:/Users/moi/sorties"     # barres obliques
repertoire = 'C:\Users\moi\sorties'    # apostrophes simples : rien n'est échappé
```

L'outil détecte ce cas précis et vous le dit dans le message d'erreur.

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
│   ├── text.py        normalisation FR + extractions (VIN, km, CT, Crit'Air…)
│   ├── exclusions.py  les onze règles, déclencheurs et contre-expressions
│   ├── territory.py   code postal → département, y compris Corse et outre-mer
│   └── codes.py       grammaire de la source (statuts, booléens, genres)
├── api/           ← LE TRANSPORT
│   ├── operations.py  requêtes GraphQL figées, identiques à celles du site
│   ├── transport.py   pile réseau du navigateur, session persistée
│   ├── client.py      limiteur de débit, reprises, refus du challenge
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

Le pipeline ne connaît pas `DomaineClient` : il dépend d'un `Protocol` à une
méthode. C'est ce qui permet de rejouer un run complet sur des fixtures.

### Langue du code

**Le code est en anglais** — noms de fichiers, de classes, de fonctions, de
variables, commentaires et docstrings compris. C'est la langue par défaut de
l'écosystème Python, et la seule qui évite les hybrides du genre
`extraire_vin`.

**Reste en français tout ce qu'un humain lit ou édite** :

| Quoi | Pourquoi |
|---|---|
| Sorties de la CLI, messages d'erreur, digest | interface opérateur |
| Cette documentation, les commentaires de `config/default.toml` | idem |
| Les **clés du JSON de sortie** (`reserve_aux_professionnels`, `mise_a_prix`…) | contrat avec le système aval, spécifié en français |
| Les **clés du fichier de configuration** (`[reseau]`, `departements`…) | interface éditée quotidiennement |
| Les **codes de règles** (`sans_cle`, `epave_ou_pieces`…) | ils apparaissent dans la sortie et dans la config |

Les deux contrats sont tenus par des **alias Pydantic** : les attributs sont
anglais, la forme sérialisée reste française. Un test verrouille cette
correspondance dans les deux sens.

**La base SQLite est en anglais**, tables et colonnes comprises
(`sale`, `lot`, `bid`, `hammer_price`, `listing_cache`) : c'est un détail
d'implémentation interne, jamais lu par l'opérateur.

### Les destinations de sortie

`output/sink.py` définit un `Protocol` à deux méthodes. Deux implémentations :

| Destination | Quand |
|---|---|
| [`FileSink`](src/sleeper/output/sink.py) | toujours, et en premier |
| [`DriveSink`](src/sleeper/output/drive.py) | quand `[sortie.drive] actif = true` |

#### Un dossier par jour, deux noms qui ne bougent pas

Les fichiers d'un run sont rangés dans un dossier à sa date ; les deux noms
stables restent au niveau du dessus.

```
Sleeper/
├── 2026-08-25/
│   ├── sleeper-2026-08-25-0430.json
│   └── sleeper-2026-08-25-0430.md
├── 2026-08-26/
│   └── …
├── latest.json      → pointe dans le dossier du jour
└── latest.md
```

```toml
[sortie]
dossier_par_date = true
format_dossier_date = "%Y-%m-%d"
```

**Pourquoi `latest.json` ne descend pas avec les autres.** Sur Drive, un
fichier déplacé garde son identifiant, mais un fichier *recréé* ailleurs en
reçoit un neuf. Si le nom stable déménageait chaque nuit, tout lien mis en
favori — et tout consommateur qui le lit — mourrait avec la journée
précédente. Vérifié : d'un dépôt à l'autre, `latest.json` conserve le même
identifiant Drive.

Un format qui produirait un nom vide, ou qui contiendrait un séparateur de
chemin (`%Y/%m`), est refusé au démarrage : sur Drive la barre oblique est un
caractère ordinaire, et le dossier s'appellerait littéralement `2026/08`.

**Le fichier local est écrit d'abord, et il reste la source.** Un échec de
dépôt sur Drive ne fait jamais échouer le run : l'erreur est repliée dans
`run.erreurs`, le fichier local est réécrit pour la porter, et l'opérateur la
trouve là où il la cherche.

#### Le chemin le plus court : ne pas passer par l'API

Si la destination est **votre propre Drive personnel** sur votre propre
machine, l'API n'apporte rien. Installez **Google Drive pour ordinateur** :
votre dossier devient un chemin sur le disque, et il suffit d'y pointer la
sortie ordinaire.

```toml
[sortie]
repertoire = "/Users/vous/Library/CloudStorage/GoogleDrive-vous@example.com/Mon Drive/Sleeper"
```

Aucun identifiant, aucun secret, aucun jeton, aucune dépendance
supplémentaire, rien qui expire — et c'est `FileSink`, la destination écrite
en premier à chaque run et la plus testée des deux.

> ⚠️ **Un espace synchronisé n'existe que si son client tourne.** Si Drive est
> arrêté la nuit, `mkdir` recréerait la branche en dossiers locaux ordinaires :
> le run réussirait, les fichiers seraient écrits, rien ne partirait, et vous
> croiriez publier depuis des semaines. `FileSink` refuse : sous une racine de
> synchronisation, seul le dernier niveau peut être créé, et le parent absent
> est une erreur qui nomme la cause. Hors de ces chemins, rien ne change — une
> première exécution crée toujours `var/sorties` toute seule.

L'API Drive reste utile pour une machine qui publie vers le Drive de
*quelqu'un d'autre*, ou vers un Drive partagé Workspace. C'est ce que décrit
la suite.

#### Deux authentifications, et le choix ne vous appartient pas

Google en propose deux, et laquelle s'applique dépend du **compte de
destination**, pas d'une préférence :

| Compte de destination | Voie | Pourquoi |
|---|---|---|
| Google Workspace, écrivant sur un **Drive partagé** | compte de service | tourne sans surveillance, aucun navigateur |
| Compte Google **personnel** (Gmail) | client OAuth | un compte de service **n'a aucun quota de stockage** : partagez-lui un dossier, il pourra le lire et sera refusé à chaque dépôt (`storageQuotaExceeded`) |

L'outil lit le fichier d'identifiants pour savoir auquel il a affaire : la
nature du fichier est écrite dedans, et la redemander en configuration ne
créerait qu'une seconde vérité capable de contredire la première.

Le scope est `drive.file` dans les deux cas — **le plus étroit qui permette
d'écrire**. L'outil voit les fichiers qu'il a créés, et rien d'autre de votre
Drive.

#### Activer le dépôt

```bash
uv sync --extra drive
```

```toml
[sortie.drive]
actif = true
credentials = "/chemin/hors/depot/identifiants.json"
jeton = "/chemin/hors/depot/drive-token.json"   # voie OAuth uniquement
dossier_id = "1AbC..."
```

Sur la voie OAuth, une autorisation unique, dans **votre** navigateur :

```bash
uv run sleeper autoriser-drive -c config/local.toml
```

C'est vous qui vous connectez et qui accordez l'accès. L'outil ne voit jamais
votre mot de passe. Le jeton obtenu se renouvelle seul : les runs planifiés
n'ouvrent plus rien, et `collecter` **n'ouvrira jamais** de navigateur de son
propre chef — une tâche nocturne qui attend un consentement que personne
n'accordera est un run perdu, pas un run lent.

> ⚠️ Dans la console Google Cloud, passez l'écran de consentement en
> **« En production »**. En « Test », Google fait expirer le jeton de
> rafraîchissement au bout de **7 jours** : l'outil s'arrêterait de publier
> chaque semaine. `drive.file` n'est pas un scope sensible, la mise en
> production ne demande aucune vérification manuelle.

La publication exige deux URL publiques. Celles de ce projet sont servies par
GitHub Pages depuis la branche `gh-pages`, dont les sources sont dans
[`site/`](site/) :

| Champ du formulaire Google | Valeur |
|---|---|
| Page d'accueil | `https://william-stoops.github.io/Sleeper/` |
| Règles de confidentialité | `https://william-stoops.github.io/Sleeper/confidentialite.html` |
| Domaine autorisé | `github.io` |

**Vérifié sur un compte Gmail personnel :** le scope `drive.file` permet bien
d'écrire dans un dossier que vous avez créé vous-même dans l'interface Drive,
et le remplacement se fait **en place** — `latest.json` garde le même
identifiant d'un run à l'autre, donc le lien reste valable et peut être mis en
favori.

> 🔐 **Ni les identifiants ni le jeton n'entrent dans le dépôt.** Seuls leurs
> chemins sont configuration, et `.gitignore` refuse les fichiers eux-mêmes.
> Le jeton est un secret à part entière : il porte un *refresh token*
> réutilisable, et il est écrit en `600`.

### L'état persistant a une valeur propre

SQLite ne sert pas qu'à détecter les nouveautés. La table `enchere` n'enregistre
une ligne **que lorsqu'un montant change**, ce qui construit une série
historique propre. Dans six mois, elle répondra à la question qui compte : à
quel pourcentage de la mise à prix les lots du Domaine partent-ils réellement ?
La table `hammer_price` conserve les prix constatés à la clôture : dès que la
source publie `bid_winner_amount` sur un lot, le montant et la mise à prix
correspondante sont consignés, une fois et une seule — **y compris pour les
lots écartés par une règle métier**. La série décrit le marché, pas votre
présélection ; la restreindre aux lots retenus la biaiserait avec vos propres
filtres.

---

## Développement

```bash
uv sync
uv run pre-commit install
```

| Commande | Rôle |
|---|---|
| `uv run pytest` | tous les tests, **aucun ne touche le réseau** |
| `uv run pytest --cov` | couverture (plancher : 90 %) |
| `uv run mypy` | typage strict, **zéro `# type: ignore`** |
| `uv run ruff check src tests tools` | lint |
| `uv run ruff format src tests tools` | format |
| `uv run python tools/check_no_personal_data.py` | aucune donnée personnelle dans les fixtures |
| `uv run python tools/generate_rules_doc.py > docs/regles-metier.md` | régénérer la doc des règles |
| `uv run python tools/audit_rule.py sans_cle --limit 30` | auditer une règle d'exclusion, avec le fragment déclencheur de chaque lot |

La CI GitHub Actions rejoue l'ensemble sur Linux, macOS et Windows, en Python
3.12 et 3.13, et vérifie en plus que le JSON Schema publié et la documentation
des règles suivent bien le code.

### Les tests ne touchent jamais le réseau

Les fixtures sont de **vraies réponses de l'API**, capturées le 2026-08-25 puis
**expurgées des données personnelles** — l'API renvoie l'IBAN du compte de
l'État ainsi que le nom, le courriel et le téléphone d'agents publics.
`tools/check_no_personal_data.py` refuse tout versionnement qui en réintroduirait,
et il tourne en pre-commit comme en CI.

### Rejouer la reconnaissance de l'API

Quand un run échoue en `UpstreamSchemaError`, c'est que le contrat amont a bougé :

```bash
uv run python tools/discover_api.py --out var/discovery
```

Procédure détaillée dans [`docs/api.md` §8](docs/api.md).

---

## Limites assumées

**Le site est protégé par un pare-feu applicatif UBIKA doublé d'un CAPTCHA
ALTCHA.** Cela impose trois choses, toutes délibérées :

1. **Les requêtes partent de la pile réseau d'un vrai navigateur.**
   C'est le point qui a coûté le plus cher, et il mérite d'être expliqué en
   entier, parce qu'il s'écarte de ce qui était prévu.

   Le plan initial — découvrir les endpoints JSON puis les appeler en `httpx`
   sans navigateur — **ne fonctionne pas sur ce site**. Ont été essayés, et
   mesurés :

   | Tentative | Résultat |
   |---|---|
   | `httpx` + requête GraphQL forgée | `400 — Bad query params length`, puis CAPTCHA |
   | `httpx` + requête **exacte** de l'application + cookies du navigateur | challenge JavaScript au lieu du JSON |
   | idem + en-têtes fonctionnels de l'application (`Store`, `Referer`, `Content-Type`) | challenge |
   | idem en **HTTP/2** | challenge |
   | requête émise **par le navigateur** (`context.request`) | **JSON** |

   Le pare-feu discrimine donc sur la **signature TLS** du client. La franchir
   supposerait de forger l'empreinte TLS d'un navigateur : c'est un
   contournement de protection anti-robot, explicitement hors périmètre.

   L'équivalent conforme est de faire émettre les requêtes **par le navigateur
   lui-même** (`api/transport.py`). Ce n'est pas un contournement : c'est un
   vrai navigateur, muni d'une vraie session, qui appelle l'API publique de
   l'application. Les pages ne sont simplement pas rendues — un choix de
   performance, pas une esquive. On conserve ainsi l'essentiel du gain visé :
   du JSON structuré, aucun sélecteur CSS, aucun parsing de DOM.

   **Le navigateur n'est pas en mode headless, et c'est délibéré.** En headless,
   Chromium annonce `HeadlessChrome/151…` dans son User-Agent, ce que le
   pare-feu refuse. Deux issues étaient possibles : masquer ce jeton, ou ouvrir
   un vrai navigateur. Masquer aurait été un déguisement. La session est
   persistée entre les exécutions (`storage_state`), de sorte que le challenge
   d'entrée n'est repassé que lorsqu'il expire.

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
   `AntiBotChallengeError`, **sans aucune reprise**, et le run s'arrête avec
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
| **google-api-python-client**, **google-auth** | dépôt du JSON classé sur Drive. **Optionnels** (`--extra drive`) : une machine qui ne publie pas n'a pas à les installer |
| **google-auth-oauthlib** | consentement navigateur unique, seule voie d'écriture sur un compte Google personnel — un compte de service n'y a pas de quota. Bibliothèque officielle, **optionnelle** (`--extra drive`) |
| **playwright** | **seul moyen d'atteindre l'API sans contourner la protection anti-robot** : le pare-feu du site rejette tout client dont la signature TLS n'est pas celle d'un navigateur. Sert aussi à la phase de reconnaissance |
| **pydantic** v2 | modèles typés, validation, et **génération du JSON Schema** depuis les mêmes classes : le contrat de sortie a une seule source de vérité |
| **typer** | CLI typée dérivée des annotations, cohérente avec `mypy --strict` |
| **rich** | tableau de bilan lisible en fin de run |
| **structlog** | journalisation structurée JSON, indispensable pour une tâche planifiée non surveillée |
| **jsonschema** | valide le document contre le schéma **publié sur disque**. Ce détour est volontaire : il fait échouer le run si le schéma versionné et les modèles divergent, là où une validation Pydantic ne validerait le document que contre lui-même |

### Développement

`pytest`, `pytest-cov`, `mypy`, `ruff`, `pre-commit`, `types-jsonschema`.

### Écarté délibérément

| Envisagé | Pourquoi non |
|---|---|
| `httpx` | **retiré** : inutilisable ici, le pare-feu du site rejette sa signature TLS. Le transport passe par le navigateur |
| `pytest-recording` / `vcrpy` | le transport est derrière un `Protocol` : un transport factice suffit, et les fixtures restent des fichiers JSON lisibles et expurgeables à la main |
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
