"""Body-damage classification.

Correctif 2: on Domaine sales, nearly every description mentions a knock.
"Coups, chocs, rayures et frottements d'usage" is boilerplate. Treating that
as grounds for exclusion throws away the seam.

Classification therefore never excludes: it feeds the repair budget and the
score. The wordings below are taken verbatim from the run of 2026-08-25.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sleeper.domain.damage import classify_damage

REAL = json.loads(
    (Path(__file__).parent.parent / "fixtures/reel/run-2026-08-25.json").read_text(encoding="utf-8")
)


class TestNoDamage:
    @pytest.mark.parametrize(
        "description",
        ["DACIA DUSTER, Gazole, 06 cv, 05 places.", "Très bon état général", ""],
    )
    def test_a_clean_description_declares_none(self, description: str) -> None:
        assert classify_damage(description) == "aucun"


class TestWearAndTear:
    @pytest.mark.parametrize(
        "description",
        [
            "Coups, chocs, rayures et frottements d'usage",
            "coups, chocs, rayures et frottements d'usage sur la carrosserie",
            "éclats de peinture",
            "rayures sur les portes",
            "frottements d'usage",
        ],
    )
    def test_administrative_boilerplate_is_only_wear(self, description: str) -> None:
        assert classify_damage(description) == "usage"


class TestCosmetic:
    @pytest.mark.parametrize(
        "description",
        [
            "choc sur l'aile avant droite",
            "enfoncement portière arrière",
            "bouclier arrière abîmé",
            "pare-chocs enfoncé",
            "hayon enfoncé",
            "capot déformé par un choc",
            "frottement sur le bas de caisse",
            "rétroviseur cassé",
        ],
    )
    def test_a_named_panel_is_cosmetic(self, description: str) -> None:
        assert classify_damage(description) == "cosmetique"


class TestStructural:
    @pytest.mark.parametrize(
        "description",
        [
            "traverse avant enfoncée",
            "longeron déformé",
            "berceau abîmé",
            "châssis tordu",
            "montant plié",
            "pavillon percé",
            "toit percé",
            "corrosion importante",
            "véhicule grêlé",
            "déformation de la structure",
        ],
    )
    def test_structural_wording_is_structural(self, description: str) -> None:
        assert classify_damage(description) == "structurel"


class TestSeverityWins:
    def test_the_worst_level_present_is_the_verdict(self) -> None:
        mixed = "rayures d'usage, choc sur l'aile, et corrosion du longeron"
        assert classify_damage(mixed) == "structurel"

    def test_cosmetic_beats_wear(self) -> None:
        assert classify_damage("éclats de peinture et choc sur la portière") == "cosmetique"


class TestTheFordTransit:
    """Lot 329644 — the best file of the run, and it must never be excluded."""

    DESCRIPTION = json.loads(REAL["ford_transit_329644"])["description_integrale"]

    def test_it_is_classified_not_excluded(self) -> None:
        assert classify_damage(self.DESCRIPTION) in {"cosmetique", "structurel"}

    def test_its_multiple_knocks_are_seen(self) -> None:
        # « mécanique et carrosserie à revoir […] choc AR, état général dégradé,
        # multiples chocs et impacts sur carrosserie »
        assert "choc" in self.DESCRIPTION.lower()
        assert classify_damage(self.DESCRIPTION) != "aucun"


class TestRealDescriptions:
    """Every damaged lot of the real run gets a level, and none of them raises."""

    def test_all_real_descriptions_classify(self) -> None:
        levels = {
            lot_id: classify_damage(text)
            for lot_id, text in REAL["descriptions_avec_dommages"].items()
        }
        assert levels
        assert set(levels.values()) <= {"aucun", "usage", "cosmetique", "structurel"}

    def test_the_boilerplate_does_not_dominate_the_corpus(self) -> None:
        """If everything came out structural, the rule would be useless."""
        levels = [classify_damage(t) for t in REAL["descriptions_avec_dommages"].values()]
        assert levels.count("structurel") < len(levels)


class TestSeriousCrashWordings:
    """Relevé en production : ces formulations ressortaient sans dommage.

    Le Renault Master 308717 — « Véhicule accidenté AVG (aile, roue, optiques,
    triangle etc), dégâts non expertisés. Airbag déclenché. » — était écarté
    par l'ancienne règle et classé « aucun » par la première version de
    celle-ci. Les deux verdicts étaient faux.
    """

    MASTER = (
        "RENAULT Master III 2.3 Dci S&S 110, 3 places, Gazole, 153184 km. "
        "Véhicule accidenté AVG (aile, roue, optiques, triangle etc), dégâts non "
        "expertisés. Airbag déclenché. État mécanique inconnu."
    )

    def test_a_deployed_airbag_is_structural(self) -> None:
        assert classify_damage(self.MASTER) == "structurel"

    @pytest.mark.parametrize(
        "description",
        ["véhicule accidenté", "véhicule sinistré", "dégâts non expertisés"],
    )
    def test_crash_wordings_are_never_no_damage(self, description: str) -> None:
        assert classify_damage(description) != "aucun"

    def test_every_lot_the_old_rule_excluded_now_carries_damage(self) -> None:
        """Aucun des dix ne doit ressortir « aucun » : la règle les voyait bien."""
        niveaux = {
            lot_id: classify_damage(lot["description"])
            for lot_id, lot in REAL["choc_reclasses"].items()
        }
        assert niveaux
        assert "aucun" not in niveaux.values(), niveaux
