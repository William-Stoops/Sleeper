# Audit de la règle `sans_cle`

> Run du 2026-08-25 · **155 lots écartés** pour ce motif, dont les 30 premiers ci-dessous.

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
| [298559](https://encheres-domaine.gouv.fr/lot/fiat-scudo-doo-5.html) | FIAT SCUDO | `vl` | *(attribut)* | — |
| [298569](https://encheres-domaine.gouv.fr/lot/fiat-ducato-doo-10.html) | FIAT DUCATO | `vu` | *(attribut)* | — |
| [298585](https://encheres-domaine.gouv.fr/lot/peugeot-308-doo-61.html) | peugeot 308 | `vl` | *(attribut)* | — |
| [134374](https://encheres-domaine.gouv.fr/lot/68e164415a04c.html) | LAND ROVER | `vl` | `absence de cle` | …rie SALLJGMF8HA480195, 1 ère mis en circulation 13/03/1991, 10 cv, 07 places. km inconnu .Absence de clé . Visites sur place uniquement le vendredi 31/07/2026 de 09h00 à 10h30 Enlèvement sur pla… |
| [204445](https://encheres-domaine.gouv.fr/lot/fiat-500-av-893-se-1.html) | FIAT 500 | `vl` | `pas de cle` | …e ZFA31200000098945, 1 ère mise en circulation le 28/11/2008, 06 cv, 04 places . Fermé et pas de clé. Enlèvement sur plateau obligatoire à la charge exclusive de l'acquéreur et sur rendez vo… |
| [273148](https://encheres-domaine.gouv.fr/lot/69fb1d574f627.html) | PEUGEOT 208 | `vl` | *(attribut)* | — |
| [130083](https://encheres-domaine.gouv.fr/lot/renaultmeganecabriolet-1-doo-1.html) | RENAULT MEGANE CABRIOLET | `vl` | `absence de cle` | …0, n° série VF1EA04B521823347, 1 ère mise en circulation le 16/02/2000, 07 cv, 04 places, absence de clé . etat général mauvais. Visites sur place uniquement le jeudi 30/07/2026 de 13h00 à 15h00… |
| [130106](https://encheres-domaine.gouv.fr/lot/renaulttwingo-1-doo-7.html) | RENAULT TWINGO | `vl` | `pas de cle` | …1, n° serie VF1C06G0E37312956, 1ère mis e en circulation le 28/03/2007, 04 cv, 04 places. pas de clé. Visites sur place uniquement le jeudi 30/07/2026 de 13h00 à 15h00 sur rendez vous pris a… |
| [130108](https://encheres-domaine.gouv.fr/lot/renaultclio-1-doo-50.html) | RENAULT CLIO | `vl` | `pas de cle` | …02/2003, 10 cv, 05 places. Véhicule en mauvais état.Absence de calandre et d'un optique , pas de clé. Visites sur place uniquement le jeudi 30/07/2026 de 13h00 à 15h00 sur rendez vous pris a… |
| [130113](https://encheres-domaine.gouv.fr/lot/vwpolo1-2l-1.html) | VW POLO 1.2 l | `vl` | `absence de cle` | …0, n° série WVWZZZ9NZ6Y175193, 1 ère mise en circulation le 23/03/2006, 04 cv, 05 places, absence de clé. Visites sur place uniquement le jeudi 30/07/2026 de 13h00 à 15h00 sur rendez vous pris a… |
| [130116](https://encheres-domaine.gouv.fr/lot/vwpolo1-9l-1.html) | VW POLO 1.9l | `vl` | `absence de cle` | …22, n° série WVWZZZ9NZ4Y067892, 1 ère mise en circulation le 06/01/2004, 04cv, 05 places. Absence de clé. Visites sur place uniquement le jeudi 30/07/2026 de 13h00 à 15h00 sur rendez vous pris a… |
| [305378](https://encheres-domaine.gouv.fr/lot/207-1-doo-3.html) | PEUGEOT 207 | `vl` | *(attribut)* | — |
| [208278](https://encheres-domaine.gouv.fr/lot/ambulancepompier-1-doo-1.html) | RENAULT MASTER | `vl` | *(attribut)* | — |
| [175827](https://encheres-domaine.gouv.fr/lot/camionciternegrandecapaciter-1.html) | CAMION IVECO | `pl` | `sans cle` | …1ère mise en circulation 13/03/2007, 21 cv, 03 places, genre VASP , carrosserie INCENDIE, sans clé, ne démarre pas Véhicule vendu en l'état. Voir conditions de visite auprès du lieu de dép… |
| [120948](https://encheres-domaine.gouv.fr/lot/68c85828c2ca6.html) | RENAULT MEGANE | `vl` | *(attribut)* | — |
| [236876](https://encheres-domaine.gouv.fr/lot/69b0878827b74.html) | KIA SPORTAGE | `vl` | `absence de cle` | …, 1ère mise en circulation 31/03/2014, km inconnu,06 cv, 05 places, véhicule fermé à clé, absence de clé, absence de certificat d'immatriculation. Les visites se feront uniquement le vendredi 21… |
| [238225](https://encheres-domaine.gouv.fr/lot/69b13e8cdf47c.html) | OPEL MOVANO | `vu` | `absence de cle` | …rie W0LMRFCRAFB076243, 1ère mise en circulation 31/12/2015, km inconnu, véhicule fermé et absence de clé,on garantis, feu AR G cassé, absence de certificat d'immatriculation. Les visites se fero… |
| [245486](https://encheres-domaine.gouv.fr/lot/69c26186d750c.html) | PEUGEOT 208 | `vl` | *(attribut)* | — |
| [279157](https://encheres-domaine.gouv.fr/lot/6a0b1157e4b9c.html) | PEUGEOT 208 | `vl` | `sans cle` | …en circulation 12/02/2021, 07 cv, 05 places, km non relevé, véhicule ouvert avec 1 clé , sans clé, absence de certificat d'immatriculation. Les visites se feront uniquement le vendredi 21… |
| [296221](https://encheres-domaine.gouv.fr/lot/6a285953bcffd.html) | VOLVO XC 60 | `vl` | `absence de cle` | …rie YV1DZA8CDH2122878, 1ère mise en circulation 29/09/2017, km inconnu, véhicule fermé et absence de clé, absence de certificat d'immatriculation. Les visites se feront uniquement le vendredi 21… |
| [334132](https://encheres-domaine.gouv.fr/lot/6a749a33726a7.html) | VOLKSWAGEN GOLF | `vl` | *(attribut)* | — |
| [339354](https://encheres-domaine.gouv.fr/lot/6a80ff95e3587.html) | NISSAN QASHQAI | `vl` | `absence de cle` | …J11U2778552, 1ère mise en circulation 30/09/2020, 08cv , 05 places, véhicule fermé à clé, absence de clé, km inconnu, vitre arrière cassée, pare brise fêlé, nombreuses rayures et chocs divers de… |
| [336633](https://encheres-domaine.gouv.fr/lot/broyeurduratech-1.html) | Broyeur DURATECH | `engin` ⚠️ | *(attribut)* | — |
| [336636](https://encheres-domaine.gouv.fr/lot/broyeur-1-doo-3.html) | Broyeur | `engin` ⚠️ | *(attribut)* | — |
| [336641](https://encheres-domaine.gouv.fr/lot/cribleurrotatifmenarttr1535-1.html) | Cribleur Rotatif Ménart TR1535 | `engin` ⚠️ | *(attribut)* | — |
| [336650](https://encheres-domaine.gouv.fr/lot/chargeurtelescopique-1.html) | Chargeur telescopique | `engin` ⚠️ | *(attribut)* | — |
| [288940](https://encheres-domaine.gouv.fr/lot/renaultfurgon963pvl75-1.html) | RENAULT Kangoo | `vu` | *(attribut)* | — |
| [332335](https://encheres-domaine.gouv.fr/lot/bmwx63-0d285ch-1.html) | BMW X6 | `vl` | *(attribut)* | — |
| [327797](https://encheres-domaine.gouv.fr/lot/autocarmercedesintouro-1-doo-11.html) | Car MERCEDES-BENZ Intouro ME | `pl` | `sans cle` | …GT, type MBU ME 926, n° de série WEB63325213255051, 498095 km non garantis au 10/04/2025. Sans clé. Climatisation intégrale. Élévateur UFR. Carte grise 64 places, 59 places assises, 23 pla… |
| [316238](https://encheres-domaine.gouv.fr/lot/alfa-romeo-147.html) | ALFA ROMEO 147 | `vl` | *(attribut)* | — |

## Bilan

- **4 lot(s) mal attribué(s)** sur les 30 audités :
  ce sont des engins non immatriculables, désormais rangés en
  `hors_categorie_vehicule`.
- **16 lot(s)** ont déclenché sur un **attribut structuré** de la
  fiche, pas sur du texte : ces verdicts-là ne sont pas discutables.
- **14 lot(s)** ont déclenché sur une expression.

À valider à la main : ces derniers, quand l'extrait ne justifie pas
l'écartement.
