# FEWURA CRM Agent

Agent CRM local conçu selon les standards AURELIA FORGE.

## Mission
FEWURA CRM Agent utilise désormais **FEWURA PROSPECT comme moteur unique d'acquisition**. Une recherche de nouvelles entreprises passe par FEWURA PROSPECT, puis les résultats sont importés ou fusionnés directement dans le CRM.

## Acquisition FEWURA PROSPECT
Le moteur intégré reprend les fonctions de FEWURA PROSPECT :
- géocodage Nominatim ;
- recherche Overpass avec plusieurs serveurs de secours ;
- catégories métiers FEWURA ;
- découverte du site officiel quand il manque ;
- extraction d'e-mails professionnels publics et de téléphones ;
- scoring des leads ;
- dédoublonnage ;
- import/merge automatique dans le CRM.

La commande agent correspondante est `prospect_search_import(zone, category, radius_km, max_results, enrich)`.

`search_prospects` reste uniquement un filtre des fiches **déjà présentes dans le CRM** ; il n'est plus considéré comme un moteur de prospection.

## Adaptation CRM
Lorsqu'une entreprise existe déjà, une nouvelle recherche FEWURA PROSPECT :
- actualise/enrichit email, téléphone, site, adresse, localisation, source et score ;
- conserve le statut commercial actuel ;
- conserve le nom de contact saisi manuellement ;
- conserve toutes les notes et tâches.

## Principes
- données CRM locales sous `%LOCALAPPDATA%\FEWURA\CRM` sous Windows ;
- aucune suppression massive sans confirmation explicite ;
- aucune campagne ou diffusion massive automatisée par défaut ;
- les opérations destructives restent soumises à validation humaine ;
- architecture compatible avec les standards de génération d'agents de Forge.

## Installation Windows (clients distants)

Le dépôt publie désormais un installateur EXE Windows professionnel :

- télécharger le fichier `FEWURA_CRM_Setup.exe` depuis la release GitHub
- lancer l’installateur en mode standard ou silencieux (`/SILENT /NORESTART`)
- l’application est installée dans `C:\Program Files\FEWURA CRM`
- renommer `.env.example` en `.env` et renseigner `OPENAI_API_KEY` si nécessaire

### Installations silencieuses

- `FEWURA_CRM_Setup.exe /SILENT /NORESTART`
- ou via le script PowerShell : `install-client-pro.ps1`

## Développement
1. Copier `.env.example` vers `.env` et renseigner `OPENAI_API_KEY`.
2. `install.bat`
3. `start.bat`

## Commandes agent
L'agent peut notamment :
- rechercher de nouveaux prospects avec FEWURA PROSPECT et les importer ;
- lister et filtrer les prospects du CRM ;
- créer ou modifier un prospect ;
- ajouter des notes ;
- ajouter ou terminer des tâches ;
- produire un résumé commercial ;
- exporter les prospects en CSV.

## Tests
`python -m pytest -q`

Les tests vérifient notamment la requête `Toulouse + hotels` et la conservation du pipeline CRM lors d'un ré-enrichissement FEWURA PROSPECT.

## Forge
Le fichier `forge_manifest.json` décrit l'Agent DNA de FEWURA CRM et déclare FEWURA PROSPECT comme moteur d'acquisition.
