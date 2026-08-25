"""Configuration: validated at startup, never along the way.

A configuration error must fail immediately with an explicit message. A
silently empty scan is the worst possible outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sleeper.config import Configuration, load_configuration
from sleeper.errors import ConfigurationError

MINIMAL = """
[reseau]
user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"

[perimetre]
departements = ["59", "62"]

[sortie]
repertoire = "var/sorties"

[etat]
base = "var/etat/sleeper.sqlite3"
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoading:
    def test_loads_a_minimal_configuration_and_applies_the_defaults(self, tmp_path: Path) -> None:
        config = load_configuration(write(tmp_path, MINIMAL))
        assert isinstance(config, Configuration)
        assert config.scope.departments == frozenset({"59", "62"})
        assert config.network.max_attempts >= 1

    def test_the_browser_is_not_headless_by_default(self, tmp_path: Path) -> None:
        """Guard rail: in headless mode Chromium announces "HeadlessChrome" and
        the site's firewall serves a CAPTCHA. This default must not be flipped
        by accident."""
        default = load_configuration(write(tmp_path, MINIMAL))
        shipped = load_configuration(Path("config/default.toml"))
        assert default.network.headless_browser is False
        assert shipped.network.headless_browser is False

    def test_the_file_shipped_with_the_project_is_valid(self) -> None:
        config = load_configuration(Path("config/default.toml"))
        assert "59" in config.scope.departments
        assert config.scope.foreign_countries >= frozenset({"BE", "LU"})

    def test_a_missing_file_fails_with_its_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="introuvable"):
            load_configuration(tmp_path / "nexiste_pas.toml")

    def test_malformed_toml_fails_explicitly(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="TOML"):
            load_configuration(write(tmp_path, "[reseau\nuser_agent = "))


class TestValidation:
    def test_an_empty_scope_is_refused(self, tmp_path: Path) -> None:
        content = MINIMAL.replace('departements = ["59", "62"]', "departements = []")
        with pytest.raises(ConfigurationError, match="departements"):
            load_configuration(write(tmp_path, content))

    def test_an_invalid_department_is_refused(self, tmp_path: Path) -> None:
        content = MINIMAL.replace('["59", "62"]', '["59", "ZZZZ"]')
        with pytest.raises(ConfigurationError, match="ZZZZ"):
            load_configuration(write(tmp_path, content))

    def test_an_unknown_network_setting_is_refused(self, tmp_path: Path) -> None:
        # Notably `concurrence_max`, removed once requests became sequential:
        # a stale setting must fail rather than be silently ignored.
        content = MINIMAL.replace("[perimetre]", "concurrence_max = 2\n\n[perimetre]")
        with pytest.raises(ConfigurationError, match="concurrence_max"):
            load_configuration(write(tmp_path, content))

    def test_too_short_a_delay_is_refused_out_of_politeness(self, tmp_path: Path) -> None:
        content = MINIMAL.replace("[perimetre]", "delai_entre_requetes_s = 0.0\n\n[perimetre]")
        with pytest.raises(ConfigurationError, match="delai_entre_requetes_s"):
            load_configuration(write(tmp_path, content))

    def test_an_anonymous_user_agent_is_refused(self, tmp_path: Path) -> None:
        content = MINIMAL.replace(
            'user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"',
            'user_agent = "Mozilla/5.0"',
        )
        with pytest.raises(ConfigurationError, match="identifiable"):
            load_configuration(write(tmp_path, content))

    def test_an_unknown_section_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="section_fantome"):
            load_configuration(write(tmp_path, MINIMAL + "\n[section_fantome]\nx = 1\n"))

    def test_an_unknown_exclusion_rule_is_refused(self, tmp_path: Path) -> None:
        content = MINIMAL + '\n[exclusions]\nregles_actives = ["regle_fantome"]\n'
        with pytest.raises(ConfigurationError, match="regle_fantome"):
            load_configuration(write(tmp_path, content))


class TestDerivations:
    def test_builds_the_domain_perimeter(self, tmp_path: Path) -> None:
        config = load_configuration(write(tmp_path, MINIMAL))
        assert config.perimeter().status("59000", "LILLE") == "dans"
        assert config.perimeter().status("13001", "MARSEILLE") == "hors"
        assert config.perimeter().status("", "") == "inconnu"

    def test_builds_the_exclusion_engine_with_the_extra_phrases(self, tmp_path: Path) -> None:
        content = MINIMAL + (
            "\n[exclusions.formulations_supplementaires]\n"
            'moteur_hors_service = ["bloc moteur fendu"]\n'
        )
        engine = load_configuration(write(tmp_path, content)).exclusion_engine()
        phrases = {p for rule in engine.rules for p in rule.phrases}
        assert "bloc moteur fendu" in phrases

    def test_restricting_the_active_rules_shrinks_the_engine(self, tmp_path: Path) -> None:
        content = MINIMAL + '\n[exclusions]\nregles_actives = ["sans_cle"]\n'
        engine = load_configuration(write(tmp_path, content)).exclusion_engine()
        assert [rule.code for rule in engine.rules] == ["sans_cle"]


class TestFrenchWireFormat:
    def test_the_toml_keys_stay_the_documented_french_ones(self, tmp_path: Path) -> None:
        """Identifiers are English; the configuration file is a user interface."""
        config = load_configuration(write(tmp_path, MINIMAL))
        # The French keys of the file feed the English attributes.
        assert config.network.user_agent.startswith("SleeperBot/")
        assert config.output.directory == Path("var/sorties")
        assert config.state.database == Path("var/etat/sleeper.sqlite3")


class TestWindowsPaths:
    """Un chemin Windows entre guillemets casse le TOML, et le message doit le dire.

    « C:\\Users\\... » déclenche « Invalid hex value » : TOML lit « \\U » comme
    une séquence d'échappement. Le message brut n'en dit rien, et le correctif
    tient en un caractère.
    """

    def test_a_backslash_path_fails_with_guidance(self, tmp_path: Path) -> None:
        content = MINIMAL.replace(
            'repertoire = "var/sorties"', 'repertoire = "C:\\Users\\moi\\sorties"'
        )
        with pytest.raises(ConfigurationError, match="Chemin Windows"):
            load_configuration(write(tmp_path, content))

    def test_forward_slashes_are_accepted(self, tmp_path: Path) -> None:
        content = MINIMAL.replace(
            'repertoire = "var/sorties"', 'repertoire = "C:/Users/moi/sorties"'
        )
        assert load_configuration(write(tmp_path, content)).output.directory.parts

    def test_a_literal_string_is_accepted(self, tmp_path: Path) -> None:
        content = MINIMAL.replace(
            'repertoire = "var/sorties"', "repertoire = 'C:\\Users\\moi\\sorties'"
        )
        assert load_configuration(write(tmp_path, content)).output.directory.parts

    def test_an_ordinary_syntax_error_gets_no_windows_hint(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="TOML") as caught:
            load_configuration(write(tmp_path, "[reseau\nuser_agent = "))
        assert "Chemin Windows" not in str(caught.value)
