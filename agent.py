import asyncio
import getpass
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from agents import Agent, Runner

from fewura_crm.db import init_db
from fewura_crm.paths import data_dir
from fewura_crm.tools import TOOLS

VERSION = "1.1.0"


def _load_local_env() -> Path:
    env_path = data_dir() / ".env"
    load_dotenv(env_path, override=False)
    load_dotenv(override=False)
    return env_path


def _ensure_openai_key() -> bool:
    env_path = _load_local_env()
    if os.getenv("OPENAI_API_KEY", "").strip():
        return True
    if "--self-test" in sys.argv:
        return True
    print("\nPremière configuration FEWURA CRM")
    print("Une clé OpenAI API est nécessaire pour l'assistant conversationnel.")
    print("La clé sera enregistrée uniquement dans votre dossier local FEWURA CRM.\n")
    try:
        key = getpass.getpass("Clé OpenAI API : ").strip()
    except Exception:
        key = input("Clé OpenAI API : ").strip()
    if not key:
        print("Aucune clé fournie. FEWURA CRM ne peut pas lancer l'assistant.")
        return False
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(f"OPENAI_API_KEY={key}\nAGENT_MODEL=gpt-5.6-sol\n", encoding="utf-8")
    os.environ["OPENAI_API_KEY"] = key
    print(f"Configuration enregistrée dans {env_path}\n")
    return True


_load_local_env()

SYSTEM_INSTRUCTIONS = """
Tu es FEWURA CRM Agent, assistant commercial local.

Objectifs:
- aider à organiser les prospects, notes et tâches;
- retrouver rapidement les contacts;
- utiliser FEWURA PROSPECT comme moteur d'acquisition de nouvelles entreprises;
- importer et enrichir les résultats dans le CRM sans écraser l'avancement commercial existant;
- résumer l'état du pipeline commercial;
- préparer les prochaines actions commerciales;
- conserver des données factuelles et ne jamais inventer un contact.

Règles:
- utilise les outils CRM pour toute information provenant de la base;
- pour trouver de nouvelles entreprises, utilise le moteur FEWURA PROSPECT intégré au CRM;
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
        "tools": len(agent.tools) >= 10,
        "instructions": bool(SYSTEM_INSTRUCTIONS),
        "data_dir": data_dir().exists(),
        "version": VERSION == "1.1.0",
    }
    print({"ok": all(checks.values()), "checks": checks, "version": VERSION})
    return 0 if all(checks.values()) else 2


async def main() -> None:
    init_db()
    if not _ensure_openai_key():
        input("Appuyez sur Entrée pour fermer...")
        return
    print(f"FEWURA CRM Agent {VERSION}")
    print("Moteur d'acquisition : FEWURA PROSPECT")
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
