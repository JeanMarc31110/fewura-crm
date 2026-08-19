import os

import fewura_crm.prospect_engine as prospect_engine
import fewura_crm.sirene as sirene
from fewura_crm.sirene import _flatten_establishment, search_sirene


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
    monkeypatch.setattr(prospect_engine, "extract_public_contacts", lambda *args: {
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
    assert captured["params"]["nombre"] == 10


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
    monkeypatch.setattr(prospect_engine, "geocode", lambda *args: (_ for _ in ()).throw(AssertionError("OSM ne doit pas être utilisé")))
    assert prospect_engine.search_businesses(
        "Bordeaux", "all", 20, 10, enrich=False, contact_mode="either", legal_form="ei"
    ) == []
