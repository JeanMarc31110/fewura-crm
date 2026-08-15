# FEWURA CRM Agent

Agent CRM local conçu selon les standards AURELIA FORGE.

## Mission
FEWURA CRM Agent centralise les prospects, notes et tâches commerciales, aide à prioriser les leads et fournit une interface conversationnelle locale pilotée par OpenAI Agents SDK.

## Principes
- données CRM locales sous `%LOCALAPPDATA%\FEWURA\CRM` sous Windows ;
- aucune suppression massive sans confirmation explicite ;
- aucune campagne ou diffusion massive automatisée par défaut ;
- les opérations destructives restent soumises à validation humaine ;
- architecture compatible avec les standards de génération d'agents de Forge.

## Développement
1. Copier `.env.example` vers `.env` et renseigner `OPENAI_API_KEY`.
2. `install.bat`
3. `start.bat`

## Commandes agent
L'agent peut notamment :
- lister et rechercher les prospects ;
- créer ou modifier un prospect ;
- ajouter des notes ;
- ajouter ou terminer des tâches ;
- produire un résumé commercial ;
- exporter les prospects en CSV.

## Tests
`python -m pytest -q`

## Forge
Le fichier `forge_manifest.json` décrit l'Agent DNA de FEWURA CRM.
