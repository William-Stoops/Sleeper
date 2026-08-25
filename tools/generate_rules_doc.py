"""Regenerate docs/regles-metier.md from the code.

The business-rule documentation derives from the rules themselves, so it
cannot lie about what the tool actually does. CI checks that the versioned
file matches what this script produces.

    uv run python tools/generate_rules_doc.py > docs/regles-metier.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from sleeper.domain.codes import OUT_OF_SCOPE_KINDS
from sleeper.domain.damage import DAMAGE_PATTERNS
from sleeper.domain.exclusions import CLASSIC_CAR_YEAR, DEFAULT_RULES

HEADER: Final = """\
# Règles métier — formulations reconnues

> **Ce fichier est généré depuis le code** (`src/sleeper/domain/exclusions.py`).
> Pour ajouter une formulation, deux voies :
>
> 1. **sans toucher au code** — l'ajouter dans `config/default.toml`, section
>    `[exclusions.formulations_supplementaires]`. C'est la voie normale ;
> 2. **dans le code** — l'ajouter à la règle concernée, avec un test.
>
> Régénérer ensuite : `uv run python tools/generate_rules_doc.py > docs/regles-metier.md`

## Comment une règle décide

Chaque règle interroge **deux sources**, dans cet ordre :

1. **l'attribut structuré** de la fiche (`vehicle_has_a_key`, `vhu_declared`…),
   qui est fiable. S'il tranche, c'est fini ;
2. **le texte libre** de la description, qui ne l'est pas — il est saisi à la
   main par des agents différents selon la direction régionale, fautes de frappe
   comprises (« porfessionnels » a été relevé tel quel en production).

Sur le texte, une règle porte deux listes :

- des **expressions déclenchantes** ;
- des **contre-expressions**, évaluées **d'abord**, qui annulent la règle.

C'est ce qui permet à « sans choc apparent » de ne pas écarter un lot sain,
tout en laissant « choc avant » l'écarter.

> ⚠️ **Piège vérifié par un test** : une contre-expression ne doit jamais être
> un fragment de son propre déclencheur. La contre-expression `roulant`
> annulerait le déclencheur `non roulant`. Écrire `véhicule roulant`.

La comparaison se fait sur la forme **normalisée** : minuscules, sans accents,
sans ponctuation, en **mots entiers**. « Véhicule NON-ROULANT » et
« vehicule non roulant » sont donc équivalents, tandis que « chargeur » ne
déclenche pas sur « charge ».

## Ordre d'évaluation

L'ordre ci-dessous est celui du code, et il est **significatif** : un lot
cumulant plusieurs défauts rend toujours le premier motif de la liste, ce qui
rend le verdict reproductible d'un run à l'autre.

## Les règles
"""

FOOTER: Final = """\
## Attributs structurés qui priment sur le texte

| Règle | Attribut de la fiche | Verdict |
|---|---|---|
| `hors_categorie_vehicule` | `kind`, `vehicle_brand`, `vehicle_model` | **tous vides** → écarté. Cette règle n'a aucune expression textuelle : elle ne juge que la présence d'attributs véhicule |
| `genre_hors_cible` | `kind` | code hors cible → écarté |
| `collection_avant_1990` | `date_first_registration` | année < {annee} → écarté |
| `sans_cle` | `vehicle_has_a_key` | `Non` → écarté |
| `sans_certificat_immatriculation` | `registration_certificate` | `Non` → écarté |
| `epave_ou_pieces` | `vhu_declared` | `Oui` → écarté |
| `non_roulant` | `registrable_again` | `Non` → écarté |
| `kilometrage_inconnu` | `vehicle_mileage` | absent **ou zéro** → écarté, sauf si un kilométrage figure dans le texte |

Deux précisions tirées des données réelles :

- **un compteur à zéro n'est pas un kilométrage** : c'est une absence de
  saisie, et le code le traite comme telle ;
- **le genre est lu sur son seul code J.1**. L'attribut porte des valeurs
  composées (`VASP - DERIV_VP`) et une casse inconstante (`vp`) : seul le
  premier jeton est le code de la carte grise.

## Genres de carte grise écartés d'office

Rubrique J.1 du certificat d'immatriculation, attribut `kind` :

{genres}

`QM` couvre le quadricycle à moteur, c'est-à-dire la voiture sans permis.
Les genres retenus sont tous les autres, `VP` (voiture particulière) et
`CTTE` (camionnette) en tête.

## Mentions positives extraites en champs structurés

Ces formulations ne déclenchent aucune exclusion : elles sont **extraites** du
texte libre et remontent en champs propres dans le JSON.

| Formulation type | Champ de sortie |
|---|---|
| `Avec CG et clé` | `carte_grise`, `cles` (attribut structuré prioritaire) |
| `Dernier CT en date du 03/12/2025` | `controle_technique` → `2025-12-03` |
| `CT OK 05/2027` | `controle_technique` → `2027-05` |
| `Très bon état général`, `Réparations à prévoir` | `etat_declare`, **tel quel** |
| `n° série VF1FC1EAF39868928` | `vin` |
| `06 cv` | `puissance_fiscale` → `6` |
| `15500 km`, `120 000 km`, `87.500 kms` | `kilometrage` |
| `Crit'Air 2` | `crit_air` → `2` |
| `Visites sur place le Mercredi 29/07/2026 de 08h00 à 11h00` | `dates_visite`, **tel quel** |

`description_integrale` conserve toujours le texte source complet, sans
reformulation : c'est la matière première de l'analyse aval.

## Ce qui n'est jamais écarté

Un lot **hors périmètre géographique n'est pas supprimé**. Il est marqué
`hors_perimetre: true` et conservé dans la sortie : la décision de faire la
route appartient à l'opérateur, pas à l'outil.

Un lot dont la mention « réservé aux professionnels » n'a pas pu être lue
n'est **pas** livré avec une valeur par défaut. Il sort avec
`reserve_aux_professionnels: null`, `champs_manquants` renseigné, une entrée
dans `run.erreurs`, une section dédiée dans le digest, et le run se termine
avec le code de sortie `1`.

"""


def render() -> str:
    """Compose the full rule documentation."""
    parts = [HEADER]
    for rank, rule in enumerate(DEFAULT_RULES, 1):
        parts.append(f"\n### {rank}. `{rule.code}`\n")
        parts.append(f"\n**{rule.label}**\n")
        if rule.phrases:
            parts.append("\nDéclenche sur :\n\n")
            parts.append("\n".join(f"- `{p}`" for p in rule.phrases))
            parts.append("\n")
        if rule.counter_phrases:
            parts.append("\nAnnulée par :\n\n")
            parts.append("\n".join(f"- `{c}`" for c in rule.counter_phrases))
            parts.append("\n")
    parts.append("\n")
    parts.append(_damage_section())
    parts.append(
        FOOTER.format(
            annee=CLASSIC_CAR_YEAR,
            genres=", ".join(f"`{k}`" for k in sorted(OUT_OF_SCOPE_KINDS)),
        )
    )
    return "".join(parts)


def _damage_section() -> str:
    """Dommages de carrosserie : les motifs, et le reclassement des lots réels."""
    lignes = [
        "\n## Dommages de carrosserie — gradués, jamais excluants\n",
        "\nSur ce gisement, presque toutes les descriptions mentionnent un choc.",
        "\n« Coups, chocs, rayures et frottements d'usage » est une formule",
        "\nadministrative. En faire un motif d'exclusion revient à jeter le",
        "\ngisement : le meilleur dossier du run du 25/08 — un Ford Transit de 2021",
        "\nà 27 798 km, mis à prix 800 € — en porte deux.\n",
        "\nLe niveau est donc **gradué**, il alimente le budget de remise en état",
        "\net le score, et il n'écarte jamais.\n",
        "\n| Niveau | Motif de déclenchement (forme normalisée) |\n|---|---|\n",
    ]
    for niveau, motif in DAMAGE_PATTERNS.items():
        lignes.append(f"| `{niveau}` | `{motif}` |\n")
    lignes.append("| `aucun` | aucune des formes ci-dessus, et aucun mot d'impact isolé |\n")

    reclasses = _reclassified_lots()
    if reclasses:
        lignes.append(
            "\n### Reclassement des lots que l'ancienne règle écartait\n"
            "\nLes dix lots écartés pour `choc_ou_accident` lors du run du"
            " 2026-08-25, tels qu'ils sont désormais classés. Aucun n'est plus"
            " exclu.\n"
            "\n| Lot | Niveau | Titre |\n|---|---|---|\n"
        )
        for lot_id, lot in sorted(reclasses.items()):
            lignes.append(f"| [{lot_id}]({lot['url']}) | `{lot['dommages']}` | {lot['titre']} |\n")
    return "".join(lignes)


def _reclassified_lots() -> dict[str, dict[str, str]]:
    """Lit la fixture du run réel, si elle est présente."""
    fixture = Path("tests/fixtures/reel/run-2026-08-25.json")
    if not fixture.is_file():
        return {}
    charge: dict[str, dict[str, str]] = json.loads(fixture.read_text(encoding="utf-8")).get(
        "choc_reclasses", {}
    )
    return charge


def main() -> int:
    """Write the documentation to standard output.

    The trailing newline is deliberate: it aligns the output with what the
    pre-commit guards expect.
    """
    print(render().rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
