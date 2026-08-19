import os

import fewura_crm.prospect_engine as prospect_engine
import fewura_crm.sirene as sirene
from fewura_crm.sirene import _flatten_establishment, search_recherche_entreprises, search_sirene


def test_sirene_record_keeps_official_identifiers_and_address():
    record = _flatten_establishment({
        "siret": "12345678900012",
        "siren": "123456789",
        "uniteLegale": {"denominationUniteLegale": "Entreprise Test", "categorieJuridiqueUniteLegale": "5710"},
        "adresseEtablissement": {
            "numeroVoieEtablissement": "10",
            "typeVoieEtablissement": "RUE",
            "libelleVoieEtablissement": "TEST",
            "codePostalEtablissement": "31000",
            "libelleCommuneEtablissement": "Toulouse",
        },
        "periodesEtablissement": [{"activitePrincipaleEtablissement": "62.01Z"}],
    }, "informatique", "Toulouse")
    assert record["siren"] == "123456789"
    assert record["siret"] == "12345678900012"
    assert record["company_name"] == "Entreprise Test"
    assert record["source_type"] == "SIRENE / INSEE"
    assert record["postal_code"] == "31000"
    assert record["legal_form_code"] == "5710"


def test_sirene_is_primary_before_osm_and_then_scrapes_site(monkeypatch):
    registry_record = {
        "company_name": "Entreprise SIRENE",
        "siren": "123456789",
        "siret": "12345678900012",
        "category": "informatique",
        "city": "Toulouse",
        "website": "https://entreprise.test",
        "email": None,
        "phone": None,
        "source": "SIRENE / INSEE",
        "source_url": "https://annuaire-entreprises.data.gouv.fr/etablissement/12345678900012",
        "source_type": "SIRENE / INSEE",
        "contact_form_url": None,
    }
    monkeypatch.setattr(prospect_engine, "search_sirene", lambda *args: [dict(registry_record)])
    monkeypatch.setattr(prospect_engine, "extract_public_contacts", lambda *args, **kwargs: {
        "email": "contact@entreprise.test", "phone": "0611223344", "contact_form_url": None,
    })
    monkeypatch.setattr(prospect_engine, "geocode", lambda *args: (_ for _ in ()).throw(AssertionError("OSM ne doit pas être appelé")))
    found = prospect_engine.search_businesses("Toulouse", "informatique", 10, 10, enrich=True, contact_mode="email")
    assert len(found) == 1
    assert found[0]["siren"] == "123456789"
    assert found[0]["email"] == "contact@entreprise.test"



def test_sirene_legal_form_adds_official_query_filter(monkeypatch):
    captured = {}
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"etablissements": []}
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, endpoint, params=None):
            captured["endpoint"] = endpoint
            captured["params"] = params
            return Response()
    monkeypatch.setattr(sirene, "_api_key", lambda: "test-key")
    monkeypatch.setattr(sirene.httpx, "Client", Client)
    assert search_sirene("Toulouse", max_results=10, legal_form="sas") == []
    assert captured["endpoint"] == sirene.SIRENE_ENDPOINT
    assert "categorieJuridiqueUniteLegale:5710" in captured["params"]["q"]
    assert captured["params"]["nombre"] == 200
    assert captured["params"]["debut"] == 0


def test_sirene_paginates_up_to_requested_batch(monkeypatch):
    calls = []
    class Response:
        status_code = 200
        def __init__(self, index):
            self.index = index
        def raise_for_status(self):
            return None
        def json(self):
            return {"etablissements": [{
                "siret": f"123456789{self.index:05d}{item:02d}",
                "siren": "123456789",
                "uniteLegale": {"denominationUniteLegale": f"EI {self.index}-{item}"},
                "adresseEtablissement": {"libelleCommuneEtablissement": "Toulouse"},
                "periodesEtablissement": [{"etatAdministratifEtablissement": "A"}],
            } for item in range(200)]}
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, endpoint, params=None):
            calls.append(params["debut"])
            return Response(len(calls))
    monkeypatch.setattr(sirene, "_api_key", lambda: "test-key")
    monkeypatch.setattr(sirene.httpx, "Client", Client)
    found = search_sirene("Toulouse", max_results=201, legal_form="ei")
    assert len(found) == 201
    assert calls == [0, 200]


def test_sirene_rejects_unknown_legal_form(monkeypatch):
    monkeypatch.setattr(sirene, "_api_key", lambda: "test-key")
    try:
        search_sirene("Toulouse", legal_form="unknown")
    except ValueError as exc:
        assert "legal_form invalide" in str(exc)
    else:
        raise AssertionError("Une forme juridique inconnue doit être refusée")



def test_legal_form_filter_never_falls_back_to_osm(monkeypatch):
    monkeypatch.setattr(prospect_engine, "search_sirene", lambda *args: [])
    monkeypatch.setattr(prospect_engine, "search_recherche_entreprises", lambda *args: [])
    monkeypatch.setattr(prospect_engine, "geocode", lambda *args: (_ for _ in ()).throw(AssertionError("OSM ne doit pas être utilisé")))
    assert prospect_engine.search_businesses(
        "Bordeaux", "all", 20, 10, enrich=False, contact_mode="either", legal_form="ei"
    ) == []


def test_recherche_entreprises_keeps_only_active_exact_city_and_legal_form(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "results": [
                    {
                        "siren": "111111111",
                        "nom_complet": "EI Toulouse",
                        "nature_juridique": "1000",
                        "matching_etablissements": [
                            {"siret": "11111111100011", "libelle_commune": "TOULOUSE", "etat_administratif": "A", "code_postal": "31000", "adresse": "1 RUE TEST", "activite_principale": "62.01Z"},
                            {"siret": "11111111100022", "libelle_commune": "PARIS", "etat_administratif": "A"},
                        ],
                    },
                    {
                        "siren": "222222222",
                        "nom_complet": "EI Fermée",
                        "nature_juridique": "1000",
                        "matching_etablissements": [
                            {"siret": "22222222200022", "libelle_commune": "TOULOUSE", "etat_administratif": "F"},
                        ],
                    },
                ]
            }
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, endpoint, params=None):
            assert endpoint == sirene.RECHERCHE_ENTREPRISES_ENDPOINT
            assert params["nature_juridique"] == "1000"
            return Response()
    monkeypatch.setattr(sirene.httpx, "Client", Client)
    found = search_recherche_entreprises("Toulouse", max_results=10, legal_form="ei")
    assert [item["siret"] for item in found] == ["11111111100011"]
    assert found[0]["source_type"] == "Recherche Entreprises / data.gouv.fr"


def test_registry_sources_are_merged_by_siret(monkeypatch):
    primary = [{"company_name": "Déjà là", "siret": "11111111100011", "city": "Toulouse", "email": "a@example.test", "phone": None}]
    secondary = [
        {"company_name": "Doublon", "siret": "11111111100011", "city": "Toulouse", "email": None, "phone": None},
        {"company_name": "Nouveau", "siret": "22222222200022", "city": "Toulouse", "email": "b@example.test", "phone": None},
    ]
    monkeypatch.setattr(prospect_engine, "search_sirene", lambda *args: primary)
    monkeypatch.setattr(prospect_engine, "search_recherche_entreprises", lambda *args: secondary)
    monkeypatch.setattr(prospect_engine, "discover_official_website", lambda *args, **kwargs: None)
    found = prospect_engine.search_businesses("Toulouse", max_results=2, enrich=False, contact_mode="email", legal_form="ei")
    assert [item["siret"] for item in found] == ["11111111100011", "22222222200022"]



def test_sirene_discards_inactive_establishments(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "etablissements": [
                    {
                        "siret": "11111111100011",
                        "periodesEtablissement": [{"dateFin": None, "etatAdministratifEtablissement": "F"}],
                        "uniteLegale": {"denominationUniteLegale": "Fermée"},
                    },
                    {
                        "siret": "22222222200022",
                        "periodesEtablissement": [{"dateFin": None, "etatAdministratifEtablissement": "A"}],
                        "uniteLegale": {"denominationUniteLegale": "Active"},
                    },
                ]
            }
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, endpoint, params=None):
            return Response()
    monkeypatch.setattr(sirene, "_api_key", lambda: "test-key")
    monkeypatch.setattr(sirene.httpx, "Client", Client)
    found = search_sirene("Bordeaux", max_results=10, legal_form="ei")
    assert [item["company_name"] for item in found] == ["Active"]



def test_every_sirene_result_is_web_enriched_before_contact_filter(monkeypatch):
    registry = [
        {"company_name": "Entreprise A", "city": "Bordeaux", "siren": "111111111", "siret": "11111111100011", "website": None, "email": None, "phone": None},
        {"company_name": "Entreprise B", "city": "Bordeaux", "siren": "222222222", "siret": "22222222200022", "website": None, "email": None, "phone": None},
        {"company_name": "Entreprise C", "city": "Bordeaux", "siren": "333333333", "siret": "33333333300033", "website": None, "email": None, "phone": None},
    ]
    searched = []
    monkeypatch.setattr(prospect_engine, "search_sirene", lambda *args: [dict(item) for item in registry])
    def discover(*args, **kwargs):
        searched.append(kwargs.get("siret"))
        return "https://example.test"
    monkeypatch.setattr(prospect_engine, "discover_official_website", discover)
    monkeypatch.setattr(prospect_engine, "extract_public_contacts", lambda website, **kwargs: {
        "email": "contact@example.test", "phone": None, "contact_form_url": None,
    })
    monkeypatch.setattr(prospect_engine, "search_recherche_entreprises", lambda *args: [])
    found = prospect_engine.search_businesses(
        "Bordeaux", "all", 20, 20, enrich=False, contact_mode="email", legal_form="ei"
    )
    assert searched == ["11111111100011", "22222222200022", "33333333300033"]
    assert len(found) == 3




