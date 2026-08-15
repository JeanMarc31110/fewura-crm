import asyncio
import os
import sys
from dotenv import load_dotenv
from agents import Agent, Runner

from fewura_crm.db import init_db
from fewura_crm.tools import TOOLS

load_dotenv()

SYSTEM_INSTRUCTIONS = """
Tu es FEWURA CRM Agent, assistant commercial local.

Objectifs:
- utiliser FEWURA PROSPECT comme moteur unique d'acquisition de nouveaux prospects;
- importer et enrichir automatiquement les entreprises trouvées dans le CRM;
- organiser les prospects, notes et tâches;
- retrouver rapidement les contacts déjà présents dans le CRM;
- résumer l'état du pipeline commercial et préparer les prochaines actions;
- conserver des données factuelles et ne jamais inventer un contact.

Règles d'utilisation des recherches:
- pour chercher de nouvelles entreprises dans une ville/zone/activité, utilise prospect_search_import;
- search_prospects sert uniquement à filtrer la base CRM déjà importée, jamais à découvrir de nouvelles entreprises;
- les recherches FEWURA PROSPECT doivent dédupliquer et mettre à jour les coordonnées sans écraser le statut commercial, les notes ou les tâches existantes;
- privilégie l'enrichissement des coordonnées publiques professionnelles quand l'utilisateur recherche des prospects.

Sécurité:
- utilise les outils CRM pour toute information provenant de la base;
- ne prétends jamais avoir modifié le CRM si aucun outil n'a été exécuté;
- une suppression nécessite une demande explicite de l'utilisateur et le mot de confirmation SUPPRIMER;
- ne lance jamais de diffusion massive, campagne e-mail ou WhatsApp sans validation humaine explicite;
- n'expose jamais de secrets ou clés API;
- privilégie les réponses courtes, opérationnelles et en français.
""".strip()

agent = Agent(
    name="FEWURA CRM Agent",
    model=os.getenv("AGENT_MODEL", "gpt-5.6-sol"),
    instructions=SYSTEM_INSTRUCTIONS,
    tools=TOOLS,
)


def self_test() -> int:
    init_db()
    tool_names = {getattr(tool, "name", "") for tool in agent.tools}
    checks = {
        "agent_name": agent.name == "FEWURA CRM Agent",
        "tools": len(agent.tools) >= 10,
        "fewura_prospect_engine": "prospect_search_import" in tool_names,
        "instructions": "FEWURA PROSPECT" in SYSTEM_INSTRUCTIONS,
    }
    print({"ok": all(checks.values()), "checks": checks})
    return 0 if all(checks.values()) else 2


async def main() -> None:
    init_db()
    print("FEWURA CRM Agent 1.1.0")
    print("Moteur d'acquisition: FEWURA PROSPECT")
    print("Tapez 'quit' pour quitter.\n")
    while True:
        message = input("Vous > ").strip()
        if message.lower() in {"quit", "exit", "q"}:
            break
        if not message:
            continue
        try:
            result = await Runner.run(agent, message)
            print("\nAgent >", result.final_output, "\n")
        except Exception as exc:
            print("\nErreur :", exc, "\n")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    asyncio.run(main())
