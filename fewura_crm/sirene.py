from __future__ import annotations

import os
from urllib.parse import quote

import httpx

from .db import init_db, one


SIRENE_ENDPOINT = "https://api.insee.fr/api-sirene/3.11/siret"
RECHERCHE_ENTREPRISES_ENDPOINT = "https://recherche-entreprises.api.gouv.fr/search"

LEGAL_FORM_LABELS = {
    "all": "Toutes les formes juridiques",
    "ei": "Entrepreneur individuel / micro-entreprise",
    "sarl": "SARL / EURL",
    "sas": "SAS",
    "sasu": "SASU (code SIRENE 5710)",
    "sa": "SA",
    "sci": "SCI",
    "association": "Association",
}
LEGAL_FORM_CODES = {
    "ei": ("1000",),
    "sarl": ("5499", "5498"),
    "sas": ("5710",),
    "sasu": ("5710",),
    "sa": ("5510", "5520", "5599", "5610", "5620", "5699"),
    "sci": ("6540", "6541"),
    "association": ("9210", "9220", "9230", "9240", "9260", "9300"),
}



class SireneUnavailable(RuntimeError):
    """The official SIRENE registry could not be queried."""


def _api_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "FEWURA-CRM-PROSPECT/1.4.4",
    }


def _api_key() -> str:
    value = os.getenv("FEWURA_SIRENE_API_KEY", "").strip()
    if value:
        return value
    init_db()
    row = one("SELECT value FROM settings WHERE key='sirene_api_key'")
    return str(row["value"] or "").strip() if row else ""


def _escape_query(value: str) -> str:
    return value.replace("\\", " ").replace('"', " ").strip()


def _first(mapping: dict, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _flatten_establishment(item: dict, category: str, zone: str, legal_form: str = "all") -> dict | None:
    address = item.get("adresseEtablissement") or {}
    legal = item.get("uniteLegale") or {}
    periods = item.get("periodesEtablissement") or []
    period = periods[0] if periods else {}
    legal_form_code = _first(legal, "categorieJuridiqueUniteLegale") or _first(period, "categorieJuridiqueUniteLegale")
    name = _first(
        legal,
        "denominationUniteLegale",
        "nomUsageUniteLegale",
        "nomUniteLegale",
        "sigleUniteLegale",
    )
    siret = str(item.get("siret") or "").strip()
    if not name or not siret:
        return None
    street = " ".join(
        str(x).strip()
        for x in (
            address.get("numeroVoieEtablissement"),
            address.get("indiceRepetitionEtablissement"),
            address.get("typeVoieEtablissement"),
            address.get("libelleVoieEtablissement"),
        )
        if x
    )
    city = _first(address, "libelleCommuneEtablissement", "libelleCedexEtablissement") or zone
    website = _first(item, "urlEtablissement", "siteWebEtablissement")
    return {
        "company_name": str(name).strip(),
        "siren": str(item.get("siren") or legal.get("siren") or siret[:9]).strip(),
        "siret": siret,
        "category": category,
        "address": street,
        "postal_code": _first(address, "codePostalEtablissement"),
        "city": city,
        "country": "FR",
        "website": website,
        "email": None,
        "phone": None,
        "source": "SIRENE / INSEE",
        "source_url": f"https://annuaire-entreprises.data.gouv.fr/etablissement/{siret}",
        "source_type": "SIRENE / INSEE",
        "activity_code": _first(period, "activitePrincipaleEtablissement"),
        "legal_form_code": legal_form_code,
        "legal_form": legal_form,
        "contact_form_url": None,
    }


def search_sirene(zone: str, category: str = "all", max_results: int = 50, legal_form: str = "all") -> list[dict]:
    """Search active establishments in SIRENE before any OSM/web fallback."""
    key = _api_key()
    if not key:
        return []
    if legal_form not in LEGAL_FORM_LABELS:
        raise ValueError(f"legal_form invalide: {legal_form}")
    query = f'-periode(etatAdministratifEtablissement:F) AND libelleCommuneEtablissement:"{_escape_query(zone)}"'
    codes = LEGAL_FORM_CODES.get(legal_form, ())
    if codes:
        legal_query = codes[0] if len(codes) == 1 else "(" + " OR ".join(codes) + ")"
        query += " AND categorieJuridiqueUniteLegale:" + legal_query
    headers = {**_api_headers(), "X-INSEE-Api-Key-Integration": key}
    params = {"q": query, "nombre": max(1, min(int(max_results), 200)), "debut": 0}
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=8, read=25, write=8, pool=8), follow_redirects=True, headers=headers) as client:
            response = client.get(SIRENE_ENDPOINT, params=params)
            if response.status_code in (401, 403, 429):
                raise SireneUnavailable(f"SIRENE HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
    except SireneUnavailable:
        raise
    except Exception as exc:
        raise SireneUnavailable(f"SIRENE indisponible : {exc}") from exc
    results = []
    for item in payload.get("etablissements", []):
        periods = item.get("periodesEtablissement") or []
        current = next((period for period in periods if period.get("dateFin") in (None, "")), periods[0] if periods else None)
        if current and str(current.get("etatAdministratifEtablissement") or "").upper() != "A":
            continue
        prospect = _flatten_establishment(item, category, zone, legal_form)
        if prospect:
            results.append(prospect)
    return results


def search_recherche_entreprises(
    zone: str,
    category: str = "all",
    max_results: int = 50,
    legal_form: str = "all",
) -> list[dict]:
    """Use the official Annuaire des Entreprises API as a complementary source.

    The API returns legal units and their establishments.  We only keep an
    open establishment whose exact municipality matches ``zone``; otherwise
    a company headquartered elsewhere could incorrectly enter the search.
    """
    if legal_form not in LEGAL_FORM_LABELS:
        raise ValueError(f"legal_form invalide: {legal_form}")
    codes = LEGAL_FORM_CODES.get(legal_form, ())
    # The public endpoint rejects values above 25.
    per_page = 25
    params = {
        "q": "" if zone.strip().isdigit() else zone.strip(),
        "page": 1,
        "per_page": per_page,
    }
    if zone.strip().isdigit() and len(zone.strip()) == 5:
        params["code_postal"] = zone.strip()
    if len(codes) == 1:
        params["nature_juridique"] = codes[0]
    elif codes:
        params["nature_juridique"] = ",".join(codes)
    wanted_city = _escape_query(zone).casefold()
    results: list[dict] = []
    seen: set[str] = set()
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=8, read=25, write=8, pool=8), follow_redirects=True, headers=_api_headers()) as client:
            payload = None
            total_pages = 1
            for page in range(1, 11):
                params["page"] = page
                response = client.get(RECHERCHE_ENTREPRISES_ENDPOINT, params=params)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise SireneUnavailable(f"Recherche Entreprises HTTP {response.status_code}")
                response.raise_for_status()
                payload = response.json()
                total_pages = int(payload.get("total_pages") or 1)
                for legal in payload.get("results", []):
                    legal_siren = str(legal.get("siren") or "").strip()
                    legal_name = legal.get("nom_complet") or legal.get("nom_raison_sociale")
                    if not legal_siren or not legal_name:
                        continue
                    establishments = legal.get("matching_etablissements") or []
                    for establishment in establishments:
                        city = str(establishment.get("libelle_commune") or "").strip()
                        if not city or city.casefold() != wanted_city:
                            continue
                        if str(establishment.get("etat_administratif") or "").upper() != "A":
                            continue
                        siret = str(establishment.get("siret") or "").strip()
                        if not siret or siret in seen:
                            continue
                        seen.add(siret)
                        results.append({
                            "company_name": str(legal_name).strip(),
                            "siren": legal_siren,
                            "siret": siret,
                            "category": category,
                            "address": str(establishment.get("adresse") or "").strip(),
                            "postal_code": establishment.get("code_postal"),
                            "city": city,
                            "country": "FR",
                            "website": None,
                            "email": None,
                            "phone": None,
                            "source": "Recherche Entreprises / data.gouv.fr",
                            "source_url": f"https://annuaire-entreprises.data.gouv.fr/etablissement/{siret}",
                            "source_type": "Recherche Entreprises / data.gouv.fr",
                            "activity_code": establishment.get("activite_principale"),
                            "legal_form_code": legal.get("nature_juridique"),
                            "legal_form": legal_form,
                            "contact_form_url": None,
                        })
                        if len(results) >= max(1, int(max_results)):
                            return results
                if page >= total_pages:
                    break
    except SireneUnavailable:
        raise
    except Exception as exc:
        raise SireneUnavailable(f"Recherche Entreprises indisponible : {exc}") from exc

    return results

