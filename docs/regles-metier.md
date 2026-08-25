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

### 1. `hors_categorie_vehicule`

**Lot sans attribut vehicule (mobilier, high-tech, bijoux…)**

### 2. `genre_hors_cible`

**Genre de vehicule hors cible (deux-roues, quadricycle, agricole, remorque)**

Déclenche sur :

- `moto`
- `motocyclette`
- `scooter`
- `cyclomoteur`
- `quad`
- `quadricycle`
- `remorque`
- `semi remorque`
- `caravane`
- `tracteur agricole`
- `engin agricole`
- `moissonneuse`
- `tondeuse autoportee`
- `sans permis`
- `voiturette`

Annulée par :

- `porte moto`
- `remorque non comprise`

### 3. `collection_avant_1990`

**Vehicule de collection anterieur a 1990**

Déclenche sur :

- `vehicule de collection`
- `carte grise de collection`

### 4. `sans_cle`

**Vehicule sans cle**

Déclenche sur :

- `sans cle`
- `sans cles`
- `sans clef`
- `sans clefs`
- `cle absente`
- `cles absentes`
- `clef absente`
- `absence de cle`
- `absence de cles`
- `absence de clef`
- `pas de cle`
- `pas de cles`
- `pas de clef`
- `aucune cle`
- `cle manquante`
- `cles manquantes`

Annulée par :

- `avec cle`
- `avec cles`
- `avec clef`
- `presence de cle`

### 5. `sans_certificat_immatriculation`

**Absence de certificat d'immatriculation**

Déclenche sur :

- `sans carte grise`
- `sans cg`
- `cg absente`
- `carte grise absente`
- `absence de carte grise`
- `absence de certificat d immatriculation`
- `sans certificat d immatriculation`
- `pas de carte grise`
- `pas de cg`
- `carte grise manquante`
- `cg non fournie`
- `carte grise non fournie`
- `vehicule non immatricule`

Annulée par :

- `avec cg`
- `avec carte grise`
- `carte grise fournie`

### 6. `epave_ou_pieces`

**Epave ou vente pour pieces**

Déclenche sur :

- `epave`
- `pour pieces`
- `pieces detachees`
- `vehicule hors d usage`
- `vhu`
- `destruction obligatoire`
- `a detruire`
- `cession pour destruction`

Annulée par :

- `pieces jointes`
- `pieces du dossier`

### 7. `non_roulant`

**Vehicule non roulant**

Déclenche sur :

- `non roulant`
- `ne roule pas`
- `ne demarre pas`
- `vehicule immobilise`
- `etat non roulant`
- `hors etat de rouler`
- `ne circule plus`

Annulée par :

- `vehicule roulant`
- `en etat de rouler`
- `demarre correctement`
- `demarre et roule`

### 8. `moteur_hors_service`

**Moteur hors service**

Déclenche sur :

- `moteur hors service`
- `moteur hs`
- `moteur casse`
- `moteur a refaire`
- `moteur serre`
- `moteur bloque`
- `joint de culasse hs`
- `boite hs`

Annulée par :

- `moteur en bon etat`
- `moteur revise`

### 9. `choc_ou_accident`

**Choc, accident ou degats de carrosserie**

Déclenche sur :

- `accidente`
- `accidentee`
- `vehicule accidente`
- `choc avant`
- `choc arriere`
- `choc lateral`
- `degats de carrosserie`
- `degat de carrosserie`
- `carrosserie endommagee`
- `carrosserie abimee`
- `sinistre`
- `vehicule sinistre`
- `impacts de carrosserie`

Annulée par :

- `sans choc`
- `aucun choc`
- `non accidente`
- `non accidentee`
- `aucun degat de carrosserie`
- `aucun degat`
- `sans degat`
- `carrosserie en bon etat`

### 10. `gage_ou_opposition`

**Gage ou opposition**

Déclenche sur :

- `gage`
- `gagee`
- `vehicule gage`
- `opposition`
- `saisie conservatoire`
- `situation administrative bloquee`

Annulée par :

- `sans gage`
- `non gage`
- `aucune opposition`
- `sans opposition`

### 11. `kilometrage_inconnu`

**Kilometrage inconnu, non renseigne ou absent**

Déclenche sur :

- `kilometrage inconnu`
- `kilometrage non renseigne`
- `km inconnu`
- `compteur non fonctionnel`
- `compteur hs`
- `compteur bloque`
- `kilometrage non garanti`
- `compteur non fiable`

## Attributs structurés qui priment sur le texte

| Règle | Attribut de la fiche | Verdict |
|---|---|---|
| `kilometrage_inconnu` | `vehicle_mileage` | absent **ou zéro** → écarté, sauf si un kilométrage figure dans le texte |
| `sans_cle` | `vehicle_has_a_key` | `Non` → écarté |
| `sans_certificat_immatriculation` | `registration_certificate` | `Non` → écarté |
| `non_roulant` | `registrable_again` | `Non` → écarté |
| `epave_ou_pieces` | `vhu_declared` | `Oui` → écarté |
| `genre_hors_cible` | `kind` | code hors cible → écarté |
| `collection_avant_1990` | `date_first_registration` | année < 1990 → écarté |

Un compteur à zéro n'est pas un kilométrage : c'est une absence de saisie. Le
code le traite comme tel.

## Genres de carte grise écartés d'office

Rubrique J.1 du certificat d'immatriculation, attribut `kind` :

`CL`, `CM`, `MAAG`, `MAGA`, `MIAR`, `MTL`, `MTT1`, `MTT2`, `MTT3`, `MTT4`, `QLEM`, `QLOM`, `QM`, `REM`, `REMORQUE`, `RESP`, `SREM`, `TRA`

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
