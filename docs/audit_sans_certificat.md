# Audit de la règle `sans_certificat_immatriculation`

> Run du 2026-08-25 · **237 lots écartés** pour ce motif, dont les 30 premiers ci-dessous.

Chaque ligne porte **le fragment exact de la description qui a déclenché la
règle**. Un motif sans sa preuve n'est pas vérifiable.

Quand la colonne « déclencheur » indique *(attribut)*, la règle n'a pas
lu de texte : elle a tranché sur un attribut structuré de la fiche, qui
est fiable. Ces cas-là ne sont pas discutables.

Un segment `engin` signale un lot **mal attribué** : il n'est pas
immatriculable et n'aurait jamais dû atteindre un filtre d'état. Le
prédicat corrigé le range désormais en `hors_categorie_vehicule`.

| Lot | Titre | Segment | Déclencheur | Extrait |
|---|---|---|---|---|
| [192050](https://encheres-domaine.gouv.fr/lot/citroenjumpy-1-doo-4.html) | Citroën JUMPY | `vl` | *(attribut)* | — |
| [192051](https://encheres-domaine.gouv.fr/lot/citroenjumpy-1-doo-5.html) | Citroën JUMPY | `vl` | *(attribut)* | — |
| [192109](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-1.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [192301](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-6.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [192347](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-9.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [192371](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-10.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [192375](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-11.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [298507](https://encheres-domaine.gouv.fr/lot/peugeot-206-doo-35.html) | PEUGEOT 206+ | `vl` | *(attribut)* | — |
| [298554](https://encheres-domaine.gouv.fr/lot/peugeot-206-doo-36.html) | PEUGEOT 206 | `vl` | *(attribut)* | — |
| [298564](https://encheres-domaine.gouv.fr/lot/renault-kangoo-doo-116.html) | RENAULT KANGOO | `vl` | *(attribut)* | — |
| [298578](https://encheres-domaine.gouv.fr/lot/peugeot-bipper-doo-8.html) | PEUGEOT BIPPER | `vu` | *(attribut)* | — |
| [298581](https://encheres-domaine.gouv.fr/lot/citroen-berlingo-doo-33.html) | CITROEN BERLINGO | `vu` | *(attribut)* | — |
| [298592](https://encheres-domaine.gouv.fr/lot/peugeot-308-doo-62.html) | PEUGEOT 308 | `vl` | *(attribut)* | — |
| [298596](https://encheres-domaine.gouv.fr/lot/peugeot-308-doo-63.html) | PEUGEOT 308 | `vl` | *(attribut)* | — |
| [298601](https://encheres-domaine.gouv.fr/lot/peugeot-206-doo-37.html) | PEUGEOT 206+ | `vl` | *(attribut)* | — |
| [298607](https://encheres-domaine.gouv.fr/lot/peugeot-308-doo-64.html) | PEUGEOT 308 | `vl` | *(attribut)* | — |
| [298615](https://encheres-domaine.gouv.fr/lot/peugeot-308-doo-65.html) | PEUGEOT 308 | `vl` | *(attribut)* | — |
| [298627](https://encheres-domaine.gouv.fr/lot/peugeot-206-doo-38.html) | PEUGEOT 206+ | `vl` | *(attribut)* | — |
| [213337](https://encheres-domaine.gouv.fr/lot/citroenjumpyspacetourer-1-doo-12.html) | Citroën JUMPY Space Tourer | `vl` | *(attribut)* | — |
| [256279](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-2.html) | CLIO V | `vl` | *(attribut)* | — |
| [256288](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-3.html) | CLIO V | `vl` | *(attribut)* | — |
| [256290](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-4.html) | CLIO V | `vl` | *(attribut)* | — |
| [256293](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-5.html) | CLIO V | `vl` | *(attribut)* | — |
| [256294](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-6.html) | CLIO V | `vl` | *(attribut)* | — |
| [256296](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-7.html) | CLIO V | `vl` | *(attribut)* | — |
| [256299](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-8.html) | CLIO V | `vl` | *(attribut)* | — |
| [256302](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-9.html) | CLIO V | `vl` | *(attribut)* | — |
| [256305](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-10.html) | CLIO V | `vl` | *(attribut)* | — |
| [256316](https://encheres-domaine.gouv.fr/lot/cliov-1-doo-14.html) | RENAULT CLIO V | `vl` | *(attribut)* | — |
| [256320](https://encheres-domaine.gouv.fr/lot/e-208-1.html) | E-208 | `vl` | *(attribut)* | — |

## Bilan

- **0 lot(s) mal attribué(s)** sur les 30 audités :
  ce sont des engins non immatriculables, désormais rangés en
  `hors_categorie_vehicule`.
- **30 lot(s)** ont déclenché sur un **attribut structuré** de la
  fiche, pas sur du texte : ces verdicts-là ne sont pas discutables.
- **0 lot(s)** ont déclenché sur une expression.

À valider à la main : ces derniers, quand l'extrait ne justifie pas
l'écartement.
