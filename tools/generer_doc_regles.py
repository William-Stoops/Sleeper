"""Regenere docs/regles-metier.md depuis le code.

La documentation des regles metier est derivee des regles elles-memes : elle
ne peut donc pas mentir sur ce que l'outil fait reellement. La CI verifie que
le fichier versionne correspond bien a ce que ce script produit.

    uv run python tools/generer_doc_regles.py > docs/regles-metier.md
"""

from __future__ import annotations

from typing import Final

from sleeper.domain.codes import GENRES_HORS_CIBLE
from sleeper.domain.exclusions import ANNEE_COLLECTION, REGLES_PAR_DEFAUT

ENTETE: Final = """\
# Règles métier — formulations reconnues

> **Ce fichier est généré depuis le code** (`src/sleeper/domain/exclusions.py`).
> Pour ajouter une formulation, deux voies :
>
> 1. **sans toucher au code** — l'ajouter dans `config/default.toml`, section
>    `[exclusions.formulations_supplementaires]`. C'est la voie normale ;
> 2. **dans le code** — l'ajouter à la règle concernée, avec un test.
>
> Régénérer ensuite : `uv run python tools/generer_doc_regles.py > docs/regles-metier.md`

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

PIED: Final = """\
## Attributs structurés qui priment sur le texte

| Règle | Attribut de la fiche | Verdict |
|---|---|---|
| `kilometrage_inconnu` | `vehicle_mileage` | absent **ou zéro** → écarté, sauf si un kilométrage figure dans le texte |
| `sans_cle` | `vehicle_has_a_key` | `Non` → écarté |
| `sans_certificat_immatriculation` | `registration_certificate` | `Non` → écarté |
| `non_roulant` | `registrable_again` | `Non` → écarté |
| `epave_ou_pieces` | `vhu_declared` | `Oui` → écarté |
| `genre_hors_cible` | `kind` | code hors cible → écarté |
| `collection_avant_{annee}` | `date_first_registration` | année < {annee} → écarté |

Un compteur à zéro n'est pas un kilométrage : c'est une absence de saisie. Le
code le traite comme tel.

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


def rediger() -> str:
    """Compose la documentation complete des regles."""
    morceaux = [ENTETE]
    for rang, regle in enumerate(REGLES_PAR_DEFAUT, 1):
        morceaux.append(f"\n### {rang}. `{regle.code}`\n")
        morceaux.append(f"\n**{regle.libelle}**\n")
        if regle.expressions:
            morceaux.append("\nDéclenche sur :\n\n")
            morceaux.append("\n".join(f"- `{e}`" for e in regle.expressions))
            morceaux.append("\n")
        if regle.contre_expressions:
            morceaux.append("\nAnnulée par :\n\n")
            morceaux.append("\n".join(f"- `{c}`" for c in regle.contre_expressions))
            morceaux.append("\n")
    morceaux.append("\n")
    morceaux.append(
        PIED.format(
            annee=ANNEE_COLLECTION,
            genres=", ".join(f"`{g}`" for g in sorted(GENRES_HORS_CIBLE)),
        )
    )
    return "".join(morceaux)


def main() -> int:
    """Ecrit la documentation sur la sortie standard."""
    print(rediger(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
