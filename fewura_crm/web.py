from __future__ import annotations

import html
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse

from .db import init_db, rows, one, execute, connect
from .tools import prospect_search_import, crm_summary, export_prospects_csv

app = FastAPI(title="FEWURA CRM", version="1.2.0")
_shutdown_requested = False

STATUSES = ["nouveau","a_contacter","contacte","qualifie","proposition","gagne","perdu","archive"]
CATEGORIES = ["all","restaurants","hotels","garages","immobilier","comptables","avocats","informatique","batiment","coiffure","sport","transport"]


def esc(v):
    return html.escape(str(v or ""), quote=True)


def layout(body: str, title: str = "FEWURA CRM") -> str:
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#1d2430;font-family:Segoe UI,Arial,sans-serif}}header{{background:#111827;color:white;padding:18px 24px;display:flex;justify-content:space-between;align-items:center}}header h1{{margin:0;font-size:24px}}header small{{color:#cbd5e1}}main{{max-width:1500px;margin:auto;padding:22px}}.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}}.tabs a,.btn{{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:#2563eb;color:white;text-decoration:none;cursor:pointer;font-weight:600}}.btn.secondary{{background:#475569}}.btn.danger{{background:#b91c1c}}.btn.light{{background:#e2e8f0;color:#111827}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}}.card{{background:white;border-radius:12px;padding:16px;box-shadow:0 1px 3px #0002;margin-bottom:16px}}.stats article{{background:white;padding:15px;border-radius:12px;box-shadow:0 1px 3px #0002}}.stats b{{font-size:28px;display:block}}label{{display:block;font-size:13px;font-weight:600;margin:8px 0}}input,select,textarea{{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:7px;margin-top:4px;background:white}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f8fafc;position:sticky;top:0}}.table-wrap{{overflow:auto;max-height:620px}}.toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.pill{{padding:3px 8px;border-radius:999px;background:#e2e8f0}}.flash{{padding:10px;border-radius:8px;background:#dcfce7;margin-bottom:12px}}.dangerbox{{background:#fee2e2}}.muted{{color:#64748b}}.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.actions form{{display:inline}}details{{max-width:380px}}@media(max-width:800px){{.row{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style></head><body><header><div><h1>FEWURA CRM</h1><small>CRM local + moteur FEWURA PROSPECT — aucune clé API</small></div><button class="btn danger" id="quit">Quitter</button></header><main>
<div class="tabs"><a href="/">Tableau de bord</a><a href="/prospects">Contacts / Prospects</a><a href="/tasks">Tâches</a><a href="/prospect">FEWURA PROSPECT</a></div>{body}</main>
<script>document.getElementById('quit').onclick=async()=>{{if(confirm('Quitter FEWURA CRM et arrêter complètement le programme ?')){{try{{await fetch('/shutdown',{{method:'POST'}})}}catch(e){{}}document.body.innerHTML='<main style="padding:40px"><h2>FEWURA CRM est arrêté.</h2><p>Vous pouvez fermer cette fenêtre.</p></main>';}}}};</script></body></html>'''


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    s = crm_summary()
    recent = rows("SELECT * FROM prospects ORDER BY updated_at DESC,id DESC LIMIT 8")
    tasks = rows("SELECT t.*,p.company_name FROM tasks t LEFT JOIN prospects p ON p.id=t.prospect_id WHERE t.status<>'terminee' ORDER BY coalesce(t.due_at,'9999'),t.id LIMIT 8")
    body = '<section class="grid stats">' + ''.join([
        f'<article><b>{s["prospects"]}</b><span>Contacts / prospects</span></article>',
        f'<article><b>{s["fewura_prospect"]}</b><span>Importés par FEWURA PROSPECT</span></article>',
        f'<article><b>{s["emails"]}</b><span>Avec email</span></article>',
        f'<article><b>{s["phones"]}</b><span>Avec téléphone</span></article>',
        f'<article><b>{s["open_tasks"]}</b><span>Tâches ouvertes</span></article>']) + '</section>'
    body += '<section class="card"><h2>Pipeline commercial</h2><div class="toolbar">' + ''.join(f'<span class="pill">{esc(x["status"])} : {x["n"]}</span>' for x in s['statuses']) + '</div></section>'
    body += '<div class="grid"><section class="card"><h2>Derniers contacts</h2>' + ''.join(f'<p><b>{esc(p["company_name"])}</b> — {esc(p["city"])} <span class="pill">{esc(p["status"])}</span></p>' for p in recent) + '</section>'
    body += '<section class="card"><h2>Prochaines tâches</h2>' + (''.join(f'<p><b>{esc(t["title"])}</b> — {esc(t.get("company_name"))} <span class="muted">{esc(t.get("due_at"))}</span></p>' for t in tasks) or '<p>Aucune tâche ouverte.</p>') + '</section></div>'
    return layout(body)


@app.get("/prospects", response_class=HTMLResponse)
def prospects(q: str = "", status: str = ""):
    init_db(); params=[]; where=[]
    if q:
        like=f"%{q}%"; where.append("(company_name LIKE ? OR contact_name LIKE ? OR email LIKE ? OR phone LIKE ? OR city LIKE ? OR category LIKE ?)"); params += [like]*6
    if status:
        where.append("status=?"); params.append(status)
    sql="SELECT * FROM prospects" + (" WHERE "+" AND ".join(where) if where else "") + " ORDER BY lead_score DESC,id DESC LIMIT 500"
    data=rows(sql,tuple(params))
    filt=f'''<form class="toolbar" method="get"><input style="max-width:320px" name="q" value="{esc(q)}" placeholder="Entreprise, contact, email, téléphone, ville"><select style="max-width:180px" name="status"><option value="">Tous statuts</option>{''.join(f'<option value="{x}" {"selected" if x==status else ""}>{x}</option>' for x in STATUSES)}</select><button class="btn">Filtrer</button><a class="btn light" href="/prospects">Réinitialiser</a><a class="btn secondary" href="/export/csv">Exporter CSV</a></form>'''
    toolbar='''<div class="toolbar"><button type="button" class="btn light" id="selall">Tout sélectionner</button><button type="button" class="btn light" id="clear">Désélectionner</button><span id="count">0 sélectionné</span><button class="btn danger" form="bulk" formaction="/prospects/delete-selected">Supprimer la sélection</button><form method="post" action="/prospects/delete-all" onsubmit="return confirm('ATTENTION : supprimer TOUS les contacts ?')"><input type="hidden" name="confirmation" value="SUPPRIMER_TOUT"><button class="btn danger">Supprimer tout</button></form></div>'''
    trs=[]
    for p in data:
        opts=''.join(f'<option value="{x}" {"selected" if x==p["status"] else ""}>{x}</option>' for x in STATUSES)
        trs.append(f'''<tr><td><input class="pc" type="checkbox" name="ids" value="{p['id']}"></td><td><b>{esc(p['company_name'])}</b><br><span class="muted">{esc(p.get('contact_name'))}</span></td><td>{esc(p.get('city'))}<br>{esc(p.get('category'))}</td><td>{esc(p.get('email'))}<br>{esc(p.get('phone'))}</td><td>{esc(p.get('website'))}</td><td><b>{esc(p.get('lead_score'))}</b></td><td><form method="post" action="/prospects/{p['id']}/status"><select name="status" onchange="this.form.submit()">{opts}</select></form></td><td class="actions"><a class="btn light" href="/prospects/{p['id']}">Ouvrir</a> <form method="post" action="/prospects/{p['id']}/delete" onsubmit="return confirm('Supprimer {esc(p['company_name'])} ?')"><input type="hidden" name="confirmation" value="SUPPRIMER"><button class="btn danger">Supprimer</button></form></td></tr>''')
    body=f'<section class="card"><h2>Contacts / Prospects ({len(data)})</h2>{filt}{toolbar}<form id="bulk" method="post"><div class="table-wrap"><table><thead><tr><th></th><th>Entreprise / contact</th><th>Ville / activité</th><th>Email / téléphone</th><th>Site</th><th>Score</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div></form></section><script>const c=[...document.querySelectorAll(".pc")],n=document.getElementById("count");function r(){{let x=c.filter(z=>z.checked).length;n.textContent=x+" sélectionné"+(x>1?"s":"")}}c.forEach(z=>z.onchange=r);document.getElementById("selall").onclick=()=>{{c.forEach(z=>z.checked=true);r()}};document.getElementById("clear").onclick=()=>{{c.forEach(z=>z.checked=false);r()}};document.getElementById("bulk").onsubmit=e=>{{let x=c.filter(z=>z.checked).length;if(!x||!confirm("Supprimer "+x+" contact(s) sélectionné(s) ?"))e.preventDefault()}};</script>'
    return layout(body,"Contacts - FEWURA CRM")


@app.get("/prospects/{pid}", response_class=HTMLResponse)
def prospect_detail(pid: int):
    p=one("SELECT * FROM prospects WHERE id=?",(pid,))
    if not p: return layout('<section class="card"><h2>Prospect introuvable</h2></section>')
    notes=rows("SELECT * FROM notes WHERE prospect_id=? ORDER BY id DESC",(pid,)); tasks=rows("SELECT * FROM tasks WHERE prospect_id=? ORDER BY id DESC",(pid,))
    body=f'''<section class="card"><h2>{esc(p['company_name'])}</h2><div class="grid"><div><p><b>Contact :</b> {esc(p.get('contact_name'))}</p><p><b>Email :</b> {esc(p.get('email'))}</p><p><b>Téléphone :</b> {esc(p.get('phone'))}</p><p><b>Site :</b> {esc(p.get('website'))}</p></div><div><p><b>Adresse :</b> {esc(p.get('address'))} {esc(p.get('postal_code'))} {esc(p.get('city'))}</p><p><b>Activité :</b> {esc(p.get('category'))}</p><p><b>Source :</b> {esc(p.get('source'))}</p><p><b>Score :</b> {esc(p.get('lead_score'))}</p></div></div></section>
<div class="grid"><section class="card"><h2>Notes</h2><form method="post" action="/prospects/{pid}/notes"><textarea name="body" required placeholder="Ajouter une note"></textarea><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{esc(n["created_at"])}</b><br>{esc(n["body"])}</p>' for n in notes) or '<p>Aucune note.</p>'}</section>
<section class="card"><h2>Tâches</h2><form method="post" action="/prospects/{pid}/tasks"><label>Tâche<input name="title" required></label><label>Échéance<input type="datetime-local" name="due_at"></label><button class="btn">Ajouter</button></form>{''.join(f'<p><b>{esc(t["title"])}</b> — {esc(t["status"])} {esc(t.get("due_at"))} '+(f'<form style="display:inline" method="post" action="/tasks/{t["id"]}/complete"><button class="btn light">Terminer</button></form>' if t['status']!='terminee' else '')+'</p>' for t in tasks) or '<p>Aucune tâche.</p>'}</section></div>'''
    return layout(body,p['company_name'])


@app.post("/prospects/{pid}/status")
def set_status(pid:int,status:str=Form(...)):
    if status in STATUSES: execute("UPDATE prospects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,pid))
    return RedirectResponse('/prospects',303)

@app.post("/prospects/{pid}/notes")
def add_note_route(pid:int,body:str=Form(...)):
    execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)",(pid,body.strip())); return RedirectResponse(f'/prospects/{pid}',303)

@app.post("/prospects/{pid}/tasks")
def add_task_route(pid:int,title:str=Form(...),due_at:str=Form("")):
    execute("INSERT INTO tasks(prospect_id,title,due_at) VALUES(?,?,?)",(pid,title.strip(),due_at or None)); return RedirectResponse(f'/prospects/{pid}',303)

@app.post("/tasks/{tid}/complete")
def complete_task_route(tid:int):
    t=one("SELECT prospect_id FROM tasks WHERE id=?",(tid,)); execute("UPDATE tasks SET status='terminee' WHERE id=?",(tid,)); return RedirectResponse(f'/prospects/{t["prospect_id"]}' if t and t.get('prospect_id') else '/tasks',303)

@app.get('/tasks',response_class=HTMLResponse)
def tasks_page():
    data=rows("SELECT t.*,p.company_name FROM tasks t LEFT JOIN prospects p ON p.id=t.prospect_id ORDER BY CASE WHEN t.status='terminee' THEN 1 ELSE 0 END,coalesce(t.due_at,'9999'),t.id DESC")
    body='<section class="card"><h2>Tâches</h2><div class="table-wrap"><table><tr><th>Tâche</th><th>Prospect</th><th>Échéance</th><th>État</th><th></th></tr>'+''.join(f'<tr><td>{esc(t["title"])}</td><td>{esc(t.get("company_name"))}</td><td>{esc(t.get("due_at"))}</td><td>{esc(t["status"])}</td><td>'+(f'<form method="post" action="/tasks/{t["id"]}/complete"><button class="btn light">Terminer</button></form>' if t['status']!='terminee' else '')+'</td></tr>' for t in data)+'</table></div></section>'
    return layout(body,'Tâches - FEWURA CRM')

@app.post('/prospects/{pid}/delete')
def delete_one(pid:int,confirmation:str=Form(...)):
    if confirmation=='SUPPRIMER': execute('DELETE FROM prospects WHERE id=?',(pid,))
    return RedirectResponse('/prospects',303)

@app.post('/prospects/delete-selected')
async def delete_selected(request:Request):
    form=await request.form(); ids=[int(x) for x in form.getlist('ids') if str(x).isdigit()]
    if ids:
        con=connect(); con.executemany('DELETE FROM prospects WHERE id=?',[(x,) for x in ids]); con.commit(); con.close()
    return RedirectResponse('/prospects',303)

@app.post('/prospects/delete-all')
def delete_all(confirmation:str=Form(...)):
    if confirmation=='SUPPRIMER_TOUT': execute('DELETE FROM prospects')
    return RedirectResponse('/prospects',303)

@app.get('/prospect',response_class=HTMLResponse)
def prospect_page(message:str=''):
    body=f'''{f'<div class="flash">{esc(message)}</div>' if message else ''}<section class="card"><h2>FEWURA PROSPECT — recherche et import CRM</h2><form method="post" action="/prospect/search"><div class="row"><label>Zone<input name="zone" value="Toulouse" required></label><label>Type<select name="category">{''.join(f'<option value="{c}">{c}</option>' for c in CATEGORIES)}</select></label></div><div class="row"><label>Rayon km<input type="number" name="radius_km" min="1" max="50" value="20"></label><label>Maximum<input type="number" name="max_results" min="1" max="100" value="50"></label></div><label><input style="width:auto" type="checkbox" name="enrich" value="true" checked> Enrichir les emails et sites professionnels publics</label><button class="btn">Rechercher et importer dans le CRM</button></form></section>'''
    return layout(body,'FEWURA PROSPECT - CRM')

@app.post('/prospect/search')
def run_prospect(zone:str=Form(...),category:str=Form('all'),radius_km:int=Form(20),max_results:int=Form(50),enrich:str|None=Form(None)):
    try:
        r=prospect_search_import(zone,category,radius_km,max_results,enrich=='true')
        msg=f"{r['found']} trouvés — {r['created']} nouveaux — {r['updated']} mis à jour."
    except Exception as exc:
        msg=f"Erreur de recherche : {exc}"
    from urllib.parse import quote
    return RedirectResponse('/prospect?message='+quote(msg),303)

@app.get('/export/csv')
def export_csv():
    result=export_prospects_csv(); return FileResponse(result['path'],filename='fewura-crm-prospects.csv',media_type='text/csv')

@app.post('/shutdown')
def shutdown():
    global _shutdown_requested; _shutdown_requested=True
    return JSONResponse({'ok':True})

def shutdown_requested()->bool:
    return _shutdown_requested
