"""The personal-data guard must not cry wolf on vehicle serial numbers.

It blocked a legitimate fixture by reading every VIN as an IBAN.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from check_no_personal_data import (
    ALLOWED,
    FORBIDDEN_NAMES,
    PATTERNS,
    _is_reserved,
    tracked_files,
)


class TestIbanPattern:
    @pytest.mark.parametrize(
        "value",
        [
            # Structure d'un IBAN français, valeur inventée : ce fichier ne
            # doit contenir aucune donnée réelle, c'est tout son objet.
            "FR7600000000000000000000000",
            "DE89370400440532013000",
        ],
    )
    def test_detects_a_real_iban(self, value: str) -> None:
        assert PATTERNS["IBAN"].search(value)

    @pytest.mark.parametrize(
        "vin",
        [
            "VF15R7A0H48421954",
            "VF7VAYHVKKZ078443",  # le doublon constaté dans la vente 467
            "WF0FXXTTRFMU20040",  # le Ford Transit 329644
        ],
    )
    def test_does_not_mistake_a_vin_for_an_iban(self, vin: str) -> None:
        assert not PATTERNS["IBAN"].search(vin)


class TestAllowList:
    """Les valeurs légitimes du dépôt : contacts du projet et valeurs inventées."""

    def test_the_project_contacts_are_allowed(self) -> None:
        assert "contact@exemple.fr" in ALLOWED

    def test_the_synthetic_test_values_are_allowed(self) -> None:
        assert {"06-00-00-00-00", "FR7600000000000000000000000"} <= ALLOWED


class TestReservedDomains:
    """Une adresse à un domaine réservé ne désigne personne : rien à fuiter."""

    @pytest.mark.parametrize(
        "adresse",
        [
            "x@y.iam.example",
            "quelquun@example.com",
            "a@sous.domaine.example.org",
            "essai@machine.invalid",
            "root@localhost",
            "MAJUSCULE@EXAMPLE.NET",
        ],
    )
    def test_a_reserved_address_is_not_a_leak(self, adresse: str) -> None:
        assert _is_reserved(adresse)

    @pytest.mark.parametrize(
        "adresse",
        [
            "nom.invente@fournisseur-imaginaire.fr",
            "contact@exemple.fr",
            "agent@ministere-invente.gouv.fr",
            "piege@example.org.attaquant.fr",
        ],
    )
    def test_a_real_address_is_still_a_leak(self, adresse: str) -> None:
        """« example » ailleurs qu'en domaine de tête ne protège rien."""
        assert not _is_reserved(adresse)


class TestOtherPatterns:
    def test_detects_an_email(self) -> None:
        assert PATTERNS["courriel"].search("prenom.nom@exemple.gouv.fr")

    def test_it_scans_every_tracked_file_not_only_the_fixtures(self) -> None:
        """La faille originelle : de vrais numéros ont atteint tests/ sans être vus."""
        suivis = tracked_files()
        assert suivis, "le garde-fou doit voir les fichiers versionnés"
        # git ls-files rend des chemins POSIX ; sous Windows, str(Path(...))
        # les rendrait avec des antislashs.
        assert any(f.as_posix().startswith("tests/") for f in suivis)

    @pytest.mark.parametrize("phone", ["06-00-00-00-00", "06 00 00 00 00", "0600000000"])
    def test_detects_a_phone_number(self, phone: str) -> None:
        assert PATTERNS["téléphone"].search(phone)

    def test_does_not_flag_a_mileage(self) -> None:
        assert not PATTERNS["téléphone"].search("110430 km")


class TestForbiddenFileNames:
    """Un compte de service donne l'écriture sur le Drive de quelqu'un."""

    @pytest.mark.parametrize(
        "name",
        [
            "config/drive-service-account.json",
            "config/service_account.json",
            "secrets/credentials.json",
            "keys/deploy.pem",
            "keys/private.key",
            "certs/client.p12",
        ],
    )
    def test_a_secret_file_name_is_refused(self, name: str) -> None:
        assert FORBIDDEN_NAMES.search(name)

    @pytest.mark.parametrize(
        "name",
        [
            "config/default.toml",
            "tests/fixtures/api/auctions_list_page1.json",
            "src/sleeper/output/drive.py",
            "schemas/sortie-2.0.json",
        ],
    )
    def test_an_ordinary_file_passes(self, name: str) -> None:
        assert not FORBIDDEN_NAMES.search(name)
