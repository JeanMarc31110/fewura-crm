from __future__ import annotations

import html
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse

from .db import init_db, rows, one, execute, connect
from .tools import prospect_search_import, crm_summary, export_prospects_csv
from .outreach import (
    create_campaign, schedule_campaign, run_campaign, retry_errors, outreach_summary,
    smtp_status, whatsapp_status, save_smtp, save_whatsapp, start_scheduler,
)

VERSION = "1.3.0"
app = FastAPI(title="FEWURA CRM", version=VERSION)
_shutdown_requested = False
STATUSES = ["nouveau","a_contacter","contacte","qualifie","proposition","gagne","perdu","archive"]
CATEGORIES = ["all","restaurants","hotels","garages","immobilier","comptables","avocats","informatique","batiment","coiffure","sport","transport"]


def esc(v): return html.escape(str(v or ""), quote=True)

def layout(body: str, title: str = "FEWURA CRM") -> str:
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f8;color:#1f2937;font-family:Segoe UI,Arial,sans-serif}}header{{background:#111827;color:#fff;padding:17px 24px;display:flex;justify-content:space-between;align-items:center;gap:10px}}header h1{{margin:0;font-size:24px}}header small{{color:#cbd5e1}}main{{max-width:1550px;margin:auto;padding:20px}}.tabs{{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}}.tabs a,.btn{{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:#2563eb;color:#fff;text-decoration:none;cursor:pointer;font-weight:600;font-size:13px}}.btn.secondary{{background:#475569}}.btn.danger{{background:#b91c1c}}.btn.success{{background:#15803d}}.btn.warn{{background:#b45309}}.btn.light{{background:#e2e8f0;color:#111827}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}}.card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px #0002;margin-bottom:15px}}.stats article{{background:#fff;padding:15px;border-radius:12px;box-shadow:0 1px 4px #0002}}.stats b{{font-size:27px;display:block}}label{{display:block;font-size:13px;font-weight:600;margin:8px 0}}input,select,textarea{{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:7px;margin-top:4px;background:#fff}}input[type=checkbox]{{width:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f8fafc;position:sticky;top:0}}.table-wrap{{overflow:auto;max-height:650px}}.toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.pill{{padding:3px 8px;border-radius:999px;background:#e2e8f0;display:inline-block}}.ok{{background:#dcfce7;color:#166534}}.bad{{background:#fee2e2;color:#991b1b}}.warnpill{{background:#fef3c7;color:#92400e}}.muted{{color:#64748b}}.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.notice{{padding:11px;border-radius:8px;background:#eff6ff;margin-bottom:12px}}.dangerbox{{background:#fee2e2}}pre{{white-space:pre-wrap}}@media(max-width:800px){{.row{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style></head><body><header><div><h1>FEWURA CRM</h1><small>CRM local + FEWURA PROSPECT + campagnes automatisées — v{VERSION}</small></div><button class="btn danger" id="quit">Quitter</button></header><main>
<div class="tabs"><a href="/">Tableau de bord</a><a href="/prospects">Contacts</a><a href="/prospect">FEWURA PROSPECT</a><a href="/campaigns">Campagnes</a><a href="/communications">Emails / historique</a><a href="/tasks">Tâches</a><a href="/settings">Paramètres</a></div>{body}</main>
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
    body+='<div class="grid"><section class="card"><h2>Derniers contacts</h2>'+''.join(f'<p><a href="/prospects/{p["id"]}"><b>{esc(p["company_name"])}</b></a> — {esc(p.get("city"))} <span class="pill">{esc(p["status"])}</span></p>' for p in recent)+'</section>'
    body+='<section class="card"><h2>État des canaux</h2>'+('<p><span class="pill ok">SMTP configuré</span></p>' if smtp_status()['configured'] else '<p><span class="pill bad">SMTP à configurer</span></p>')+('<p><span class="pill ok">WhatsApp Cloud configuré</span></p>' if whatsapp_status()['configured'] else '<p><span class="pill warnpill">WhatsApp Cloud optionnel</span></p>')+'<p><a class="btn" href="/settings">Configurer les envois</a></p></section></div>'
    return layout(body)

@app.get("/prospects", response_class=HTMLResponse)
def prospects(q:str="",status:str=""):
    params=[]; where=[]
    if q:
        like=f"%{q}%"; where.append("(company_name LIKE ? OR contact_name LIKE ? OR email LIKE ? OR phone LIKE ? OR city LIKE ? OR category LIKE ?)"); params += [like]*6
    if status: where.append("status=?"); params.append(status)
    data=rows("SELECT * FROM prospects"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY lead_score DESC,id DESC LIMIT 500",tuple(params))
    opts_filter=''.join(f'<option value="{x}" {"selected" if x==status else ""}>{x}</option>' for x in STATUSES)
    trs=[]
    for p in data:
        opts=''.join(f'<option value="{x}" {"selected" if x==p["status"] else ""}>{x}</option>' for x in STATUSES)
        trs.append(f'''<tr><td><input class="pc" type="checkbox" name="ids" value="{p['id']}"></td><td><b>{esc(p['company_name'])}</b><br><span class="muted">{esc(p.get('contact_name'))}</span></td><td>{esc(p.get('city'))}<br>{esc(p.get('category'))}</td><td>{esc(p.get('email'))}<br>{esc(p.get('phone'))}</td><td>{esc(p.get('website'))}</td><td><b>{esc(p.get('lead_score'))}</b></td><td><form method="post" action="/prospects/{p['id']}/status"><select name="status" onchange="this.form.submit()">{opts}</select></form></td><td><a class="btn light" href="/prospects/{p['id']}">Ouvrir</a> <button class="btn danger" form="one{p['id']}">Supprimer</button><form id="one{p['id']}" method="post" action="/prospects/{p['id']}/delete" onsubmit="return confirm('Supprimer ce contact ?')"><input type="hidden" name="confirmation" value="SUPPRIMER"></form></td></tr>''')
    body=f'''<section class="card"><h2>Contacts / Prospects ({len(data)})</h2><form class="toolbar" method="get"><input style="max-width:320px" name="q" value="{esc(q)}" placeholder="Entreprise, email, téléphone, ville"><select style="max-width:180px" name="status"><option value="">Tous statuts</option>{opts_filter}</select><button class="btn">Filtrer</button><a class="btn light" href="/prospects">Réinitialiser</a><a class="btn secondary" href="/export/csv">CSV</a></form>
<div class="toolbar"><button type="button" class="btn light" id="selall">Tout sélectionner</button><button type="button" class="btn light" id="clear">Désélectionner</button><span id="count">0 sélectionné</span><button class="btn danger" form="bulk">Supprimer la sélection</button><form method="post" action="/prospects/delete-all" onsubmit="return confirm('ATTENTION : supprimer TOUS les contacts ?')"><input type="hidden" name="confirmation" value="SUPPRIMER_TOUT"><button class="btn danger">Supprimer tout</button></form></div>
<form id="bulk" method="post" action="/prospects/delete-selected"><div class="table-wrap"><table><thead><tr><th></th><th>Entreprise</th><th>Ville / activité</th><th>Email / téléphone</th><th>Site</th><th>Score</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div></form></section>
<script>const c=[...document.querySelectorAll('.pc')],n=document.getElementById('count');function r(){{let x=c.filter(z=>z.checked).length;n.textContent=x+' sélectionné'+(x>1?'s':'')}}c.forEach(z=>z.onchange=r);document.getElementById('selall').onclick=()=>{{c.forEach(z=>z.checked=true);r()}};document.getElementById('clear').onclick=()=>{{c.forEach(z=>z.checked=false);r()}};document.getElementById('bulk').onsubmit=e=>{{let x=c.filter(z=>z.checked).length;if(!x||!confirm('Supprimer '+x+' contact(s) ?'))e.preventDefault()}};</script>'''
    return layout(body,"Contacts - FEWURA CRM")

@app.get("/prospects/{pid}",response_class=HTMLResponse)
def prospect_detail(pid:int):
    p=one("SELECT * FROM prospects WHERE id=?",(pid,))
    if not p: return layout('<section class="card"><h2>Prospect introuvable</h2></section>')
    notes=rows("SELECT * FROM notes WHERE prospect_id=? ORDER BY id DESC",(pid,)); tasks=rows("SELECT * FROM tasks WHERE prospect_id=? ORDER BY id DESC",(pid,)); comms=rows("SELECT * FROM communications WHERE prospect_id=? ORDER BY id DESC LIMIT 30",(pid,))
    body=f'''<section class="card"><h2>{esc(p['company_name'])}</h2><div class="grid"><div><p><b>Contact :</b> {esc(p.get('contact_name'))}</p><p><b>Email :</b> {esc(p.get('email'))}</p><p><b>Téléphone :</b> {esc(p.get('phone'))}</p><p><b>Site :</b> {esc(p.get('website'))}</p></div><div><p><b>Adresse :</b> {esc(p.get('address'))} {esc(p.get('postal_code'))} {esc(p.get('city'))}</p><p><b>Activité :</b> {esc(p.get('category'))}</p><p><b>Source :</b> {esc(p.get('source'))}</p><p><b>Score :</b> {esc(p.get('lead_score'))}</p></div></div></section>
<div class="grid"><section class="card"><h2>Notes</h2><form method="post" action="/prospects/{pid}/notes"><textarea name="body" required></textarea><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{esc(n["created_at"])}</b><br>{esc(n["body"])}</p>' for n in notes) or '<p>Aucune note.</p>'}</section><section class="card"><h2>Tâches</h2><form method="post" action="/prospects/{pid}/tasks"><label>Tâche<input name="title" required></label><label>Échéance<input type="datetime-local" name="due_at"></label><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{esc(t["title"])}</b> — {esc(t["status"])} {esc(t.get("due_at"))}</p>' for t in tasks) or '<p>Aucune tâche.</p>'}</section></div>
<section class="card"><h2>Historique des communications</h2><div class="table-wrap"><table><tr><th>Date</th><th>Canal</th><th>État</th><th>Destinataire</th><th>Objet</th><th>Erreur</th></tr>{''.join(f'<tr><td>{esc(c["created_at"])}</td><td>{esc(c["channel"])}</td><td>{esc(c["status"])}</td><td>{esc(c.get("recipient"))}</td><td>{esc(c.get("subject"))}</td><td>{esc(c.get("error"))}</td></tr>' for c in comms)}</table></div></section>'''
    return layout(body,p['company_name'])

@app.post('/prospects/{pid}/status')
def set_status(pid:int,status:str=Form(...)):
    if status in STATUSES: execute("UPDATE prospects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,pid))
    return RedirectResponse('/prospects',303)
@app.post('/prospects/{pid}/notes')
def add_note(pid:int,body:str=Form(...)): execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)",(pid,body.strip())); return RedirectResponse(f'/prospects/{pid}',303)
@app.post('/prospects/{pid}/tasks')
def add_task(pid:int,title:str=Form(...),due_at:str=Form("")): execute("INSERT INTO tasks(prospect_id,title,due_at) VALUES(?,?,?)",(pid,title.strip(),due_at or None)); return RedirectResponse(f'/prospects/{pid}',303)
@app.post('/prospects/{pid}/delete')
def delete_one(pid:int,confirmation:str=Form(...)):
    if confirmation=='SUPPRIMER':
        con=connect(); con.execute("DELETE FROM prospects WHERE id=?",(pid,)); con.commit(); con.close()
    return RedirectResponse('/prospects',303)
@app.post('/prospects/delete-selected')
def delete_selected(ids:list[int]=Form(default=[])):
    if ids:
        con=connect(); con.executemany("DELETE FROM prospects WHERE id=?",[(i,) for i in ids]); con.commit(); con.close()
    return RedirectResponse('/prospects',303)
@app.post('/prospects/delete-all')
def delete_all(confirmation:str=Form(...)):
    if confirmation=='SUPPRIMER_TOUT':
        con=connect(); con.execute("DELETE FROM prospects"); con.commit(); con.close()
    return RedirectResponse('/prospects',303)

@app.get('/tasks',response_class=HTMLResponse)
def tasks_page():
    data=rows("SELECT t.*,p.company_name FROM tasks t LEFT JOIN prospects p ON p.id=t.prospect_id ORDER BY CASE WHEN t.status='terminee' THEN 1 ELSE 0 END,coalesce(t.due_at,'9999'),t.id DESC")
    body='<section class="card"><h2>Tâches</h2><table><tr><th>Tâche</th><th>Prospect</th><th>Échéance</th><th>État</th><th></th></tr>'+''.join(f'<tr><td>{esc(t["title"])}</td><td>{esc(t.get("company_name"))}</td><td>{esc(t.get("due_at"))}</td><td>{esc(t["status"])}</td><td>'+(f'<form method="post" action="/tasks/{t["id"]}/complete"><button class="btn light">Terminer</button></form>' if t['status']!='terminee' else '')+'</td></tr>' for t in data)+'</table></section>'
    return layout(body,'Tâches')
@app.post('/tasks/{tid}/complete')
def complete_task(tid:int): execute("UPDATE tasks SET status='terminee' WHERE id=?",(tid,)); return RedirectResponse('/tasks',303)

@app.get('/prospect',response_class=HTMLResponse)
def prospect_page():
    cats=''.join(f'<option value="{x}">{x}</option>' for x in CATEGORIES)
    body=f'''<section class="card"><h2>FEWURA PROSPECT — acquisition</h2><p class="notice">Les entreprises trouvées sont importées ou enrichies dans le CRM sans écraser le pipeline commercial.</p><form method="post" action="/prospect/search"><div class="row"><label>Zone<input name="zone" required placeholder="Toulouse"></label><label>Activité<select name="category">{cats}</select></label></div><div class="row"><label>Rayon km<input type="number" name="radius_km" value="20" min="1" max="50"></label><label>Maximum<input type="number" name="max_results" value="50" min="1" max="100"></label></div><label><input type="checkbox" name="enrich" value="true" checked> Enrichir sites et emails professionnels publics</label><button class="btn">Rechercher et importer</button></form></section>'''
    return layout(body,'FEWURA PROSPECT')
@app.post('/prospect/search',response_class=HTMLResponse)
def prospect_search(zone:str=Form(...),category:str=Form('all'),radius_km:int=Form(20),max_results:int=Form(50),enrich:str=Form("")):
    try:
        r=prospect_search_import(zone,category,radius_km,max_results,enrich=='true'); body=f'<section class="card"><h2>Résultat FEWURA PROSPECT</h2><p><b>{r["found"]}</b> trouvés — <b>{r["created"]}</b> créés — <b>{r["updated"]}</b> mis à jour.</p><a class="btn" href="/prospects">Voir les contacts</a> <a class="btn light" href="/prospect">Nouvelle recherche</a></section>'
    except Exception as e: body=f'<section class="card dangerbox"><h2>Erreur</h2><p>{esc(e)}</p><a class="btn" href="/prospect">Retour</a></section>'
    return layout(body,'Résultat prospection')

@app.get('/campaigns',response_class=HTMLResponse)
def campaigns_page():
    data=rows("SELECT c.*,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id) recipients,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id AND r.status='sent') sent,(SELECT count(*) FROM campaign_recipients r WHERE r.campaign_id=c.id AND r.status='error') errors FROM campaigns c ORDER BY c.id DESC")
    cats=''.join(f'<option value="{x if x!="all" else ""}">{x}</option>' for x in CATEGORIES)
    body=f'''<div class="grid"><section class="card"><h2>Nouvelle campagne</h2><form method="post" action="/campaigns"><label>Nom<input name="name" required></label><div class="row"><label>Activité<select name="category"><option value="">Toutes</option>{cats}</select></label><label>Ville<input name="city"></label></div><label>Score minimum<input type="number" name="min_score" value="0" min="0" max="100"></label><label>Objet<input name="subject" value="Une solution pour {{entreprise}}" required></label><label>Message<textarea name="body" rows="9" required>Bonjour {{contact}},\n\nNous souhaitons vous présenter notre solution pour {{entreprise}} à {{ville}}.\n\nCordialement,\nFEWURA</textarea></label><div class="row"><label>Mode<select name="mode"><option value="simulation">Simulation (aucun envoi)</option><option value="reel">Réel</option></select></label><label>Programmer pour<input type="datetime-local" name="scheduled_at"></label></div><label><input type="checkbox" name="confirm_real" value="OUI"> Je confirme que si je choisis Réel, les messages pourront être envoyés automatiquement à l'heure programmée.</label><button class="btn">Créer la campagne</button></form></section>
<section class="card"><h2>Règles d'envoi</h2><p>Priorité : <b>email</b>. Si aucun email mais un téléphone est disponible : <b>WhatsApp Cloud</b>.</p><p>Chaque prospect n'est inséré qu'une fois par campagne. Une ligne déjà envoyée n'est jamais renvoyée automatiquement.</p><p>Le mode simulation écrit dans l'historique sans contacter personne.</p></section></div>
<section class="card"><h2>Campagnes</h2><div class="table-wrap"><table><tr><th>Nom</th><th>État</th><th>Mode</th><th>Programmation</th><th>Dest.</th><th>Envoyés</th><th>Erreurs</th><th></th></tr>{''.join(f'<tr><td><b>{esc(c["name"])}</b></td><td>{esc(c["status"])}</td><td>{esc(c["mode"])}</td><td>{esc(c.get("scheduled_at"))}</td><td>{c["recipients"]}</td><td>{c["sent"]}</td><td>{c["errors"]}</td><td><a class="btn light" href="/campaigns/{c["id"]}">Ouvrir</a></td></tr>' for c in data)}</table></div></section>'''
    return layout(body,'Campagnes')

@app.post('/campaigns')
def campaign_create(name:str=Form(...),subject:str=Form(...),body:str=Form(...),category:str=Form(""),city:str=Form(""),min_score:int=Form(0),mode:str=Form('simulation'),scheduled_at:str=Form(""),confirm_real:str=Form("")):
    if mode=='reel' and confirm_real!='OUI': return HTMLResponse(layout('<section class="card dangerbox"><h2>Confirmation requise</h2><p>Une campagne réelle doit être explicitement confirmée.</p><a class="btn" href="/campaigns">Retour</a></section>'),400)
    cid=create_campaign(name,subject,body,category,city,min_score,mode,scheduled_at)
    return RedirectResponse(f'/campaigns/{cid}',303)

@app.get('/campaigns/{cid}',response_class=HTMLResponse)
def campaign_detail(cid:int):
    c=one("SELECT * FROM campaigns WHERE id=?",(cid,))
    if not c: return layout('<section class="card"><h2>Campagne introuvable</h2></section>')
    rs=rows("SELECT cr.*,p.company_name,p.email,p.phone FROM campaign_recipients cr JOIN prospects p ON p.id=cr.prospect_id WHERE cr.campaign_id=? ORDER BY cr.id",(cid,))
    counts={r['status']:0 for r in rs}
    for r in rs: counts[r['status']]=counts.get(r['status'],0)+1
    body=f'''<section class="card"><h2>{esc(c['name'])}</h2><p><b>État :</b> {esc(c['status'])} — <b>Mode :</b> {esc(c['mode'])} — <b>Programmation :</b> {esc(c.get('scheduled_at'))}</p><p><b>Objet :</b> {esc(c['subject'])}</p><pre>{esc(c['body'])}</pre><div class="toolbar"><span class="pill">pending {counts.get('pending',0)}</span><span class="pill ok">sent {counts.get('sent',0)}</span><span class="pill">simulated {counts.get('simulated',0)}</span><span class="pill bad">error {counts.get('error',0)}</span></div>
<form style="display:inline" method="post" action="/campaigns/{cid}/run" onsubmit="return confirm('Exécuter maintenant cette campagne ?')"><input type="hidden" name="confirm_real" value="OUI"><button class="btn success">Exécuter maintenant</button></form> <form style="display:inline" method="post" action="/campaigns/{cid}/retry"><button class="btn warn">Réessayer les erreurs</button></form></section>
<section class="card"><h2>Reprogrammer</h2><form method="post" action="/campaigns/{cid}/schedule"><div class="row"><label>Date / heure<input type="datetime-local" name="scheduled_at" required value="{esc(c.get('scheduled_at'))}"></label><label>Mode<select name="mode"><option value="simulation" {"selected" if c['mode']=='simulation' else ''}>Simulation</option><option value="reel" {"selected" if c['mode']=='reel' else ''}>Réel</option></select></label></div><label><input type="checkbox" name="confirm_real" value="OUI"> Confirmation pour mode réel</label><button class="btn">Enregistrer la programmation</button></form></section>
<section class="card"><h2>Destinataires</h2><div class="table-wrap"><table><tr><th>Entreprise</th><th>Email</th><th>Téléphone</th><th>Canal</th><th>État</th><th>Tentatives</th><th>Erreur</th></tr>{''.join(f'<tr><td>{esc(r["company_name"])}</td><td>{esc(r.get("email"))}</td><td>{esc(r.get("phone"))}</td><td>{esc(r["channel"])}</td><td>{esc(r["status"])}</td><td>{r["attempts"]}</td><td>{esc(r.get("last_error"))}</td></tr>' for r in rs)}</table></div></section>'''
    return layout(body,c['name'])

@app.post('/campaigns/{cid}/run')
def campaign_run(cid:int,confirm_real:str=Form("")):
    c=one("SELECT * FROM campaigns WHERE id=?",(cid,))
    if c and c['mode']=='reel' and confirm_real!='OUI': return HTMLResponse(layout('<section class="card dangerbox"><h2>Confirmation requise</h2></section>'),400)
    run_campaign(cid); return RedirectResponse(f'/campaigns/{cid}',303)
@app.post('/campaigns/{cid}/retry')
def campaign_retry(cid:int): retry_errors(cid); return RedirectResponse(f'/campaigns/{cid}',303)
@app.post('/campaigns/{cid}/schedule')
def campaign_schedule(cid:int,scheduled_at:str=Form(...),mode:str=Form(...),confirm_real:str=Form("")):
    if mode=='reel' and confirm_real!='OUI': return HTMLResponse(layout('<section class="card dangerbox"><h2>Confirmation requise pour un envoi réel.</h2></section>'),400)
    schedule_campaign(cid,scheduled_at,mode); return RedirectResponse(f'/campaigns/{cid}',303)

@app.get('/communications',response_class=HTMLResponse)
def communications_page():
    data=rows("SELECT cm.*,p.company_name,c.name campaign_name FROM communications cm LEFT JOIN prospects p ON p.id=cm.prospect_id LEFT JOIN campaigns c ON c.id=cm.campaign_id ORDER BY cm.id DESC LIMIT 1000")
    body='<section class="card"><h2>Emails / WhatsApp / historique</h2><div class="table-wrap"><table><tr><th>Date</th><th>Entreprise</th><th>Campagne</th><th>Canal</th><th>État</th><th>Destinataire</th><th>Objet</th><th>Erreur</th></tr>'+''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x.get("company_name"))}</td><td>{esc(x.get("campaign_name"))}</td><td>{esc(x["channel"])}</td><td>{esc(x["status"])}</td><td>{esc(x.get("recipient"))}</td><td>{esc(x.get("subject"))}</td><td>{esc(x.get("error"))}</td></tr>' for x in data)+'</table></div></section>'
    return layout(body,'Historique des envois')

@app.get('/settings',response_class=HTMLResponse)
def settings_page():
    s=smtp_status(); w=whatsapp_status()
    body=f'''<div class="grid"><section class="card"><h2>Email SMTP</h2><p>{'<span class="pill ok">Configuré</span>' if s['configured'] else '<span class="pill bad">Non configuré</span>'}</p><form method="post" action="/settings/smtp"><div class="row"><label>Serveur SMTP<input name="host" value="{esc(s['host'])}" placeholder="smtp.gmail.com"></label><label>Port<input type="number" name="port" value="{s['port']}"></label></div><label>Utilisateur<input name="username" value="{esc(s['username'])}"></label><label>Mot de passe / mot de passe d'application<input type="password" name="password" placeholder="Laisser vide pour conserver l'actuel"></label><div class="row"><label>Email expéditeur<input type="email" name="from_email" value="{esc(s['from_email'])}" required></label><label>Nom expéditeur<input name="from_name" value="{esc(s['from_name'])}"></label></div><label>Sécurité<select name="security"><option value="starttls" {"selected" if s['security']=='starttls' else ''}>STARTTLS</option><option value="ssl" {"selected" if s['security']=='ssl' else ''}>SSL/TLS</option><option value="none" {"selected" if s['security']=='none' else ''}>Aucune</option></select></label><button class="btn">Enregistrer SMTP</button></form></section>
<section class="card"><h2>Meta WhatsApp Business Cloud</h2><p>{'<span class="pill ok">Configuré</span>' if w['configured'] else '<span class="pill warnpill">Optionnel / non configuré</span>'}</p><p>Utilisé automatiquement uniquement si le prospect n'a pas d'email mais possède un téléphone.</p><form method="post" action="/settings/whatsapp"><label>Phone Number ID<input name="phone_number_id" value="{esc(w['phone_number_id'])}"></label><label>Access Token<input type="password" name="token" placeholder="Laisser vide pour conserver l'actuel"></label><button class="btn">Enregistrer WhatsApp</button></form></section></div>
<section class="card"><h2>Sécurité d'envoi</h2><p>Une campagne réelle nécessite une confirmation explicite. Les secrets sont enregistrés uniquement dans la base locale FEWURA CRM sur ce PC. GitHub et FEWURA PROSPECT ne reçoivent pas ces identifiants.</p></section>'''
    return layout(body,'Paramètres')
@app.post('/settings/smtp')
def settings_smtp(host:str=Form(...),port:int=Form(...),username:str=Form(""),password:str=Form(""),from_email:str=Form(...),from_name:str=Form("FEWURA CRM"),security:str=Form("starttls")):
    save_smtp(host,port,username,password,from_email,from_name,security); return RedirectResponse('/settings',303)
@app.post('/settings/whatsapp')
def settings_whatsapp(phone_number_id:str=Form(""),token:str=Form("")):
    save_whatsapp(phone_number_id,token); return RedirectResponse('/settings',303)

@app.get('/export/csv')
def export_csv():
    r=export_prospects_csv(); return FileResponse(r['path'],filename='fewura-crm-prospects.csv',media_type='text/csv')
@app.post('/shutdown')
def shutdown():
    global _shutdown_requested; _shutdown_requested=True; return JSONResponse({'ok':True})
def shutdown_requested()->bool: return _shutdown_requested
