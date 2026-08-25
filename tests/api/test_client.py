"""Client HTTP : cadence, reprises, et refus explicite du challenge anti-robot.

Aucun test ne touche le reseau : httpx.MockTransport joue les reponses.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx
import pytest

from sleeper.api.client import Cadenceur, ClientDomaine, SessionStatique, identifier
from sleeper.config import Reseau
from sleeper.errors import ProtectionAntiRobotError, ReseauError

PAGE_ALTCHA = (
    "<!DOCTYPE html><html><head><title>Check that you are not a robot</title>"
    "<script src='/.well-known/ubika/captcha/altcha.js'></script></head></html>"
)


@pytest.fixture
def reseau() -> Reseau:
    return Reseau(
        user_agent="SleeperBot/0.1 (+mailto:test@example.org)",
        delai_entre_requetes_s=0.5,
        tentatives_max=3,
        backoff_initial_s=0.01,
        backoff_max_s=0.05,
    )


def horloge_qui_court() -> Any:
    """Horloge avancant de 1000 s a chaque lecture : le cadenceur ne dort jamais.

    Les sommeils enregistres sont alors exclusivement ceux du backoff, ce qui
    rend les assertions sur les reprises non ambigues.
    """
    compteur = itertools.count(0.0, 1000.0)
    return lambda: next(compteur)


def client_avec(
    reseau: Reseau, gestionnaire: Any, sommeils: list[float] | None = None
) -> ClientDomaine:
    return ClientDomaine(
        reseau=reseau,
        session=SessionStatique({"bot_mitigation_cookie": "x"}, user_agent="Chrome/140"),
        transport=httpx.MockTransport(gestionnaire),
        dormir=(sommeils.append if sommeils is not None else lambda _: None),
        horloge=horloge_qui_court(),
    )


class TestRequeteNominale:
    def test_rend_le_payload_json(self, reseau: Reseau) -> None:
        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"ok": True}})

        with client_avec(reseau, gestionnaire) as client:
            assert client.interroger("query x{y}", {"a": 1}) == {"data": {"ok": True}}

    def test_transmet_query_variables_et_operation(self, reseau: Reseau) -> None:
        vues: list[httpx.Request] = []

        def gestionnaire(requete: httpx.Request) -> httpx.Response:
            vues.append(requete)
            return httpx.Response(200, json={"data": {}})

        with client_avec(reseau, gestionnaire) as client:
            client.interroger("query getAuctions{a}", {"currentPage": 2})

        params = vues[0].url.params
        assert params["query"] == "query getAuctions{a}"
        assert json.loads(params["variables"]) == {"currentPage": 2}
        # Le navigateur d'origine ET le robot sont annonces : la session reste
        # valide cote pare-feu, et l'operateur du site peut nous joindre.
        agent = vues[0].headers["user-agent"]
        assert agent.startswith("Chrome/140")
        assert "SleeperBot/0.1 (+mailto:test@example.org)" in agent

    def test_envoie_les_cookies_de_session(self, reseau: Reseau) -> None:
        vues: list[httpx.Request] = []

        def gestionnaire(requete: httpx.Request) -> httpx.Response:
            vues.append(requete)
            return httpx.Response(200, json={"data": {}})

        with client_avec(reseau, gestionnaire) as client:
            client.interroger("query x{y}", {})
        assert "bot_mitigation_cookie=x" in vues[0].headers["cookie"]


class TestProtectionAntiRobot:
    @pytest.mark.parametrize("statut", [200, 403])
    def test_page_captcha_est_terminale(self, reseau: Reseau, statut: int) -> None:
        appels = 0

        def gestionnaire(_: httpx.Request) -> httpx.Response:
            nonlocal appels
            appels += 1
            return httpx.Response(statut, text=PAGE_ALTCHA, headers={"content-type": "text/html"})

        with client_avec(reseau, gestionnaire) as client, pytest.raises(ProtectionAntiRobotError):
            client.interroger("query x{y}", {})
        # Aucune reprise : insister sur un challenge, c'est chercher a le contourner.
        assert appels == 1

    def test_redirection_javascript_est_terminale(self, reseau: Reseau) -> None:
        page = "<html><body><script>window.location.href='/redirect_ABC/x'</script></body></html>"

        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=page, headers={"content-type": "text/html"})

        with client_avec(reseau, gestionnaire) as client, pytest.raises(ProtectionAntiRobotError):
            client.interroger("query x{y}", {})


class TestReprises:
    def test_reessaie_sur_erreur_serveur_puis_reussit(self, reseau: Reseau) -> None:
        reponses = [httpx.Response(503), httpx.Response(200, json={"data": {"ok": 1}})]

        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return reponses.pop(0)

        sommeils: list[float] = []
        with client_avec(reseau, gestionnaire, sommeils) as client:
            assert client.interroger("query x{y}", {}) == {"data": {"ok": 1}}
        assert not reponses

    def test_backoff_est_exponentiel_et_plafonne(self, reseau: Reseau) -> None:
        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        sommeils: list[float] = []
        with client_avec(reseau, gestionnaire, sommeils) as client, pytest.raises(ReseauError):
            client.interroger("query x{y}", {})
        # tentatives_max = 3 -> deux attentes entre les trois essais
        assert sommeils == [0.01, 0.02]
        assert max(sommeils) <= reseau.backoff_max_s

    def test_backoff_est_plafonne(self, reseau: Reseau) -> None:
        genereux = reseau.model_copy(
            update={"tentatives_max": 6, "backoff_initial_s": 1.0, "backoff_max_s": 4.0}
        )

        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        sommeils: list[float] = []
        with client_avec(genereux, gestionnaire, sommeils) as client, pytest.raises(ReseauError):
            client.interroger("query x{y}", {})
        assert sommeils == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_echec_persistant_leve_une_erreur_reseau_explicite(self, reseau: Reseau) -> None:
        def gestionnaire(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connexion refusee")

        with (
            client_avec(reseau, gestionnaire) as client,
            pytest.raises(ReseauError, match="3 tentatives"),
        ):
            client.interroger("query x{y}", {})

    def test_erreur_client_definitive_nest_pas_reessayee(self, reseau: Reseau) -> None:
        appels = 0

        def gestionnaire(_: httpx.Request) -> httpx.Response:
            nonlocal appels
            appels += 1
            return httpx.Response(400, json={"message": "Bad query params length"})

        with client_avec(reseau, gestionnaire) as client, pytest.raises(ReseauError, match="400"):
            client.interroger("query x{y}", {})
        assert appels == 1

    def test_reponse_non_json_est_une_erreur(self, reseau: Reseau) -> None:
        def gestionnaire(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="pas du json", headers={"content-type": "text/plain"})

        with client_avec(reseau, gestionnaire) as client, pytest.raises(ReseauError, match="JSON"):
            client.interroger("query x{y}", {})


class TestCadenceur:
    def test_espace_les_appels_du_delai_demande(self) -> None:
        # Lectures d'horloge : 1) 1er appel, 2) 2e appel, 3) apres le sommeil.
        instants = iter([0.0, 0.2, 0.5])
        sommeils: list[float] = []
        cadenceur = Cadenceur(0.5, horloge=lambda: next(instants), dormir=sommeils.append)
        cadenceur.attendre()  # premier appel : rien a attendre
        cadenceur.attendre()  # 0.2 s ecoulees : il reste 0.3 s
        assert sommeils == [pytest.approx(0.3)]

    def test_naquiert_jamais_de_delai_negatif(self) -> None:
        instants = iter([0.0, 10.0])
        sommeils: list[float] = []
        cadenceur = Cadenceur(0.5, horloge=lambda: next(instants), dormir=sommeils.append)
        cadenceur.attendre()
        cadenceur.attendre()  # largement au-dela du delai : aucun sommeil
        assert sommeils == []


class TestIdentification:
    def test_annonce_le_navigateur_puis_le_robot(self) -> None:
        compose = identifier("Mozilla/5.0 Chrome/140", "SleeperBot/0.1 (+mailto:a@b.fr)")
        assert compose == "Mozilla/5.0 Chrome/140 SleeperBot/0.1 (+mailto:a@b.fr)"

    def test_sans_navigateur_seule_lidentification_subsiste(self) -> None:
        assert identifier("", "SleeperBot/0.1") == "SleeperBot/0.1"
