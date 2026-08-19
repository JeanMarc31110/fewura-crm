from __future__ import annotations

import html
from .time_utils import local_now, utc_sql_to_local_display
from urllib.parse import quote
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse

from .db import init_db, rows, one, execute, connect
from .tools import prospect_search_import, crm_summary, export_prospects_csv
from .sirene import LEGAL_FORM_LABELS
from .outreach import (
    create_campaign, create_campaign_for_selection, schedule_campaign, run_campaign, retry_errors, outreach_summary,
    smtp_status, sms_status, save_smtp, save_sms, test_sms_gateway, start_scheduler, gmail_status, test_gmail_connection,
    APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY, APPROVED_SMS_BODY,
)

VERSION = "1.4.4"
app = FastAPI(title="FEWURA CRM", version=VERSION)
_shutdown_requested = False
STATUSES = ["nouveau","a_contacter","contacte","qualifie","proposition","gagne","perdu","archive"]
CATEGORIES = ["all","restaurants","hotels","garages","immobilier","comptables","avocats","informatique","batiment","coiffure","sport","transport","commerce","artisanat","sante","beauté","formation","conseil","agence_immobiliere","automobile","logistique","nettoyage","securite","evenementiel"]
CATEGORY_LABELS = {"all":"Toutes les activités","restaurants":"Restaurants / cafés","hotels":"Hôtels / hébergements","garages":"Garages / réparation automobile","immobilier":"Immobilier","comptables":"Experts-comptables","avocats":"Avocats / juridique","informatique":"Informatique / numérique","batiment":"Bâtiment / travaux","coiffure":"Coiffure","sport":"Sport / fitness","transport":"Transport","commerce":"Commerce / magasins","artisanat":"Artisanat","sante":"Santé","beauté":"Beauté / bien-être","formation":"Formation / enseignement privé","conseil":"Conseil / services aux entreprises","agence_immobiliere":"Agences immobilières","automobile":"Automobile / concessionnaires","logistique":"Logistique / livraison","nettoyage":"Nettoyage","securite":"Sécurité","evenementiel":"Événementiel"}


def esc(v): return html.escape(str(v or ""), quote=True)

def display_timestamp(v): return utc_sql_to_local_display(v)

def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "database is locked" in text.lower() or "database table is locked" in text.lower():
        return "La base clients est momentanément occupée. Patientez quelques secondes puis réessayez."
    return text

def layout(body: str, title: str = "FEWURA CRM") -> str:
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f8;color:#1f2937;font-family:Segoe UI,Arial,sans-serif}}header{{background:#111827;color:#fff;padding:17px 24px;display:flex;justify-content:space-between;align-items:center;gap:10px}}header h1{{margin:0;font-size:24px}}header small{{color:#cbd5e1}}main{{max-width:1550px;margin:auto;padding:20px}}.tabs{{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}}.tabs a,.btn{{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:#2563eb;color:#fff;text-decoration:none;cursor:pointer;font-weight:600;font-size:13px}}.btn.secondary{{background:#475569}}.btn.danger{{background:#b91c1c}}.btn.success{{background:#15803d}}.btn.warn{{background:#b45309}}.btn.light{{background:#e2e8f0;color:#111827}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}}.card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px #0002;margin-bottom:15px}}.stats article{{background:#fff;padding:15px;border-radius:12px;box-shadow:0 1px 4px #0002}}.stats b{{font-size:27px;display:block}}label{{display:block;font-size:13px;font-weight:600;margin:8px 0}}input,select,textarea{{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:7px;margin-top:4px;background:#fff}}input[type=checkbox]{{width:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f8fafc;position:sticky;top:0}}.table-wrap{{overflow:auto;max-height:650px}}.toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.pill{{padding:3px 8px;border-radius:999px;background:#e2e8f0;display:inline-block}}.ok{{background:#dcfce7;color:#166534}}.bad{{background:#fee2e2;color:#991b1b}}.warnpill{{background:#fef3c7;color:#92400e}}.muted{{color:#64748b}}.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.notice{{padding:11px;border-radius:8px;background:#eff6ff;margin-bottom:12px}}.dangerbox{{background:#fee2e2}}pre{{white-space:pre-wrap}}@media(max-width:800px){{.row{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style></head><body><header><div><h1>FEWURA CRM</h1><small>CRM local + FEWURA PROSPECT + campagnes automatisées — v{VERSION}</small></div><button class="btn danger" id="quit">Quitter</button></header><main>
<div class="tabs"><a href="/">Tableau de bord</a><a href="/prospects">Contacts</a><a href="/prospect">FEWURA PROSPECT</a><a href="/campaigns">Campagnes</a><a href="/communications">Emails / SMS / historique</a><a href="/tasks">Tâches</a><a href="/settings">Paramètres</a></div>{body}</main>
<script>document.getElementById('quit').onclick=async()=>{{if(confirm('Quitter FEWURA CRM et arrêter complètement le programme ?')){{try{{await fetch('/shutdown',{{method:'POST'}})}}catch(e){{}}document.body.innerHTML='<main style="padding:40px"><h2>FEWURA CRM est arrêté.</h2><p>Vous pouvez fermer cette fenêtre.</p></main>';}}}};</script></body></html>'''

@app.on_event("startup")
def startup():
    init_db(); start_scheduler(lambda: _shutdown_requested, 15)

@app.get("/health")
def health(): return {"ok":True,"app":"FEWURA CRM","version":VERSION,"prospect_engine":"FEWURA PROSPECT","scheduler":True}

@app.get("/", response_class=HTMLResponse)
def dashboard():
    s=crm_summary(); o=outreach_summary(); recent=rows("SELECT * FROM prospects ORDER BY updated_at DESC,id DESC LIMIT 7")
    body='<section class="grid stats">'+''.join([
        f'<article><b>{s["prospects"]}</b><span>Prospects</span></article>',f'<article><b>{s["emails"]}</b><span>Avec email</span></article>',
        f'<article><b>{o["sent"]}</b><span>Messages envoyés</span></article>',f'<article><b>{o["scheduled"]}</b><span>Campagnes planifiées</span></article>',
        f'<article><b>{o["errors"]}</b><span>Erreurs d’envoi</span></article>',f'<article><b>{s["open_tasks"]}</b><span>Tâches ouvertes</span></article>'])+'</section>'
    body+='<section class="card"><h2>Pipeline commercial</h2><div class="toolbar">'+''.join(f'<span class="pill">{esc(x["status"])} : {x["n"]}</span>' for x in s['statuses'])+'</div></section>'
    sms=sms_status()
    body+='<div class="grid"><section class="card"><h2>Derniers contacts</h2>'+''.join(f'<p><a href="/prospects/{p["id"]}"><b>{esc(p["company_name"])}</b></a> — {esc(p.get("city"))} <span class="pill">{esc(p["status"])}</span></p>' for p in recent)+'</section>'
    body+='<section class="card"><h2>État des canaux</h2>'+('<p><span class="pill ok">SMTP configuré</span></p>' if smtp_status()['configured'] else '<p><span class="pill bad">SMTP à configurer</span></p>')+'<p><span class="pill ok">Expéditeur SMS fixé — +33 7 73 54 78 57</span></p>'+('<p><span class="pill ok">Passerelle téléphone connectée</span></p>' if sms['configured'] else '<p><span class="pill warnpill">Passerelle téléphone à connecter</span></p>')+'<p><a class="btn" href="/settings">Configurer les envois</a></p></section></div>'
    return layout(body)

@app.get("/prospects", response_class=HTMLResponse)
def prospects(q: str="", status: str=""):
    params=[]; where=[]
    where.append("(coalesce(email,'')<>'' OR coalesce(phone,'')<>'')")
    where.append("coalesce(status,'nouveau')<>'archive'")
    if q:
        like=f"%{q}%"; where.append("(company_name LIKE ? OR contact_name LIKE ? OR email LIKE ? OR phone LIKE ? OR city LIKE ? OR category LIKE ?)"); params += [like]*6
    if status: where.append("status=?"); params.append(status)
    data=rows("SELECT * FROM prospects"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY lead_score DESC,id DESC LIMIT 500",tuple(params))
    filt=f'''<form class="toolbar" method="get"><input style="max-width:320px" name="q" value="{esc(q)}" placeholder="Entreprise, contact, email, téléphone, ville"><select style="max-width:180px" name="status"><option value="">Tous statuts</option>{''.join(f'<option value="{x}" {"selected" if x==status else ""}>{x}</option>' for x in STATUSES)}</select><button class="btn">Filtrer</button><a class="btn light" href="/prospects">Réinitialiser</a><a class="btn secondary" href="/export/csv">Exporter CSV</a></form>'''
    toolbar='''<div class="toolbar"><button type="button" class="btn light" id="selall">Tout sélectionner</button><button type="button" class="btn light" id="clear">Désélectionner</button><span id="count">0 sélectionné</span><button class="btn success" form="bulk" formaction="/campaigns/from-selection">Créer un envoi depuis la sélection</button><button class="btn danger" form="bulk" formaction="/prospects/delete-selected">Supprimer la sélection</button><form method="post" action="/prospects/delete-all" onsubmit="return confirm('ATTENTION : supprimer TOUS les contacts ?')"><input type="hidden" name="confirmation" value="SUPPRIMER_TOUT"><button class="btn danger">Supprimer tout</button></form></div>'''
    trs=[]
    for p in data:
        opts=''.join(f'<option value="{x}" {"selected" if x==p["status"] else ""}>{x}</option>' for x in STATUSES)
        trs.append(f'''<tr><td><input class="pc" type="checkbox" name="ids" value="{p['id']}"></td><td><a href="/prospects/{p['id']}"><b>{esc(p['company_name'])}</b></a><br><span class="muted">{esc(p.get('contact_name'))}</span></td><td>{esc(p.get('city'))}<br>{esc(p.get('category'))}</td><td>{esc(p.get('email'))}<br>{esc(p.get('phone'))}</td><td>{esc(p.get('website'))}</td><td>{esc(p.get('lead_score'))}</td><td><form method="post" action="/prospects/{p['id']}/status"><select name="status" onchange="this.form.submit()">{opts}</select></form></td><td><form method="post" action="/prospects/{p['id']}/delete" onsubmit="return confirm('Supprimer ce contact ?')"><input type="hidden" name="confirmation" value="SUPPRIMER"><button class="btn danger">Supprimer</button></form></td></tr>''')
    body=f'<section class="card"><h2>Contacts / Prospects ({len(data)})</h2>{filt}{toolbar}<form id="bulk" method="post"><div class="table-wrap"><table><tr><th></th><th>Entreprise / contact</th><th>Ville / activité</th><th>Email / téléphone</th><th>Site</th><th>Score</th><th>Statut</th><th>Action</th></tr>{"".join(trs)}</table></div></form></section><script>const c=[...document.querySelectorAll(".pc")],n=document.getElementById("count");function r(){{let x=c.filter(z=>z.checked).length;n.textContent=x+" sélectionné"+(x>1?"s":"")}}c.forEach(z=>z.onchange=r);document.getElementById("selall").onclick=()=>{{c.forEach(z=>z.checked=true);r()}};document.getElementById("clear").onclick=()=>{{c.forEach(z=>z.checked=false);r()}};document.getElementById("bulk").onsubmit=e=>{{let x=c.filter(z=>z.checked).length;if(!x||!confirm("Supprimer "+x+" contact(s) sélectionné(s) ?"))e.preventDefault()}};</script>'
    return layout(body,'Contacts - FEWURA CRM')

@app.get("/prospects/{pid}", response_class=HTMLResponse)
def prospect_detail(pid:int):
    p=one("SELECT * FROM prospects WHERE id=?",(pid,))
    if not p: return layout('<section class="card"><h2>Prospect introuvable</h2></section>')
    notes=rows("SELECT * FROM notes WHERE prospect_id=? ORDER BY id DESC",(pid,)); tasks=rows("SELECT * FROM tasks WHERE prospect_id=? ORDER BY id DESC",(pid,)); comms=rows("SELECT * FROM communications WHERE prospect_id=? ORDER BY id DESC LIMIT 30",(pid,))
    body=f'''<section class="card"><h2>{esc(p['company_name'])}</h2><div class="grid"><div><p><b>Contact :</b> {esc(p.get('contact_name'))}</p><p><b>Email :</b> {esc(p.get('email'))}</p><p><b>Téléphone :</b> {esc(p.get('phone'))}</p><p><b>Site :</b> {esc(p.get('website'))}</p></div><div><p><b>Adresse :</b> {esc(p.get('address'))} {esc(p.get('postal_code'))} {esc(p.get('city'))}</p><p><b>Activité :</b> {esc(p.get('category'))}</p><p><b>Source :</b> {esc(p.get('source'))}</p><p><b>Score :</b> {esc(p.get('lead_score'))}</p></div></div></section>
<div class="grid"><section class="card"><h2>Notes</h2><form method="post" action="/prospects/{pid}/notes"><textarea name="body" required></textarea><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{display_timestamp(n["created_at"])}</b><br>{esc(n["body"])}</p>' for n in notes) or '<p>Aucune note.</p>'}</section><section class="card"><h2>Tâches</h2><form method="post" action="/prospects/{pid}/tasks"><label>Tâche<input name="title" required></label><label>Échéance<input type="datetime-local" name="due_at"></label><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{esc(t["title"])}</b> — {esc(t["status"])} {esc(t.get("due_at"))}</p>' for t in tasks) or '<p>Aucune tâche.</p>'}</section></div><section class="card"><h2>Historique communications</h2>{''.join(f'<p><b>{display_timestamp(c["created_at"])}</b> — {esc(c["channel"])} — {esc(c["status"])} — {esc(c["subject"])}</p>' for c in comms) or '<p>Aucune communication.</p>'}</section>'''
    return layout(body,p['company_name'])

@app.post("/prospects/{pid}/status")
def set_status(pid:int,status:str=Form(...)):
    if status in STATUSES: execute("UPDATE prospects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,pid))
    return RedirectResponse('/prospects',303)
@app.post("/prospects/{pid}/notes")
def add_note(pid:int,body:str=Form(...)): execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)",(pid,body.strip())); return RedirectResponse(f'/prospects/{pid}',303)
@app.post("/prospects/{pid}/tasks")
def add_task(pid:int,title:str=Form(...),due_at:str=Form("")): execute("INSERT INTO tasks(prospect_id,title,due_at) VALUES(?,?,?)",(pid,title.strip(),due_at or None)); return RedirectResponse(f'/prospects/{pid}',303)
@app.post("/prospects/{pid}/delete")
def delete_one(pid:int,confirmation:str=Form("")):
    if confirmation=="SUPPRIMER": execute("DELETE FROM prospects WHERE id=?",(pid,))
    return RedirectResponse('/prospects',303)
@app.post('/prospects/delete-selected')
def delete_selected(ids:list[int]=Form(default=[])):
    if ids:
        con=connect(); marks=','.join('?'*len(ids)); con.execute(f'DELETE FROM prospects WHERE id IN ({marks})',ids); con.commit(); con.close()
    return RedirectResponse('/prospects',303)
@app.post('/prospects/delete-all')
def delete_all(confirmation:str=Form("")):
    if confirmation=="SUPPRIMER_TOUT": execute("DELETE FROM prospects")
    return RedirectResponse('/prospects',303)

@app.get('/tasks',response_class=HTMLResponse)
def tasks_page():
    data=rows("SELECT t.*,p.company_name FROM tasks t LEFT JOIN prospects p ON p.id=t.prospect_id ORDER BY CASE WHEN t.status='terminee' THEN 1 ELSE 0 END,coalesce(t.due_at,'9999'),t.id DESC")
    body='<section class="card"><h2>Tâches</h2><div class="table-wrap"><table><tr><th>Tâche</th><th>Prospect</th><th>Échéance</th><th>État</th></tr>'+''.join(f'<tr><td>{esc(t["title"])}</td><td>{esc(t.get("company_name"))}</td><td>{esc(t.get("due_at"))}</td><td>{esc(t["status"])}</td></tr>' for t in data)+'</table></div></section>'
    return layout(body,'Tâches')

@app.get('/prospect',response_class=HTMLResponse)
def prospect_page(message:str=""):
    body=f'<section class="card"><h2>FEWURA PROSPECT</h2>{f"<div class=notice>{esc(message)}</div>" if message else ""}<div class="notice">Objectif : jusqu’à 400 contacts exploitables. FEWURA analyse des lots de 1 000 entreprises et continue jusqu’à atteindre l’objectif. Une relance reprend après les entreprises déjà analysées.</div><form method="post" action="/prospect/search"><div class="row"><label>Zone<input name="zone" required placeholder="Toulouse"></label><label>Activité<select name="category">'+''.join(f'<option value="{c}">{CATEGORY_LABELS.get(c,c)}</option>' for c in CATEGORIES)+'</select></label><label>Rayon km<input type="number" name="radius_km" value="20" min="1" max="50"></label><label>Objectif contacts<input type="number" name="max_results" value="400" min="1" max="400"></label></div><label>Coordonnées recherchées<select name="contact_mode"><option value="either">Email ou téléphone</option><option value="email">Email uniquement</option><option value="phone">Téléphone uniquement</option></select></label><label>Forme juridique<select name="legal_form">'+''.join(f'<option value="{f}">{LEGAL_FORM_LABELS[f]}</option>' for f in LEGAL_FORM_LABELS)+'</select></label><label><input type="checkbox" name="enrich" value="1" checked> Enrichir sites, emails et téléphones</label><button class="btn success">Rechercher et importer dans le CRM</button></form></section>'
    return layout(body,'FEWURA PROSPECT')
@app.post('/prospect/search')
def prospect_search(zone:str=Form(...),category:str=Form('all'),radius_km:int=Form(20),max_results:int=Form(50),enrich:str=Form(""),contact_mode:str=Form("either"),legal_form:str=Form("all")):
    try:
        r=prospect_search_import(zone,category,radius_km,max_results,enrich=='1',contact_mode=contact_mode,legal_form=legal_form); msg=f'{r["analyzed"]} analysés — {r["found"]} exploitables — {r["created"]} créés — {r["updated"]} mis à jour'
    except Exception as e: msg=f'Erreur : {e}'
    return RedirectResponse('/prospect?message='+__import__('urllib.parse').parse.quote(msg),303)

@app.get('/campaigns',response_class=HTMLResponse)
def campaigns_page(message:str=""):
    data=rows("SELECT c.*,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id) recipients,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id AND r.status='sent') sent,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id AND r.status='simulated') simulated,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id AND r.status='error') errors FROM campaigns c ORDER BY id DESC")
    notice=f'<div class="notice">{esc(message)}</div>' if message else ''
    form='''<section class="card"><h2>Nouvelle campagne</h2><div class="notice"><b>Modèles approuvés</b> : les contenus e-mail et SMS sont utilisés automatiquement. <b>Simulation</b> n'envoie rien. En mode réel : email si disponible, sinon SMS via le téléphone +33 7 73 54 78 57. Configurez SMTP/SMS dans Paramètres puis confirmez explicitement.</div><form method="post" action="/campaigns"><div class="row"><label>Nom<input name="name" required></label><label>Objet email<input name="subject" required readonly value="{APPROVED_EMAIL_SUBJECT}"></label><label>Activité<select name="category"><option value="">Toutes</option>'''+''.join(f'<option value="{c}">{CATEGORY_LABELS.get(c,c)}</option>' for c in CATEGORIES if c!='all')+'''</select></label><label>Ville<input name="city"></label><label>Score minimum<input type="number" name="min_score" value="0" min="0" max="100"></label><label>Mode<select name="mode"><option value="simulation">Simulation</option><option value="reel">Réel</option></select></label><label>Programmer date/heure<input type="datetime-local" name="scheduled_at"></label></div><label><input type="checkbox" name="confirm_real" value="OUI"> Je confirme que le mode réel peut envoyer des emails et SMS</label><button class="btn success">Créer la campagne</button></form></section>'''
    table='<section class="card"><h2>Campagnes</h2><div class="notice"><b>Simuler</b> prépare les messages sans les envoyer. <b>Envoyer réellement</b> transmet les messages par Gmail ou SMS après votre confirmation.</div><div class="table-wrap"><table><tr><th>Nom</th><th>Mode</th><th>Planifiée</th><th>État</th><th>Dest.</th><th>Simulés</th><th>Envoyés</th><th>Erreurs</th><th>Actions</th></tr>'+''.join(f'''<tr><td>{esc(c['name'])}</td><td>{esc(c['mode'])}</td><td>{display_timestamp(c.get('scheduled_at'))}</td><td>{esc(c['status'])}</td><td>{c['recipients']}</td><td>{c['simulated']}</td><td>{c['sent']}</td><td>{c['errors']}</td><td><form method="post" action="/campaigns/{c['id']}/run" style="display:inline"><input type="hidden" name="force_mode" value="simulation"><button class="btn">Simuler</button></form> <form method="post" action="/campaigns/{c['id']}/run" style="display:inline" onsubmit="return confirm('Envoyer réellement cette campagne maintenant ?');"><input type="hidden" name="force_mode" value="reel"><input type="hidden" name="confirm_real" value="OUI"><button class="btn success">Envoyer réellement</button></form> <form method="post" action="/campaigns/{c['id']}/retry" style="display:inline"><button class="btn warn">Réessayer erreurs</button></form></td></tr>''' for c in data)+'</table></div></section>'
    return layout(notice+form+table,'Campagnes')

@app.post('/campaigns/from-selection', response_class=HTMLResponse)
def campaign_from_selection(ids:list[int]=Form(default=[])):
    ids = list(dict.fromkeys(int(pid) for pid in ids if int(pid) > 0))
    ids = [pid for pid in ids if one("SELECT id FROM prospects WHERE id=? AND (coalesce(email,'')<>'' OR coalesce(phone,'')<>'')", (pid,))]
    if not ids:
        return layout('<section class="card dangerbox"><h2>Aucun prospect exploitable</h2><p>Les prospects doivent avoir au moins un e-mail ou un téléphone.</p></section>')
    hidden = ''.join(f'<input type="hidden" name="ids" value="{pid}">' for pid in ids)
    body = f'''<section class="card"><h2>Envoi direct — {len(ids)} prospect(s) sélectionné(s)</h2>
<div class="notice">Choisissez le canal puis envoyez directement. <b>Tester sans envoyer</b> crée uniquement un aperçu dans l’historique.</div>
<form method="post" action="/campaigns/from-selection/send" onsubmit="if(event.submitter && event.submitter.value==='send' && !confirm('Envoyer réellement les messages aux prospects sélectionnés ?')) return false; const buttons=this.querySelectorAll('button'); setTimeout(()=>buttons.forEach(b=>b.disabled=true),0);">{hidden}
<label>Canal<select name="channel"><option value="auto">Automatique (email puis SMS)</option><option value="email">Email uniquement</option><option value="sms">SMS uniquement</option></select></label>
<label>Objet email<input name="subject" required value="{esc(APPROVED_EMAIL_SUBJECT)}"></label>
<div class="notice">Les modèles e-mail et SMS approuvés sont utilisés automatiquement selon le canal choisi.</div>
<label><input type="checkbox" name="confirm_real" value="OUI"> Je confirme l’envoi réel aux prospects sélectionnés</label>
<button class="btn secondary" type="submit" name="action" value="simulate">Tester sans envoyer</button> <button class="btn success" type="submit" name="action" value="send">Envoyer maintenant</button> <a class="btn light" href="/prospects">Annuler</a></form></section>'''
    return layout(body,'Envoi ciblé')

@app.post('/campaigns/from-selection/send')
def campaign_from_selection_send(
    ids:list[int]=Form(default=[]), subject:str=Form(APPROVED_EMAIL_SUBJECT),
    channel:str=Form('auto'), action:str=Form(''), confirm_real:str=Form('')
):
    if action not in {'simulate','send'}:
        return layout('<section class="card dangerbox"><h2>Action invalide</h2><p>Aucun message n’a été envoyé.</p></section>')
    if action == 'send' and confirm_real != 'OUI':
        return layout('<section class="card dangerbox"><h2>Confirmation requise</h2><p>Aucun message n’a été envoyé. Cochez la confirmation avant l’envoi réel.</p><p><a class="btn light" href="/prospects">Retour aux contacts</a></p></section>')
    mode = 'reel' if action == 'send' else 'simulation'
    label = local_now().strftime('Envoi direct %d/%m/%Y %H:%M:%S')
    try:
        cid=create_campaign_for_selection(label, subject, APPROVED_EMAIL_BODY, ids, channel, mode, '', APPROVED_SMS_BODY)
        result=run_campaign(cid, mode)
        if mode == 'reel':
            message=(f'Envoi direct terminé : {result["sent"]} envoyé(s), '
                     f'{result["skipped"]} contact(s) sans coordonnée adaptée, '
                     f'{result["errors"]} erreur(s).')
        else:
            message=(f'Test terminé sans envoi : {result["simulated"]} message(s) préparé(s), '
                     f'{result["skipped"]} contact(s) sans coordonnée adaptée, '
                     f'{result["errors"]} erreur(s).')
    except Exception as exc:
        message=f'Envoi impossible : {friendly_error(exc)}'
    return RedirectResponse('/communications?message='+quote(message),303)

@app.post('/campaigns/from-selection/create')
def campaign_from_selection_create(
    ids:list[int]=Form(default=[]), name:str=Form(...), subject:str=Form(APPROVED_EMAIL_SUBJECT),
    channel:str=Form('auto'), mode:str=Form('simulation'), scheduled_at:str=Form(''), confirm_real:str=Form('')
):
    if mode == 'reel' and confirm_real != 'OUI':
        return layout('<section class="card dangerbox"><h2>Confirmation requise</h2><p>Le mode réel doit être confirmé.</p></section>')
    try:
        cid=create_campaign_for_selection(name, subject, APPROVED_EMAIL_BODY, ids, channel, mode, scheduled_at, APPROVED_SMS_BODY)
        message=f'Campagne {cid} créée pour {len(set(ids))} prospect(s).'
    except Exception as exc:
        message=f'Création impossible : {friendly_error(exc)}'
    return RedirectResponse('/campaigns?message='+quote(message),303)

@app.post('/campaigns')
def campaign_create(name:str=Form(...),subject:str=Form(APPROVED_EMAIL_SUBJECT),body:str=Form(APPROVED_EMAIL_BODY),category:str=Form(""),city:str=Form(""),min_score:int=Form(0),mode:str=Form('simulation'),scheduled_at:str=Form(""),confirm_real:str=Form("")):
    if mode=='reel' and confirm_real!='OUI': return layout('<section class="card dangerbox"><h2>Confirmation requise</h2><p>Le mode réel doit être confirmé.</p></section>')
    try:
        cid=create_campaign(name,APPROVED_EMAIL_SUBJECT,APPROVED_EMAIL_BODY,category,city,min_score,mode,scheduled_at,APPROVED_SMS_BODY)
        message=f'Campagne {cid} créée.'
    except Exception as exc:
        message=f'Création impossible : {friendly_error(exc)}'
    return RedirectResponse('/campaigns?message='+quote(message),303)
@app.post('/campaigns/{cid}/run')
def campaign_run(cid:int,force_mode:str=Form(""),confirm_real:str=Form("")):
    c=one("SELECT mode FROM campaigns WHERE id=?",(cid,))
    if not c:
        return RedirectResponse('/campaigns?message='+quote('Campagne introuvable.'),303)
    if force_mode and force_mode not in {'simulation','reel'}:
        return RedirectResponse('/campaigns?message='+quote('Mode d’exécution invalide.'),303)
    effective_mode=force_mode or c['mode']
    if effective_mode=='reel' and confirm_real!='OUI':
        return layout('<section class="card dangerbox"><h2>Confirmation requise</h2><p>L’envoi réel n’a pas été lancé.</p></section>')
    try:
        result=run_campaign(cid,force_mode or None)
        mode_label='réel' if result['mode']=='reel' else 'simulation'
        message=(f'Campagne {cid} exécutée en mode {mode_label} : {result["sent"]} envoyé(s), '
                 f'{result["simulated"]} simulé(s), {result["errors"]} erreur(s).')
    except Exception as exc:
        message=f'Exécution impossible : {exc}'
    return RedirectResponse('/campaigns?message='+quote(message),303)
@app.post('/campaigns/{cid}/retry')
def campaign_retry(cid:int):
    try:
        retry_errors(cid)
        message=f'Les erreurs de la campagne {cid} sont prêtes à être réessayées.'
    except Exception as exc:
        message=f'Relance impossible : {exc}'
    return RedirectResponse('/campaigns?message='+quote(message),303)

@app.get('/communications',response_class=HTMLResponse)
def communications_page(message:str=""):
    data=rows("SELECT c.*,p.company_name,ca.name campaign_name FROM communications c LEFT JOIN prospects p ON p.id=c.prospect_id LEFT JOIN campaigns ca ON ca.id=c.campaign_id ORDER BY c.id DESC LIMIT 1000")
    notice=f'<div class="notice">{esc(message)}</div>' if message else ''
    body=notice+'<section class="card"><h2>Emails / SMS / historique des communications</h2><div class="table-wrap"><table><tr><th>Date</th><th>Prospect</th><th>Campagne</th><th>Canal</th><th>Statut</th><th>Destinataire</th><th>Objet</th><th>Erreur</th></tr>'+''.join(f'<tr><td>{display_timestamp(x["created_at"])}</td><td>{esc(x.get("company_name"))}</td><td>{esc(x.get("campaign_name"))}</td><td>{esc(x["channel"])}</td><td>{esc(x["status"])}</td><td>{esc(x.get("recipient"))}</td><td>{esc(x.get("subject"))}</td><td>{esc(x.get("error"))}</td></tr>' for x in data)+'</table></div></section>'
    return layout(body,'Historique')

@app.get('/settings',response_class=HTMLResponse)
def settings_page(message:str=""):
    s=smtp_status(); sms=sms_status(); gmail=gmail_status()
    gmail_class='ok' if gmail['configured'] else 'warnpill'
    gmail_label='connecté' if gmail['configured'] else 'à connecter'
    gmail_token='oui' if gmail['token_file_found'] else 'non'
    gmail_credentials='oui' if gmail['client_id_found'] and gmail['client_secret_found'] else 'non'
    msg=f'<div class="notice">{esc(message)}</div>' if message else ''
    sirene_row=one("SELECT value FROM settings WHERE key='sirene_api_key'")
    sirene_configured=bool(sirene_row and sirene_row.get("value"))
    body=msg+f'''<section class="card"><h2>Gmail OAuth</h2><p>FEWURA CRM reprend automatiquement l'autorisation Gmail de l'ancien agent si elle est présente sur ce PC.</p><p><span class="pill {gmail_class}">Gmail OAuth : {gmail_label}</span></p><p class="muted">Compte détecté : {esc(gmail['account'])}<br>Jeton local : {gmail_token}<br>Identifiants OAuth locaux : {gmail_credentials}</p><form method="post" action="/settings/gmail/test"><button class="btn secondary">Tester la connexion Gmail</button></form></section><div class="grid"><section class="card"><h2>Email SMTP</h2><p class="muted">Le mot de passe reste dans la base locale de FEWURA CRM. La configuration de l'ancien FEWURA est reprise automatiquement si elle existe.</p><form method="post" action="/settings/smtp"><label>Serveur SMTP<input name="host" value="{esc(s['host'])}" placeholder="smtp.gmail.com"></label><div class="row"><label>Port<input type="number" name="port" value="{s['port']}"></label><label>Sécurité<select name="security"><option value="starttls" {"selected" if s['security']=="starttls" else ""}>STARTTLS</option><option value="ssl" {"selected" if s['security']=="ssl" else ""}>SSL</option><option value="none" {"selected" if s['security']=="none" else ""}>Aucune</option></select></label></div><label>Utilisateur<input name="username" value="{esc(s['username'])}"></label><label>Mot de passe / mot de passe d'application<input type="password" name="password" placeholder="laisser vide pour conserver"></label><label>Email expéditeur<input type="email" name="from_email" value="{esc(s['from_email'])}"></label><label>Nom expéditeur<input name="from_name" value="{esc(s['from_name'])}"></label><button class="btn success">Enregistrer SMTP</button></form></section><section class="card"><h2>SMS via votre téléphone Android</h2><p><span class="pill ok">Expéditeur SMS déjà configuré : <b>+33 7 73 54 78 57</b></span></p><p>Si un contact n'a pas d'email mais possède un téléphone, FEWURA CRM lui envoie automatiquement un SMS depuis cette SIM.</p><p class="muted">Il n'y a rien à configurer pour le numéro expéditeur. Configurez uniquement la liaison avec FEWURA SMS Gateway sur le téléphone.</p><form method="post" action="/settings/sms"><label>Adresse de la passerelle<input name="gateway_url" value="{esc(sms['gateway_url'])}" placeholder="http://192.168.1.25:8765"></label><label>Jeton de sécurité<input type="password" name="token" placeholder="laisser vide pour conserver"></label><div class="row"><label>Limite SMS / jour<input type="number" name="daily_limit" min="1" max="500" value="{sms['daily_limit']}"></label><label>Délai entre SMS (secondes)<input type="number" name="delay_seconds" min="0" max="300" value="{sms['delay_seconds']}"></label></div><button class="btn success">Enregistrer la passerelle SMS</button></form><form method="post" action="/settings/sms/test" style="margin-top:10px"><button class="btn secondary">Tester la connexion au téléphone</button></form><p><span class="pill {'ok' if sms['configured'] else 'warnpill'}">Passerelle téléphone : {'configurée' if sms['configured'] else 'à connecter'}</span></p></section></div>'''
    body += f'''<section class="card"><h2>Registre SIRENE / INSEE</h2><p class="muted">FEWURA PROSPECT consulte d'abord le registre officiel SIRENE, puis recherche le site et les coordonnées publiques par scraping. La clé reste dans la base locale et n'est jamais affichée.</p><p><span class="pill {'ok' if sirene_configured else 'warnpill'}">Clé API SIRENE : {'configurée' if sirene_configured else 'à configurer'}</span></p><form method="post" action="/settings/sirene"><label>Clé API SIRENE<input type="password" name="api_key" placeholder="Coller la clé API INSEE"></label><button class="btn success">Enregistrer la clé SIRENE</button></form></section>'''
    return layout(body,'Paramètres')
@app.post('/settings/sirene')
def settings_sirene(api_key:str=Form("")):
    init_db()
    execute("INSERT INTO settings(key,value) VALUES('sirene_api_key',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (api_key.strip(),))
    return RedirectResponse('/settings',303)
@app.post('/settings/smtp')
def settings_smtp(host:str=Form(""),port:int=Form(587),username:str=Form(""),password:str=Form(""),from_email:str=Form(""),from_name:str=Form("FEWURA CRM"),security:str=Form("starttls")): save_smtp(host,port,username,password,from_email,from_name,security); return RedirectResponse('/settings',303)
@app.post('/settings/sms')
def settings_sms(gateway_url:str=Form(""),token:str=Form(""),daily_limit:int=Form(20),delay_seconds:int=Form(10)): save_sms(gateway_url,token,daily_limit,delay_seconds); return RedirectResponse('/settings',303)
@app.post('/settings/gmail/test')
def settings_gmail_test():
    try:
        data=test_gmail_connection(); message='Gmail OAuth connecté : '+str(data.get('account') or 'OK')
    except Exception as exc:
        message='Erreur Gmail OAuth : '+str(exc)
    return RedirectResponse('/settings?message='+__import__('urllib.parse').parse.quote(message),303)

@app.post('/settings/sms/test')
def settings_sms_test():
    try: data=test_sms_gateway(); message='Passerelle SMS connectée : '+str(data.get('app') or 'OK')
    except Exception as exc: message='Erreur passerelle SMS : '+str(exc)
    return RedirectResponse('/settings?message='+__import__('urllib.parse').parse.quote(message),303)

@app.get('/export/csv')
def export_csv():
    result=export_prospects_csv(); return FileResponse(result['path'],filename='fewura-crm-prospects.csv',media_type='text/csv')
@app.post('/shutdown')
def shutdown():
    global _shutdown_requested; _shutdown_requested=True; return JSONResponse({'ok':True})
def shutdown_requested()->bool: return _shutdown_requested



