"""Configuration : validee au demarrage, jamais en cours de route.

Une erreur de configuration doit faire echouer immediatement avec un message
explicite. Un scan silencieusement vide est le pire resultat possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sleeper.config import Configuration, charger_configuration
from sleeper.errors import ConfigurationError

MINIMALE = """
[reseau]
user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"

[perimetre]
departements = ["59", "62"]

[sortie]
repertoire = "var/sorties"

[etat]
base = "var/etat/sleeper.sqlite3"
"""


def ecrire(tmp_path: Path, contenu: str) -> Path:
    chemin = tmp_path / "config.toml"
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


class TestChargement:
    def test_charge_une_configuration_minimale_et_applique_les_defauts(
        self, tmp_path: Path
    ) -> None:
        config = charger_configuration(ecrire(tmp_path, MINIMALE))
        assert isinstance(config, Configuration)
        assert config.perimetre.departements == frozenset({"59", "62"})
        assert config.reseau.concurrence_max == 2
        assert config.reseau.tentatives_max >= 1

    def test_le_navigateur_nest_pas_headless_par_defaut(self, tmp_path: Path) -> None:
        """Garde-fou : en headless, Chromium s'annonce « HeadlessChrome » et le
        pare-feu du site sert un CAPTCHA. Ce defaut ne doit pas etre inverse
        par megarde."""
        defaut = charger_configuration(ecrire(tmp_path, MINIMALE))
        livree = charger_configuration(Path("config/default.toml"))
        assert defaut.reseau.navigateur_headless is False
        assert livree.reseau.navigateur_headless is False

    def test_le_fichier_livre_avec_le_projet_est_valide(self) -> None:
        config = charger_configuration(Path("config/default.toml"))
        assert "59" in config.perimetre.departements
        assert config.perimetre.pays_etrangers >= frozenset({"BE", "LU"})

    def test_fichier_absent_echoue_avec_le_chemin(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="introuvable"):
            charger_configuration(tmp_path / "nexiste_pas.toml")

    def test_toml_malforme_echoue_explicitement(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="TOML"):
            charger_configuration(ecrire(tmp_path, "[reseau\nuser_agent = "))


class TestValidation:
    def test_perimetre_vide_est_refuse(self, tmp_path: Path) -> None:
        contenu = MINIMALE.replace('departements = ["59", "62"]', "departements = []")
        with pytest.raises(ConfigurationError, match="departements"):
            charger_configuration(ecrire(tmp_path, contenu))

    def test_departement_invalide_est_refuse(self, tmp_path: Path) -> None:
        contenu = MINIMALE.replace('["59", "62"]', '["59", "ZZZZ"]')
        with pytest.raises(ConfigurationError, match="ZZZZ"):
            charger_configuration(ecrire(tmp_path, contenu))

    def test_concurrence_excessive_est_refusee(self, tmp_path: Path) -> None:
        contenu = MINIMALE + "\nconcurrence_max = 32\n"
        contenu = MINIMALE.replace("[perimetre]", "concurrence_max = 32\n\n[perimetre]")
        with pytest.raises(ConfigurationError, match="concurrence_max"):
            charger_configuration(ecrire(tmp_path, contenu))

    def test_delai_trop_court_est_refuse_par_politesse(self, tmp_path: Path) -> None:
        contenu = MINIMALE.replace("[perimetre]", "delai_entre_requetes_s = 0.0\n\n[perimetre]")
        with pytest.raises(ConfigurationError, match="delai_entre_requetes_s"):
            charger_configuration(ecrire(tmp_path, contenu))

    def test_user_agent_anonyme_est_refuse(self, tmp_path: Path) -> None:
        contenu = MINIMALE.replace(
            'user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"',
            'user_agent = "Mozilla/5.0"',
        )
        with pytest.raises(ConfigurationError, match="identifiable"):
            charger_configuration(ecrire(tmp_path, contenu))

    def test_section_inconnue_est_refusee(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="section_fantome"):
            charger_configuration(ecrire(tmp_path, MINIMALE + "\n[section_fantome]\nx = 1\n"))

    def test_regle_dexclusion_inconnue_est_refusee(self, tmp_path: Path) -> None:
        contenu = MINIMALE + '\n[exclusions]\nregles_actives = ["regle_fantome"]\n'
        with pytest.raises(ConfigurationError, match="regle_fantome"):
            charger_configuration(ecrire(tmp_path, contenu))


class TestDerivations:
    def test_construit_le_perimetre_du_domaine(self, tmp_path: Path) -> None:
        config = charger_configuration(ecrire(tmp_path, MINIMALE))
        assert config.perimetre_domaine().contient("59000", "LILLE") is True
        assert config.perimetre_domaine().contient("13001", "MARSEILLE") is False

    def test_construit_le_moteur_dexclusions_avec_les_ajouts(self, tmp_path: Path) -> None:
        contenu = MINIMALE + (
            "\n[exclusions.formulations_supplementaires]\n"
            'moteur_hors_service = ["bloc moteur fendu"]\n'
        )
        moteur = charger_configuration(ecrire(tmp_path, contenu)).moteur_exclusions()
        expressions = {e for r in moteur.regles for e in r.expressions}
        assert "bloc moteur fendu" in expressions

    def test_restreindre_les_regles_actives_reduit_le_moteur(self, tmp_path: Path) -> None:
        contenu = MINIMALE + '\n[exclusions]\nregles_actives = ["sans_cle"]\n'
        moteur = charger_configuration(ecrire(tmp_path, contenu)).moteur_exclusions()
        assert [r.code for r in moteur.regles] == ["sans_cle"]
