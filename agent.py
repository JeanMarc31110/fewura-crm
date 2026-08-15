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
- aider à organiser les prospects, notes et tâches;
- retrouver rapidement les contacts;
- résumer l'état du pipeline commercial;
- préparer les prochaines actions commerciales;
- conserver des données factuelles et ne jamais inventer un contact.

Règles:
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
    checks = {
        "agent_name": agent.name == "FEWURA CRM Agent",
        "tools": len(agent.tools) >= 9,
        "instructions": bool(SYSTEM_INSTRUCTIONS),
    }
    print({"ok": all(checks.values()), "checks": checks})
    return 0 if all(checks.values()) else 2


async def main() -> None:
    init_db()
    print("FEWURA CRM Agent 1.0.0")
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
