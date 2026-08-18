import os

import fewura_crm.prospect_engine as prospect_engine
from fewura_crm.sirene import _flatten_establishment, search_sirene


def test_sirene_record_keeps_official_identifiers_and_address():
    record = _flatten_establishment({
        "siret": "12345678900012",
        "siren": "123456789",
        "uniteLegale": {"denominationUniteLegale": "Entreprise Test"},
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
