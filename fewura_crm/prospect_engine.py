from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
from urllib.parse import urljoin, urlparse

import httpx
from .sirene import SireneUnavailable, search_sirene
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except Exception:
    DDGS = None

try:
    import dns.resolver
except Exception:
    dns = None

CATEGORIES = {
    "restaurants": {"amenity": ["restaurant", "fast_food", "cafe"]},
    "hotels": {"tourism": ["hotel", "guest_house", "motel"]},
    "garages": {"shop": ["car_repair", "car"]},
    "immobilier": {"office": ["estate_agent"]},
    "comptables": {"office": ["accountant"]},
    "avocats": {"office": ["lawyer"]},
    "informatique": {"office": ["it"], "shop": ["computer"]},
    "batiment": {"craft": ["builder", "electrician", "plumber", "carpenter", "painter"]},
    "coiffure": {"shop": ["hairdresser"]},
    "sport": {"leisure": ["fitness_centre", "sports_centre"]},
    "transport": {
        "office": ["logistics", "transport", "moving_company", "courier", "freight_forwarder"],
        "craft": ["transportation"],
        "industrial": ["logistics"],
    },
    "commerce": {"shop": ["supermarket", "convenience", "department_store", "clothes", "bakery", "butcher", "furniture"]},
    "artisanat": {"craft": ["carpenter", "plumber", "electrician", "painter", "photographer", "shoemaker"]},
    "sante": {"amenity": ["doctors", "dentist", "clinic", "pharmacy", "veterinary"]},
    "beauté": {"shop": ["beauty", "cosmetics"], "amenity": ["spa"]},
    "formation": {"amenity": ["school", "college", "language_school"]},
    "conseil": {"office": ["consulting", "business_consulting", "financial"]},
    "agence_immobiliere": {"office": ["estate_agent"]},
    "automobile": {"shop": ["car", "car_parts", "tyres"]},
    "logistique": {"office": ["logistics", "courier", "freight_forwarder"]},
    "nettoyage": {"office": ["cleaning"], "craft": ["cleaning"]},
    "securite": {"office": ["security"]},
    "evenementiel": {"office": ["event_management"]},
}

PUBLIC_OWNERSHIP_VALUES = {
    "government", "public", "state", "municipal", "regional", "local_authority",
}
PUBLIC_NAME_MARKERS = (
    "mairie", "toulouse métropole", "toulouse metropole", "métropole", "metropole",
    "préfecture", "prefecture", "conseil départemental", "conseil régional", "conseil regional",
    "ministère", "ministere", "université", "universite", "chu", "crous", "sncf", "ratp",
    "tisséo", "tisseo", "la poste",
)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
GENERIC = {
    "contact", "info", "commercial", "sales", "bonjour", "hello", "accueil",
    "direction", "secretariat", "serviceclient", "support", "office", "admin",
    "administration", "agence", "cabinet", "communication", "marketing", "rh",
    "recrutement", "reservation", "reservations", "booking", "service", "contacteznous",
}
DISPOSABLE_DOMAINS = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com", "trashmail.com"}
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
    "yahoo.fr", "orange.fr", "wanadoo.fr", "free.fr", "laposte.net", "icloud.com",
    "proton.me", "protonmail.com",
}
BLOCKED_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "pagesjaunes.fr", "tripadvisor.fr",
    "societe.com", "verif.com", "pappers.fr", "google.com", "maps.google.com", "x.com", "lefigaro.fr", "univ-tlse3.fr",
    "twitter.com", "youtube.com",
}
CONTACT_HINTS = (
    "contact", "nous-contacter", "contactez", "mentions-legales", "mentions", "legal",
    "impressum", "equipe", "team", "a-propos", "about", "cabinet", "agence", "societe",
    "entreprise", "coordonnees", "direction", "staff", "office",
)


def geocode(zone: str) -> dict:
    headers = {"User-Agent": os.getenv("USER_AGENT", "FEWURA-CRM-PROSPECT/1.0")}
    params = {"q": zone, "format": "jsonv2", "limit": 1, "countrycodes": "fr"}
    with httpx.Client(timeout=15, headers=headers, follow_redirects=True) as client:
        response = client.get("https://nominatim.openstreetmap.org/search", params=params)
        response.raise_for_status()
        data = response.json()
    if not data:
        raise ValueError(f"Zone introuvable: {zone}")
    return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]), "display_name": data[0].get("display_name", zone)}


def build_overpass_query(lat: float, lon: float, radius: int, category: str) -> str:
    cfg = CATEGORIES.get(category, {}) if category != "all" else {}
    if cfg:
        clauses = "".join(f'nwr(around:{radius},{lat},{lon})["{key}"="{value}"];' for key, values in cfg.items() for value in values)
    else:
        clauses = "".join(f'nwr(around:{radius},{lat},{lon})["{key}"];' for key in ["shop", "office", "amenity", "craft", "tourism", "leisure"])
    return f'[out:json][timeout:30];({clauses});out tags center;'


def _fetch_overpass(query: str) -> dict:
    headers = {"User-Agent": os.getenv("USER_AGENT", "FEWURA-CRM-PROSPECT/1.0")}
    errors = []
    timeout = httpx.Timeout(connect=8.0, read=35.0, write=15.0, pool=8.0)
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                response = client.post(endpoint, data={"data": query})
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and "elements" in data:
                    return data
                errors.append(f"{endpoint}: réponse inattendue")
            except Exception as exc:
                errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("Aucun serveur Overpass disponible. " + " | ".join(errors))


def normalize_email(value: str | None) -> str:
    email = (value or "").strip().lower().replace("mailto:", "").split("?", 1)[0]
    return email.strip(" <>\"'()[]{}.,;:")


def _website_domain(url: str | None) -> str:
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _email_domain(email: str) -> str:
    email = normalize_email(email)
    return email.split("@", 1)[1] if EMAIL_RE.fullmatch(email) else ""


def is_public_business_email(email: str, website: str | None = None) -> bool:
    email = normalize_email(email)
    if not EMAIL_RE.fullmatch(email):
        return False
    domain = _email_domain(email)
    if not domain or domain in DISPOSABLE_DOMAINS:
        return False
    if domain.rsplit(".", 1)[-1] in {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js"}:
        return False
    local = email.split("@", 1)[0]
    if local in {"noreply", "no-reply", "donotreply", "do-not-reply"}:
        return False
    website_domain = _website_domain(website)
    if website_domain and (domain == website_domain or domain.endswith("." + website_domain) or website_domain.endswith("." + domain)):
        return True
    compact = re.sub(r"[._+-]", "", local)
    if local in GENERIC or compact in GENERIC or local.startswith(("contact", "info", "commercial", "sales", "accueil", "direction", "office", "admin")):
        return True
    return domain not in FREE_MAIL_DOMAINS


def _email_score(email: str, website: str | None) -> int:
    if not is_public_business_email(email, website):
        return -100
    score = 20
    domain = _email_domain(email)
    website_domain = _website_domain(website)
    if website_domain and domain == website_domain:
        score += 60
    if re.sub(r"[._+-]", "", email.split("@", 1)[0]) in GENERIC:
        score += 30
    if domain not in FREE_MAIL_DOMAINS:
        score += 10
    return score


def _deobfuscate(text: str) -> str:
    text = html_lib.unescape(text or "")
    for pattern, replacement in [
        (r"\s*(?:\[|\()\s*at\s*(?:\]|\))\s*", "@"),
        (r"\s+(?:at|arobase)\s+", "@"),
        (r"\s*(?:\[|\()\s*dot\s*(?:\]|\))\s*", "."),
        (r"\s+(?:dot|point)\s+", "."),
    ]:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def extract_public_contacts(url: str, max_pages: int = 8) -> dict:
    if not url:
        return {"email": None, "contact_form_url": None, "phone": None}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        "User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 FEWURA-CRM-PROSPECT/1.0"),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    }
    emails: list[str] = []
    forms: list[str] = []
    phone = None
    visited: set[str] = set()
    try:
        with httpx.Client(timeout=12, headers=headers, follow_redirects=True) as client:
            first = client.get(url)
            first.raise_for_status()
            root_url = str(first.url)
            root_host = urlparse(root_url).netloc.lower()
            queue = [(root_url, first.text)]
            while queue and len(visited) < max_pages:
                page_url, page_html = queue.pop(0)
                if page_url in visited:
                    continue
                visited.add(page_url)
                soup = BeautifulSoup(page_html, "lxml")
                for node in soup.select('a[href^="mailto:"]'):
                    emails.append(normalize_email(node.get("href")))
                for raw in [soup.get_text(" ", strip=True), str(soup)]:
                    emails.extend(normalize_email(x) for x in EMAIL_RE.findall(_deobfuscate(raw)))
                if soup.find("form") and any(k in page_url.lower() for k in ("contact", "coordonne", "about", "equipe")):
                    forms.append(page_url)
                if not phone:
                    tel = soup.select_one('a[href^="tel:"]')
                    if tel:
                        phone = tel.get("href", "").replace("tel:", "").strip()
                ranked_links = []
                for anchor in soup.select("a[href]"):
                    href = anchor.get("href", "").strip()
                    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                        continue
                    absolute = urljoin(page_url, href).split("#", 1)[0]
                    if urlparse(absolute).netloc.lower() != root_host:
                        continue
                    text = (href + " " + anchor.get_text(" ", strip=True)).lower()
                    rank = sum(1 for hint in CONTACT_HINTS if hint in text)
                    if rank:
                        ranked_links.append((rank, absolute))
                for _, absolute in sorted(ranked_links, reverse=True):
                    if absolute in visited or any(absolute == queued for queued, _ in queue):
                        continue
                    try:
                        response = client.get(absolute)
                        if response.is_success and ("text/html" in response.headers.get("content-type", "") or not response.headers.get("content-type")):
                            queue.append((str(response.url), response.text))
                    except Exception:
                        continue
                    if len(visited) + len(queue) >= max_pages:
                        break
    except Exception:
        pass
    valid = sorted({normalize_email(e) for e in emails if is_public_business_email(e, url)}, key=lambda e: _email_score(e, url), reverse=True)
    return {"email": valid[0] if valid else None, "contact_form_url": forms[0] if forms else None, "phone": phone}


def _tokens(value: str | None) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower()) if token not in {"sas", "sarl", "eurl", "sa", "sasu", "france", "entreprise", "societe"}}


def _search_web_results(query: str, max_results: int = 8) -> list[dict]:
    if DDGS is not None:
        try:
            return list(DDGS().text(query, region="fr-fr", safesearch="moderate", max_results=max_results) or [])
        except Exception:
            pass

    # Fallback for packaged installs where the optional ddgs package is absent.
    headers = {"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 FEWURA-CRM-PROSPECT/1.0")}
    try:
        with httpx.Client(timeout=12, headers=headers, follow_redirects=True) as client:
            response = client.get("https://www.bing.com/search", params={"q": query, "count": max_results})
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results = []
        for item in soup.select("li.b_algo")[:max_results]:
            link = item.select_one("h2 a[href]")
            if not link:
                continue
            results.append({
                "href": link.get("href"),
                "title": link.get_text(" ", strip=True),
                "body": item.get_text(" ", strip=True),
            })
        return results
    except Exception:
        return []


def discover_official_website(
    company_name: str,
    city: str | None = None,
    max_results: int = 8,
    address: str | None = None,
    siren: str | None = None,
    siret: str | None = None,
) -> str | None:
    """Find a public business site using SIRENE identity data."""
    if not company_name or company_name.strip().upper() in {"[ND]", "ND"}:
        return None
    identity = " ".join(x for x in (address, city, siren, siret) if x)
    queries = [
        f'"{company_name}" {identity} site officiel contact'.strip(),
        f'"{company_name}" {city or ""} email téléphone'.strip(),
    ]
    company_tokens = _tokens(company_name)
    city_tokens = _tokens(city)
    ranked = []
    seen_urls = set()
    for query in queries:
        for item in _search_web_results(query, max_results):
            url = item.get("href") or item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            host = _website_domain(url)
            if not host or host in BLOCKED_HOSTS or any(host.endswith("." + blocked) for blocked in BLOCKED_HOSTS):
                continue
            haystack = " ".join([host, item.get("title", ""), item.get("body", "")]).lower()
            score = 4 * sum(1 for token in company_tokens if token in haystack) + sum(1 for token in city_tokens if token in haystack)
            if any(word in haystack for word in ("contact", "officiel", "accueil", "cabinet", "agence", "email", "téléphone")):
                score += 2
            if host.endswith(".fr"):
                score += 1
            ranked.append((score, url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= 4 else None


def lead_score(prospect: dict) -> int:
    score = 0
    for field, points in [("website", 10), ("email", 20), ("phone", 10), ("category", 20), ("city", 15), ("source_url", 10)]:
        if prospect.get(field):
            score += points
    if prospect.get("address") or prospect.get("postal_code"):
        score += 10
    if prospect.get("contact_form_url"):
        score += 5
    return min(score, 100)


def fingerprint(prospect: dict) -> str:
    domain = _website_domain(prospect.get("website"))
    raw = "|".join([
        (prospect.get("company_name") or "").lower().strip(), domain,
        (prospect.get("phone") or "").strip(), (prospect.get("address") or "").lower().strip(),
        (prospect.get("city") or "").lower().strip(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def is_private_business(name: str, tags: dict) -> bool:
    ownership_values = " ".join(
        str(tags.get(key, "")).strip().lower()
        for key in ("ownership", "operator:type", "government", "owner:type")
    )
    if any(value in ownership_values.split() for value in PUBLIC_OWNERSHIP_VALUES):
        return False
    normalized_name = re.sub(r"\s+", " ", (name or "").strip().lower())
    return not any(marker in normalized_name for marker in PUBLIC_NAME_MARKERS)


def contact_matches_mode(prospect: dict, contact_mode: str = "either") -> bool:
    """Check the selected contact requirement before importing a prospect."""
    mode = (contact_mode or "either").strip().lower()
    if mode not in {"either", "email", "phone"}:
        raise ValueError("contact_mode doit être either, email ou phone")
    has_email = bool(str(prospect.get("email") or "").strip())
    has_phone = bool(str(prospect.get("phone") or "").strip())
    return (has_email or has_phone) if mode == "either" else (has_email if mode == "email" else has_phone)


def search_businesses(zone: str, category: str = "all", radius_km: int = 20, max_results: int = 50, enrich: bool = True, contact_mode: str = "either", legal_form: str = "all") -> list[dict]:
    # SIRENE/INSEE is the primary source. OSM remains a fallback when the API
    # is not configured, unavailable, or returns no establishment.
    try:
        registry = search_sirene(zone, category, max_results, legal_form)
    except SireneUnavailable:
        registry = []
    if not registry and legal_form != "all":
        # OSM does not expose the official legal form. Falling back here would
        # return companies that do not match the user's SIRENE filter.
        return []

    if registry:
        output = []
        for prospect in registry:
            if not prospect.get("website"):
                prospect["website"] = discover_official_website(
                    prospect["company_name"], prospect["city"], address=prospect.get("address"),
                    siren=prospect.get("siren"), siret=prospect.get("siret")
                )
            if prospect.get("website") and not prospect.get("email"):
                contacts = extract_public_contacts(prospect["website"])
                prospect["email"] = contacts.get("email")
                prospect["contact_form_url"] = contacts.get("contact_form_url")
                prospect["phone"] = prospect.get("phone") or contacts.get("phone")
            if prospect.get("email"):
                prospect["email"] = normalize_email(prospect["email"])
                if not is_public_business_email(prospect["email"], prospect.get("website")):
                    prospect["email"] = None
            if not contact_matches_mode(prospect, contact_mode):
                continue
            prospect["lead_score"] = lead_score(prospect)
            prospect["confidence"] = round(prospect["lead_score"] / 100, 2)
            prospect["fingerprint"] = fingerprint(prospect)
            output.append(prospect)
        return output

    geo = geocode(zone)
    radius = max(1000, min(int(radius_km) * 1000, 50000))
    limit = max(1, min(int(max_results), 200))
    query = build_overpass_query(geo["lat"], geo["lon"], radius, category)
    try:
        data = _fetch_overpass(query)
    except RuntimeError:
        # Les requêtes "all" sur un grand rayon peuvent dépasser les quotas publics.
        # Réduire le rayon permet un second essai moins coûteux sans masquer l'erreur finale.
        if radius <= 10000:
            raise
        reduced_radius = max(1000, radius // 2)
        data = _fetch_overpass(build_overpass_query(geo["lat"], geo["lon"], reduced_radius, category))
    output = []
    seen = set()
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        center = element.get("center", {})
        name = tags.get("name") or tags.get("brand") or tags.get("operator")
        if not name:
            continue
        if not is_private_business(name, tags):
            continue
        key = (name.lower().strip(), tags.get("addr:street"), tags.get("addr:housenumber"))
        if key in seen:
            continue
        seen.add(key)
        prospect = {
            "company_name": name,
            "category": tags.get("office") or tags.get("shop") or tags.get("amenity") or tags.get("craft") or tags.get("tourism") or tags.get("leisure") or category,
            "address": " ".join(x for x in [tags.get("addr:housenumber", ""), tags.get("addr:street", "")] if x),
            "postal_code": tags.get("addr:postcode"),
            "city": tags.get("addr:city") or zone,
            "region": None,
            "country": tags.get("addr:country", "FR"),
            "lat": element.get("lat", center.get("lat")),
            "lon": element.get("lon", center.get("lon")),
            "phone": tags.get("contact:phone") or tags.get("phone"),
            "website": tags.get("contact:website") or tags.get("website"),
            "email": tags.get("contact:email") or tags.get("email"),
            "contact_form_url": None,
            "source_url": f'https://www.openstreetmap.org/{element.get("type")}/{element.get("id")}',
            "source_type": "FEWURA Prospect / OpenStreetMap",
        }
        if enrich and not prospect["website"]:
            prospect["website"] = discover_official_website(prospect["company_name"], prospect["city"])
        if enrich and prospect["website"] and not prospect["email"]:
            contacts = extract_public_contacts(prospect["website"])
            prospect["email"] = contacts.get("email")
            prospect["contact_form_url"] = contacts.get("contact_form_url")
            prospect["phone"] = prospect["phone"] or contacts.get("phone")
        if prospect.get("email"):
            prospect["email"] = normalize_email(prospect["email"])
            if not is_public_business_email(prospect["email"], prospect.get("website")):
                prospect["email"] = None
        # A result without any usable contact channel cannot be actioned.
        if not contact_matches_mode(prospect, contact_mode):
            continue
        prospect["lead_score"] = lead_score(prospect)
        prospect["confidence"] = round(prospect["lead_score"] / 100, 2)
        prospect["fingerprint"] = fingerprint(prospect)
        output.append(prospect)
        if len(output) >= limit:
            break
    return output

