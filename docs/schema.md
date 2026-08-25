# Contrat de sortie — versions et migration

Le document produit par chaque run porte un champ `schema_version`. Le schéma
JSON correspondant est publié dans [`schemas/`](../schemas/), et le document
est **validé contre ce fichier avant écriture** : si les modèles et le schéma
publié divergent, le run échoue plutôt que de livrer.

| Version | Date | État | Schéma |
|---|---|---|---|
| `1.0` | 2026-08-25 | **gelée** — ne plus produire | [`schemas/sortie-1.0.json`](../schemas/sortie-1.0.json) |
| `2.0` | 2026-08-25 | **gelée** — ne plus produire | [`schemas/sortie-2.0.json`](../schemas/sortie-2.0.json) |
| `3.0` | 2026-08-25 | **courante** | [`schemas/sortie-3.0.json`](../schemas/sortie-3.0.json) |

---

## Règle de lecture, non négociable

> **Un consommateur doit échouer bruyamment sur une `schema_version` inconnue.
> Jamais de lecture dégradée.**

Ce n'est pas une précaution de principe. Un document 1.0 écrit
`"hors_perimetre": false` là où un 2.0 écrit `"perimetre": "inconnu"`. Le lire
comme un 2.0 transformerait « on n'a pas su déterminer le lieu » en « le lot
est dans le périmètre » — exactement la défaillance silencieuse que tout ce
contrat existe pour empêcher.

Sleeper fournit la fonction qui applique cette règle :

```python
from pathlib import Path
from sleeper.output.document import read_document

document = read_document(Path("latest.json"))  # lève OutputError si la version diffère
```

**Aucune rétrocompatibilité de code n'est assurée.** La 1.0 est gelée : son
schéma reste publié pour que d'anciens fichiers restent interprétables, mais
plus rien ne la produit et rien ne la relit.

---

## Migration 2.0 → 3.0

Un seul champ change de nom, et il change de sens en même temps — d'où la
version majeure plutôt qu'une mineure.

### Au niveau du lot

| 2.0 | 3.0 | Pourquoi |
|---|---|---|
| `marge_theorique` | **`marge_au_prix_de_depart`** | le nom laissait croire à une marge attendue. C'est la marge **si le lot part au prix de départ** : le meilleur cas, jamais le cas probable, puisque le prix au marteau sera plus haut |
| — | **`marge_sous_le_plancher`** | vrai quand la marge ne franchit pas le plancher. Le lot reste dans le document, avec son motif dans `score_explication`, mais il n'a pas de rang |

### Ce que `score` veut dire désormais

**Des euros, plus un ratio.** La 2.0 calculait `marge / cote`, ce qui classait
la voiture bon marché en tête : réaliser 80 % d'une cote de 3 000 € est facile,
80 % d'une cote de 30 000 € ne l'est pas. Un consommateur qui comparait des
scores 2.0 et 3.0 comparerait des grandeurs sans rapport — c'est précisément ce
que le refus de lecture dégradée empêche.

---

## Migration 1.0 → 2.0

### Au niveau de la vente

| 1.0 | 2.0 | Pourquoi |
|---|---|---|
| `dans_perimetre` *(booléen)* | **`perimetre`** *(`dans` / `hors` / `inconnu`)* | un lieu vide n'est pas un hors périmètre — la vente 567 « spéciale véhicule d'exception » s'était évaporée d'un scan entier |
| — | **`frais_acheteur_pct`** | le taux dont dépend tout calcul de plafond d'enchère |
| — | **`frais_acheteur_source`** | `vente`, `lot`, `config` ou `absent` |
| — | **`conditions_vente_texte`** | les conditions publiées, quand la source en publie |

### Au niveau du lot

| 1.0 | 2.0 | Pourquoi |
|---|---|---|
| `hors_perimetre` *(booléen)* | **`perimetre`** *(énuméré)* + **`perimetre_herite`** | idem, plus l'héritage du lieu de la vente |
| `controle_technique` *(chaîne)* | **objet typé** | la chaîne mêlait `"absent"`, `"présent"` et une date, et `"absent"` était ambigu |
| — | **`dommages_carrosserie`** | `aucun` / `usage` / `cosmetique` / `structurel`, **n'exclut jamais** |
| — | **`segment`** | `vl` / `vu` / `pl` / `engin` |
| — | **`km_par_an`** | le repère de vraisemblance usuel |
| — | **`frais_acheteur_source`**, **`frais_hypothetiques`** | une hypothèse doit se voir |
| — | **`cote_reference`**, **`remise_en_etat_estimee`**, **`marge_theorique`**, **`score`**, **`rang`**, **`score_explication`**, **`non_reparable_economiquement`**, **`a_coter`** | la couche de tri |

#### L'objet `controle_technique`

```jsonc
{
  "mentionne": true,          // la fiche dit quelque chose — même « il n'y en a pas »
  "date": "2026-07-16",       // null si non datée
  "resultat": "favorable_defaillances_mineures",
  "valide_a_la_date_du_run": true   // null si la date est inconnue
}
```

`resultat` vaut `favorable`, `favorable_defaillances_mineures`,
`defavorable_contre_visite` ou `inconnu`.

> **Piège traité :** « CT favorable du 10/07/2026 (périmé) ». La mention de
> péremption prime sur le verdict — le résultat reste `favorable`, la validité
> tombe à `false`. Ce sont deux questions différentes.

#### Le champ `score_explication`

Chaque règle ayant pesé sur le rang y figure, avec **le fragment exact** qui
l'a déclenchée :

```jsonc
[
  { "regle": "reserve_aux_professionnels", "coefficient": 1.20 },
  { "regle": "faible_km_par_an", "coefficient": 1.15,
    "extrait_declencheur": "5560 km/an" },
  { "regle": "revision_base", "cout_eur": 400.0,
    "extrait_declencheur": "révision générale à effectuer" }
]
```

Un rang que personne ne peut expliquer est un rang auquel personne ne peut se
fier.

### Au niveau du run

Quatre compteurs s'ajoutent, et ils se lisent en premier :

| Champ | Ce qu'il dit |
|---|---|
| `lots_perimetre_inconnu` | lots dont le lieu de retrait n'a pas pu être lu |
| `lots_sans_cote` | lots que la table de cotes ne connaît pas |
| `ventes_sans_frais_publies` | ventes dont le taux de frais est une hypothèse |
| `anomalies_integrite` | VIN en double, kilométrages incohérents, prix aberrants |

---

## Faire évoluer le contrat

1. Modifier les modèles dans [`src/sleeper/domain/models.py`](../src/sleeper/domain/models.py) — c'est la seule source de vérité.
2. Incrémenter `SCHEMA_VERSION` dans [`src/sleeper/output/document.py`](../src/sleeper/output/document.py).
3. `uv run sleeper schema` — le nouveau fichier apparaît, **les anciens ne sont jamais touchés**.
4. Documenter la migration ici.

La CI vérifie que le schéma publié suit les modèles : toute dérive fait échouer
la construction.
