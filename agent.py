import sys
from fewura_crm.db import init_db
from fewura_crm.paths import data_dir
from fewura_crm.tools import (
    prospect_search_import,
    list_prospects,
    search_prospects,
    update_prospect_status,
    add_note,
    add_task,
    crm_summary,
    export_prospects_csv,
)

VERSION = "1.1.1"


def self_test() -> int:
    init_db()
    checks = {
        "database": data_dir().exists(),
        "prospect_engine": callable(prospect_search_import),
        "local_only": True,
        "version": VERSION == "1.1.1",
    }
    print({"ok": all(checks.values()), "checks": checks, "version": VERSION})
    return 0 if all(checks.values()) else 2


def _print_help() -> None:
    print("""
Commandes FEWURA CRM :
  recherche ZONE | CATEGORIE | RAYON_KM | MAX
  liste [N]
  trouver TEXTE
  resume
  statut ID STATUT
  note ID TEXTE
  tache ID TEXTE
  export
  aide
  quitter

Exemple : recherche Toulouse | hotels | 20 | 50
""".strip())


def _show_rows(items: list[dict]) -> None:
    if not items:
        print("Aucun résultat.")
        return
    for p in items:
        print(f"#{p.get('id')} | {p.get('company_name','')} | {p.get('city','')} | {p.get('phone','') or '-'} | {p.get('email','') or '-'} | {p.get('status','')}")


def main() -> None:
    init_db()
    print(f"FEWURA CRM {VERSION}")
    print("Moteur de prospection : FEWURA PROSPECT")
    print("Fonctionnement 100% local - aucune clé API requise.")
    _print_help()
    while True:
        try:
            raw = input("\nFEWURA CRM > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        low = raw.lower()
        if low in {"quitter", "quit", "exit", "q"}:
            break
        if low in {"aide", "help", "?"}:
            _print_help(); continue
        try:
            if low.startswith("recherche "):
                parts = [x.strip() for x in raw[len("recherche "):].split("|")]
                zone = parts[0]
                category = parts[1] if len(parts) > 1 and parts[1] else "all"
                radius = int(parts[2]) if len(parts) > 2 and parts[2] else 20
                max_results = int(parts[3]) if len(parts) > 3 and parts[3] else 50
                result = prospect_search_import(zone, category, radius, max_results, True)
                print(f"FEWURA PROSPECT : {result['found']} trouvés, {result['created']} créés, {result['updated']} mis à jour.")
            elif low.startswith("liste"):
                bits = raw.split(maxsplit=1); n = int(bits[1]) if len(bits) > 1 else 50; _show_rows(list_prospects(n))
            elif low.startswith("trouver "):
                _show_rows(search_prospects(raw[len("trouver "):]))
            elif low == "resume":
                print(crm_summary())
            elif low.startswith("statut "):
                _, sid, status = raw.split(maxsplit=2); print(update_prospect_status(int(sid), status))
            elif low.startswith("note "):
                _, sid, text = raw.split(maxsplit=2); print(add_note(int(sid), text))
            elif low.startswith("tache "):
                _, sid, text = raw.split(maxsplit=2); print(add_task(text, int(sid)))
            elif low == "export":
                print(export_prospects_csv())
            else:
                print("Commande inconnue. Tapez 'aide'.")
        except Exception as exc:
            print(f"Erreur : {exc}")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
