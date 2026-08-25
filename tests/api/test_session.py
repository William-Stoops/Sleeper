"""Cache et renouvellement de session. Aucun navigateur n'est lance ici."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sleeper.api.session import COOKIE_REQUIS, Session, SessionNavigateur
from sleeper.config import Reseau
from sleeper.errors import SessionError

DEBUT = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)


class Horloge:
    def __init__(self) -> None:
        self.instant = DEBUT

    def __call__(self) -> datetime:
        return self.instant

    def avancer(self, minutes: int) -> None:
        self.instant += timedelta(minutes=minutes)


@pytest.fixture
def reseau() -> Reseau:
    return Reseau(user_agent="SleeperBot/0.1 (+mailto:test@example.org)", session_ttl_minutes=45)


def acquereur(
    compteur: list[int], cookies: Mapping[str, str] | None = None
) -> Callable[[Reseau], Session]:
    """Faux acquereur de session : compte les ouvertures de « navigateur »."""
    charge = dict(cookies or {COOKIE_REQUIS: "jeton", "PHPSESSID": "abc"})

    def _acquerir(_: Reseau) -> Session:
        compteur.append(1)
        return Session(
            cookies={**charge, "PHPSESSID": f"abc{len(compteur)}"},
            user_agent="Mozilla/5.0 (essai) Chrome/140",
        )

    return _acquerir


class TestAcquisition:
    def test_ouvre_un_navigateur_au_premier_appel(self, reseau: Reseau, tmp_path: Path) -> None:
        appels: list[int] = []
        session = SessionNavigateur(reseau, tmp_path / "s.json", acquereur(appels), Horloge())
        assert COOKIE_REQUIS in session.session().cookies
        assert len(appels) == 1

    def test_ne_reouvre_pas_tant_que_la_session_est_fraiche(
        self, reseau: Reseau, tmp_path: Path
    ) -> None:
        appels: list[int] = []
        horloge = Horloge()
        session = SessionNavigateur(reseau, tmp_path / "s.json", acquereur(appels), horloge)
        session.session()
        horloge.avancer(44)
        session.session()
        assert len(appels) == 1

    def test_renouvelle_a_lexpiration(self, reseau: Reseau, tmp_path: Path) -> None:
        appels: list[int] = []
        horloge = Horloge()
        session = SessionNavigateur(reseau, tmp_path / "s.json", acquereur(appels), horloge)
        session.session()
        horloge.avancer(46)
        session.session()
        assert len(appels) == 2

    def test_cookie_requis_absent_est_une_erreur_explicite(
        self, reseau: Reseau, tmp_path: Path
    ) -> None:
        def sans_cookie(_: Reseau) -> Session:
            return Session(cookies={"PHPSESSID": "abc"}, user_agent="Chrome/140")

        session = SessionNavigateur(reseau, tmp_path / "s.json", sans_cookie, Horloge())
        with pytest.raises(SessionError, match=COOKIE_REQUIS):
            session.session()


class TestCacheDisque:
    def test_une_seconde_instance_reutilise_le_cache(self, reseau: Reseau, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        appels: list[int] = []
        horloge = Horloge()
        SessionNavigateur(reseau, cache, acquereur(appels), horloge).session()
        SessionNavigateur(reseau, cache, acquereur(appels), horloge).session()
        assert len(appels) == 1

    def test_le_cache_est_illisible_par_les_autres(self, reseau: Reseau, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        SessionNavigateur(reseau, cache, acquereur([]), Horloge()).session()
        assert cache.stat().st_mode & 0o077 == 0

    def test_un_cache_perime_est_ignore(self, reseau: Reseau, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        appels: list[int] = []
        horloge = Horloge()
        SessionNavigateur(reseau, cache, acquereur(appels), horloge).session()
        horloge.avancer(60)
        SessionNavigateur(reseau, cache, acquereur(appels), horloge).session()
        assert len(appels) == 2

    @pytest.mark.parametrize(
        "contenu", ["{ pas du json", json.dumps({"cookies": {}}), json.dumps({"obtenus_a": "hier"})]
    )
    def test_un_cache_corrompu_est_ignore_sans_planter(
        self, reseau: Reseau, tmp_path: Path, contenu: str
    ) -> None:
        cache = tmp_path / "s.json"
        cache.write_text(contenu, encoding="utf-8")
        appels: list[int] = []
        session = SessionNavigateur(reseau, cache, acquereur(appels), Horloge())
        assert COOKIE_REQUIS in session.session().cookies
        assert len(appels) == 1

    def test_renouveler_force_une_nouvelle_acquisition(
        self, reseau: Reseau, tmp_path: Path
    ) -> None:
        appels: list[int] = []
        session = SessionNavigateur(reseau, tmp_path / "s.json", acquereur(appels), Horloge())
        premiers = dict(session.session().cookies)
        seconds = dict(session.renouveler().cookies)
        assert len(appels) == 2
        assert premiers["PHPSESSID"] != seconds["PHPSESSID"]


class TestUserAgent:
    def test_la_session_transporte_le_user_agent_du_navigateur(
        self, reseau: Reseau, tmp_path: Path
    ) -> None:
        session = SessionNavigateur(reseau, tmp_path / "s.json", acquereur([]), Horloge())
        assert "Chrome/140" in session.session().user_agent

    def test_le_user_agent_survit_au_cache_disque(self, reseau: Reseau, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        horloge = Horloge()
        SessionNavigateur(reseau, cache, acquereur([]), horloge).session()
        relue = SessionNavigateur(reseau, cache, acquereur([]), horloge).session()
        assert "Chrome/140" in relue.user_agent
