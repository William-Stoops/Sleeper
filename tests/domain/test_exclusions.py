"""Regles d'exclusion metier.

Chaque regle est couverte par de vraies formulations. Les agents du Domaine
ecrivent librement : on teste donc les variantes, mais aussi les tournures
voisines qui ne doivent PAS declencher.
"""

from __future__ import annotations

import pytest

from sleeper.domain.exclusions import REGLES_PAR_DEFAUT, MoteurExclusions, SignalLot


def signal(
    description: str = "",
    *,
    kilometrage: int | None = None,
    a_une_cle: bool | None = None,
    certificat_immatriculation: bool | None = None,
    genre: str | None = None,
    annee_mise_en_circulation: int | None = None,
    vhu_declare: bool | None = None,
    immatriculable_a_nouveau: bool | None = None,
    non_conforme: bool | None = None,
) -> SignalLot:
    """Construit un signal de lot minimal, tout le reste etant inconnu."""
    return SignalLot(
        description=description,
        kilometrage=kilometrage,
        a_une_cle=a_une_cle,
        certificat_immatriculation=certificat_immatriculation,
        genre=genre,
        annee_mise_en_circulation=annee_mise_en_circulation,
        vhu_declare=vhu_declare,
        immatriculable_a_nouveau=immatriculable_a_nouveau,
        non_conforme=non_conforme,
    )


@pytest.fixture
def moteur() -> MoteurExclusions:
    return MoteurExclusions(REGLES_PAR_DEFAUT)


class TestKilometrageInconnu:
    @pytest.mark.parametrize(
        "description",
        [
            "DACIA DUSTER, Gazole, 06 cv, 05 places.",
            "kilométrage non renseigné",
            "compteur non fonctionnel, km inconnu",
        ],
    )
    def test_ecarte_quand_aucun_kilometrage_nest_lisible(
        self, moteur: MoteurExclusions, description: str
    ) -> None:
        assert moteur.motif(signal(description)) == "kilometrage_inconnu"

    def test_conserve_quand_lattribut_structure_le_porte(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("DACIA DUSTER", kilometrage=110430)) is None

    def test_conserve_quand_le_texte_le_porte(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("RENAULT Kangoo, 15500 km.")) is None

    def test_un_kilometrage_a_zero_nest_pas_un_kilometrage(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("DACIA DUSTER", kilometrage=0)) == "kilometrage_inconnu"


class TestSansCle:
    @pytest.mark.parametrize(
        "description",
        [
            "véhicule sans clé",
            "clé absente",
            "absence de clés",
            "pas de clef",
            "110000 km, sans clés",
        ],
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(description, kilometrage=1)) == "sans_cle"

    def test_attribut_structure_prime(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("120000 km", a_une_cle=False)) == "sans_cle"

    def test_mention_positive_ne_declenche_pas(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("Avec CG et clé, 120000 km", a_une_cle=True)) is None


class TestSansCertificatImmatriculation:
    @pytest.mark.parametrize(
        "description",
        [
            "véhicule sans carte grise",
            "CG absente",
            "absence de certificat d'immatriculation",
            "vendu sans certificat d'immatriculation",
            "pas de carte grise",
        ],
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "sans_certificat_immatriculation"

    def test_attribut_structure_prime(self, moteur: MoteurExclusions) -> None:
        assert (
            moteur.motif(signal("90000 km", certificat_immatriculation=False))
            == "sans_certificat_immatriculation"
        )

    def test_mention_positive_ne_declenche_pas(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("Avec CG et clé, 90000 km")) is None


class TestNonRoulant:
    @pytest.mark.parametrize(
        "description",
        ["véhicule non roulant", "véhicule non-roulant", "ne roule pas", "état non roulant"],
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "non_roulant"

    def test_vehicule_roulant_ne_declenche_pas(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("véhicule roulant, 90000 km")) is None

    def test_non_immatriculable_a_nouveau_declenche(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("90000 km", immatriculable_a_nouveau=False)) == "non_roulant"


class TestEpaveOuPieces:
    @pytest.mark.parametrize(
        "description",
        ["épave", "vendu pour pièces", "vendu pour pieces détachées", "véhicule hors d'usage"],
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "epave_ou_pieces"

    def test_vhu_declare_declenche(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("90000 km", vhu_declare=True)) == "epave_ou_pieces"


class TestChocOuAccident:
    @pytest.mark.parametrize(
        "description",
        ["véhicule accidenté", "choc avant", "dégâts de carrosserie", "carrosserie endommagée"],
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "choc_ou_accident"

    @pytest.mark.parametrize(
        "description", ["sans choc apparent", "aucun dégât de carrosserie", "non accidenté"]
    )
    def test_les_tournures_negatives_nannulent_pas_a_tort(
        self, moteur: MoteurExclusions, description: str
    ) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) is None


class TestMoteurHorsService:
    @pytest.mark.parametrize(
        "description", ["moteur hors service", "moteur HS", "moteur cassé", "moteur à refaire"]
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "moteur_hors_service"


class TestGageOuOpposition:
    @pytest.mark.parametrize(
        "description", ["véhicule gagé", "gage en cours", "opposition sur le véhicule"]
    )
    def test_variantes(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "gage_ou_opposition"


class TestGenreHorsCible:
    @pytest.mark.parametrize("genre", ["MTL", "MTT1", "QM", "REM", "TRA"])
    def test_genre_de_carte_grise(self, moteur: MoteurExclusions, genre: str) -> None:
        assert moteur.motif(signal("90000 km", genre=genre)) == "genre_hors_cible"

    @pytest.mark.parametrize(
        "description",
        [
            "moto YAMAHA",
            "scooter PIAGGIO",
            "quad",
            "remorque plateau",
            "tracteur agricole",
            "voiture sans permis AIXAM",
        ],
    )
    def test_reperage_textuel(self, moteur: MoteurExclusions, description: str) -> None:
        assert moteur.motif(signal(f"{description}, 90000 km")) == "genre_hors_cible"

    def test_un_utilitaire_reste_dans_la_cible(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("Utilitaire RENAULT Kangoo, 15500 km", genre="CTTE")) is None


class TestCollection:
    def test_avant_1990_est_ecarte(self, moteur: MoteurExclusions) -> None:
        assert (
            moteur.motif(signal("90000 km", annee_mise_en_circulation=1972))
            == "collection_avant_1990"
        )

    def test_1990_est_conserve(self, moteur: MoteurExclusions) -> None:
        assert moteur.motif(signal("90000 km", annee_mise_en_circulation=1990)) is None


class TestOrdreEtExtensibilite:
    def test_le_premier_motif_declenche_gagne_et_il_est_deterministe(
        self, moteur: MoteurExclusions
    ) -> None:
        # Un lot cumulant plusieurs defauts doit toujours rendre le meme motif.
        cumul = signal("épave sans clé, moteur HS", kilometrage=1)
        assert moteur.motif(cumul) == moteur.motif(cumul) == "sans_cle"

    def test_une_formulation_ajoutee_par_configuration_est_prise_en_compte(self) -> None:
        etendu = MoteurExclusions.avec_ajouts(
            REGLES_PAR_DEFAUT, {"moteur_hors_service": ("bloc moteur fendu",)}
        )
        assert etendu.motif(signal("bloc moteur fendu, 90000 km")) == "moteur_hors_service"

    def test_une_regle_desactivee_ne_declenche_plus(self) -> None:
        sans_km = MoteurExclusions(
            tuple(r for r in REGLES_PAR_DEFAUT if r.code != "kilometrage_inconnu")
        )
        assert sans_km.motif(signal("DACIA DUSTER sans kilométrage")) is None

    def test_un_ajout_sur_une_regle_inconnue_est_une_erreur(self) -> None:
        with pytest.raises(KeyError, match="regle_fantome"):
            MoteurExclusions.avec_ajouts(REGLES_PAR_DEFAUT, {"regle_fantome": ("peu importe",)})
