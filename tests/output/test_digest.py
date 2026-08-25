"""Digest Markdown : lisible, et honnête sur ce qui a rate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sleeper.domain.models import DocumentSortie, ErreurRun, Lot, LotEcarte, Run
from sleeper.output.digest import LIMITE_PAR_SECTION, rediger


def lot(**remplacements: Any) -> Lot:
    base: dict[str, Any] = {
        "id": "267804",
        "url": "https://exemple/lot/1",
        "vente_id": "467",
        "numero": "1",
        "titre": "DACIA DUSTER",
        "categorie": "Véhicules",
        "reserve_aux_professionnels": True,
        "marque": "DACIA",
        "modele": "DUSTER",
        "version": "",
        "premiere_mise_en_circulation": "2015-12-23",
        "kilometrage": 110430,
        "energie": "Gazole",
        "boite": "Boîte manuelle",
        "puissance_fiscale": 6,
        "vin": "",
        "crit_air": "",
        "controle_technique": "",
        "carte_grise": True,
        "cles": True,
        "etat_declare": "",
        "mise_a_prix": 1500.0,
        "enchere_en_cours": None,
        "nb_encherisseurs": None,
        "lieu_retrait": "LILLE",
        "code_postal": "59000",
        "departement": "59",
        "dates_visite": "",
        "frais_acheteur_pct": None,
        "tva_recuperable": None,
        "description_integrale": "",
        "hors_perimetre": False,
        "nouveau_depuis_dernier_run": False,
        "enchere_a_bouge": False,
        "champs_manquants": [],
    }
    base.update(remplacements)
    return Lot(**base)


def doc(
    lots: list[Lot], ecartes: list[LotEcarte] | None = None, erreurs: list[ErreurRun] | None = None
) -> DocumentSortie:
    return DocumentSortie(
        run=Run(
            horodatage=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duree_secondes=42.0,
            ventes_scannees=2,
            lots_vus=len(lots),
            lots_retenus=len(lots),
            lots_ecartes=len(ecartes or []),
            erreurs=erreurs or [],
        ),
        ventes=[],
        lots=lots,
        ecartes=ecartes or [],
    )


class TestStructure:
    def test_contient_les_quatre_sections_attendues(self) -> None:
        rendu = rediger(doc([lot()]))
        for titre in (
            "Nouveaux lots",
            "Enchères qui ont bougé",
            "Réservés aux professionnels",
            "Erreurs du run",
        ):
            assert titre in rendu

    def test_entete_reprend_les_compteurs(self) -> None:
        rendu = rediger(doc([lot(), lot(id="2")]))
        assert "2 vente(s) balayée(s)" in rendu
        assert "**2 retenu(s)**" in rendu

    def test_un_run_vide_le_dit_au_lieu_de_mentir(self) -> None:
        rendu = rediger(doc([]))
        assert "aucun nouveau lot depuis le dernier run" in rendu
        assert "run sans erreur" in rendu


class TestContenu:
    def test_les_nouveaux_lots_sont_isoles(self) -> None:
        rendu = rediger(
            doc(
                [
                    lot(id="1", titre="NEUF", nouveau_depuis_dernier_run=True),
                    lot(id="2", titre="CONNU"),
                ]
            )
        )
        section = rendu.split("## Nouveaux lots")[1].split("##")[0]
        assert "NEUF" in section
        assert "CONNU" not in section

    def test_les_encheres_qui_bougent_sont_isolees(self) -> None:
        rendu = rediger(
            doc([lot(id="1", titre="MONTE", enchere_a_bouge=True, enchere_en_cours=2000.0)])
        )
        section = rendu.split("## Enchères qui ont bougé")[1].split("##")[0]
        assert "MONTE" in section
        assert "2 000 €" in section

    def test_le_hors_perimetre_est_signale(self) -> None:
        assert "*hors périmètre*" in rediger(doc([lot(hors_perimetre=True)]))

    @pytest.mark.parametrize(
        ("valeur", "attendu"), [(True, "**PRO**"), (False, "tous publics"), (None, "⚠️ inconnu")]
    )
    def test_mention_professionnels(self, valeur: bool | None, attendu: str) -> None:
        # Le lot est marque « nouveau » pour qu'il figure dans un tableau :
        # un lot ni nouveau, ni en mouvement, ni pro n'a rien a faire dans le
        # digest, le JSON restant la source complete.
        incomplet = ["reserve_aux_professionnels"] if valeur is None else []
        rendu = rediger(
            doc(
                [
                    lot(
                        reserve_aux_professionnels=valeur,
                        nouveau_depuis_dernier_run=True,
                        champs_manquants=incomplet,
                    )
                ]
            )
        )
        assert attendu in rendu

    def test_les_motifs_decartement_sont_comptes(self) -> None:
        ecartes = [
            LotEcarte(id="1", url="u", titre="t", motif="sans_cle"),
            LotEcarte(id="2", url="u", titre="t", motif="sans_cle"),
            LotEcarte(id="3", url="u", titre="t", motif="epave_ou_pieces"),
        ]
        rendu = rediger(doc([], ecartes))
        assert "| sans_cle | 2 |" in rendu
        assert "| epave_ou_pieces | 1 |" in rendu

    def test_les_erreurs_sont_affichees_et_non_masquees(self) -> None:
        erreurs = [
            ErreurRun(
                etape="lots",
                cible="vente 467",
                type="SchemaAmontError",
                message="champ professional_only absent",
            )
        ]
        rendu = rediger(doc([], erreurs=erreurs))
        assert "professional_only absent" in rendu
        assert "run sans erreur" not in rendu


class TestAlerteIncompletude:
    def test_un_lot_sans_mention_pro_declenche_un_avertissement_en_tete(self) -> None:
        incomplet = lot(
            reserve_aux_professionnels=None, champs_manquants=["reserve_aux_professionnels"]
        )
        rendu = rediger(doc([incomplet]))
        assert "lot(s) incomplet(s)" in rendu
        assert rendu.index("incomplet") < rendu.index("## Nouveaux lots")

    def test_les_lots_incomplets_ont_leur_propre_tableau(self) -> None:
        incomplet = lot(
            titre="A VERIFIER",
            reserve_aux_professionnels=None,
            champs_manquants=["reserve_aux_professionnels"],
        )
        rendu = rediger(doc([incomplet, lot(id="2", titre="COMPLET")]))
        section = rendu.split("## Lots incomplets")[1].split("##")[0]
        assert "A VERIFIER" in section
        assert "COMPLET" not in section

    def test_aucun_avertissement_quand_tout_est_lu(self) -> None:
        assert "incomplet" not in rediger(doc([lot()]))


class TestVolume:
    def test_les_longues_listes_sont_tronquees_en_le_disant(self) -> None:
        lots = [
            lot(id=str(i), nouveau_depuis_dernier_run=True) for i in range(LIMITE_PAR_SECTION + 5)
        ]
        assert "… et 5 autres" in rediger(doc(lots))
