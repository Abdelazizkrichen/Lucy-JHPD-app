"""Lucy — Job scraping (Vercel)
Sources légales: France Travail (API officielle) + Adzuna (API officielle)
               + APEC (API publique organisme paritaire) + Indeed RSS + Cadremploi RSS
"""
import json, urllib.request, urllib.parse, ssl, time, gzip, re
from http.server import BaseHTTPRequestHandler

SSL = ssl.create_default_context()
SSL.check_hostname = False
SSL.verify_mode = ssl.CERT_NONE
CORS = {"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"}

FT_APP = "PAR_lucyjobhunter_b4ed148e50022211273f40b6f755af73ece7c4b284eb27ed260ec3104fe697af"
FT_SEC = "9270acaa586d9a752533dc92163a1c127c976eddd5ad9aa6f889759d1e68e62b"
AZ_ID  = "cbe5b72d"
AZ_KEY = "74845cedd88ff4283ce7ec02f573d733"
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0 Safari/537.36"

FT_CONTRACT = {"CDI":"CDI","CDD":"CDD","freelance":"MIS","stage":"STA","alternance":"CTA","professionalisation":"CPI","POEI":"CDI"}
AZ_CONTRACT = {"CDI":"permanent","CDD":"contract","freelance":"contract","stage":"internship","alternance":"apprenticeship","professionalisation":"apprenticeship","POEI":"permanent"}

_ft_cache = {"tok": None, "exp": 0}

def fetch(url, hdrs=None, data=None, timeout=12):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept-Encoding", "gzip")
    req.add_header("Accept-Language", "fr-FR,fr;q=0.9")
    for k,v in (hdrs or {}).items(): req.add_header(k,v)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL) as r:
        raw = r.read()
    try: return gzip.decompress(raw).decode("utf-8","ignore")
    except: return raw.decode("utf-8","ignore")

def strip_html(s):
    return re.sub(r'\s+',' ', re.sub(r'<[^>]+>','',s)).strip()

def ft_token():
    if _ft_cache["tok"] and time.time() < _ft_cache["exp"]: return _ft_cache["tok"]
    body = urllib.parse.urlencode({"grant_type":"client_credentials","client_id":FT_APP,"client_secret":FT_SEC,"scope":"api_offresdemploiv2 o2dsoffre"}).encode()
    r = json.loads(fetch("https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire",{"Content-Type":"application/x-www-form-urlencoded"},body,10))
    _ft_cache["tok"] = r["access_token"]
    _ft_cache["exp"] = time.time() + r.get("expires_in",1200) - 60
    return _ft_cache["tok"]

def scrape_ft(keywords, contracts):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    mn = (now-timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mx = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs, seen = [], set()
    try:
        tok = ft_token()
        ft_types = list({FT_CONTRACT[c] for c in contracts if c in FT_CONTRACT}) or ["CDI"]
        for kw in keywords[:3]:
            for ct in ft_types[:2]:
                url = (f"https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
                       f"?motsCles={urllib.parse.quote(kw)}&region=11&typeContrat={ct}"
                       f"&range=0-9&minCreationDate={mn}&maxCreationDate={mx}")
                d = json.loads(fetch(url,{"Authorization":f"Bearer {tok}","Accept":"application/json"}))
                for o in d.get("resultats",[]):
                    jid = "ft_"+o["id"]
                    if jid in seen: continue
                    seen.add(jid)
                    jobs.append({"id":jid,"title":o.get("intitule",""),"company":o.get("entreprise",{}).get("nom","Confidentiel"),"location":o.get("lieuTravail",{}).get("libelle","IDF"),"salary":o.get("salaire",{}).get("commentaire") or o.get("salaire",{}).get("libelle","Non précisé"),"description":o.get("description","")[:800],"link":f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}","source":"France Travail","date":o.get("dateCreation",""),"contract":o.get("typeContratLibelle",ct)})
    except Exception as e: print(f"[FT] {e}")
    return jobs

def scrape_adzuna(keywords, contracts):
    jobs, seen = [], set()
    try:
        for kw in keywords[:3]:
            url = (f"https://api.adzuna.com/v1/api/jobs/fr/search/1?app_id={AZ_ID}&app_key={AZ_KEY}"
                   f"&results_per_page=10&what={urllib.parse.quote_plus(kw)}"
                   f"&where=Ile-de-France&distance=30&max_days_old=5&sort_by=date&content-type=application/json")
            d = json.loads(fetch(url))
            for j in d.get("results",[]):
                t=j.get("title",""); co=j.get("company",{}).get("display_name","")
                jid="az_"+"".join(c for c in (t+co).lower().replace(" ","")[:24] if c.isalnum())
                if jid in seen: continue
                seen.add(jid)
                sm,sx=j.get("salary_min"),j.get("salary_max")
                jobs.append({"id":jid,"title":t,"company":co,"location":j.get("location",{}).get("display_name","IDF"),"salary":f"{round(sm/1000)}k-{round(sx/1000)}k€" if sm and sx else "Non précisé","description":j.get("description","")[:800],"link":j.get("redirect_url",""),"source":"Adzuna","date":j.get("created",""),"contract":contracts[0] if contracts else "CDI"})
    except Exception as e: print(f"[Adzuna] {e}")
    return jobs

def scrape_apec(keywords, contracts):
    """APEC — organisme paritaire public, API JSON non authentifiée"""
    jobs, seen = [], set()
    try:
        for kw in keywords[:3]:
            url = (f"https://www.apec.fr/cms/webservices/rechercheOffre/results"
                   f"?motsCles={urllib.parse.quote_plus(kw)}&lieu=IDF&nbParPage=10&page=0&tri=1")
            text = fetch(url, {"Accept":"application/json","X-Requested-With":"XMLHttpRequest","Referer":"https://www.apec.fr/candidat/recherche-emploi.html"})
            data = json.loads(text)
            resultats = data.get("resultats") or data.get("data") or data.get("offres") or []
            for o in resultats:
                num = str(o.get("numeroOffre") or o.get("numOffre") or o.get("id") or "")
                if not num: continue
                jid = "apec_"+num
                if jid in seen: continue
                seen.add(jid)
                lieu = o.get("lieuTravail") or o.get("lieu") or {}
                loc = (lieu.get("libelle","IDF") if isinstance(lieu,dict) else str(lieu)) or "IDF"
                co = o.get("entreprise",{})
                company = o.get("nomEntreprise") or (co.get("nom") if isinstance(co,dict) else str(co)) or "Confidentiel"
                jobs.append({"id":jid,"title":o.get("intitule") or o.get("titre") or "","company":company,"location":loc,"salary":o.get("salaireTexte") or "Non précisé","description":str(o.get("texteOffre") or o.get("description") or o.get("accroche") or "")[:800],"link":f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/{num}","source":"APEC","date":o.get("datePublication") or ""})
    except Exception as e: print(f"[APEC] {e}")
    return jobs

def scrape_rss(keywords, contracts):
    """Indeed RSS + Cadremploi RSS — flux publics officiels"""
    jobs, seen = [], set()

    rss_sources = []
    for kw in keywords[:2]:
        kw_enc = urllib.parse.quote_plus(kw)
        rss_sources += [
            (f"https://fr.indeed.com/rss?q={kw_enc}&l=Ile-de-France&sort=date", "Indeed"),
            (f"https://www.cadremploi.fr/api/offres/search?q={kw_enc}&l=idf&format=rss", "Cadremploi"),
        ]

    for url, source in rss_sources:
        try:
            xml = fetch(url, {"Accept":"application/rss+xml,application/xml,text/xml"})
            items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
            for item in items[:8]:
                def tag(t): m=re.search(f'<{t}[^>]*><!\\[CDATA\\[(.*?)\\]\\]></{t}>',item,re.DOTALL); return m.group(1).strip() if m else (re.search(f'<{t}[^>]*>(.*?)</{t}>',item,re.DOTALL) or type('',(),{'group':lambda s,x:''})()).group(1).strip()
                title   = tag('title')
                link    = tag('link') or re.search(r'<link>(.*?)</link>',item,re.DOTALL)
                link    = link.group(1).strip() if hasattr(link,'group') else (link or '')
                desc    = strip_html(tag('description'))[:800]
                company = tag('source') or tag('company') or "Confidentiel"
                date    = tag('pubDate') or tag('dc:date') or ""
                if not title: continue
                raw = (title+company).lower().replace(" ","")[:24]
                jid = source.lower()+"_"+"".join(c for c in raw if c.isalnum())
                if jid in seen: continue
                seen.add(jid)
                jobs.append({"id":jid,"title":title,"company":company,"location":"IDF","salary":"Non précisé","description":desc,"link":link,"source":source,"date":date,"contract":contracts[0] if contracts else "CDI"})
        except Exception as e: print(f"[RSS {source}] {e}")

    return jobs

class handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _cors(self):
        for k,v in CORS.items(): self.send_header(k,v)
    def _json(self,data,code=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",len(body)); self._cors(); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()
    def _run(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        keywords  = [k.strip() for k in qs.get("kw",[""])[0].split(",") if k.strip()]
        contracts = [c.strip() for c in qs.get("ct",["CDI"])[0].split(",") if c.strip()] or ["CDI"]
        if not keywords:
            self._json({"jobs":[],"total":0,"error":"Aucun mot-clé — uploadez votre CV"}); return
        print(f"[Scraping] kw={keywords} ct={contracts}")
        jobs, seen = [], set()
        for fn in [scrape_ft, scrape_adzuna, scrape_apec, scrape_rss]:
            try:
                for j in fn(keywords, contracts):
                    if j["id"] not in seen: seen.add(j["id"]); jobs.append(j)
            except Exception as e: print(f"[Error] {fn.__name__}: {e}")
        print(f"[Done] {len(jobs)} offres — FT+Adzuna+APEC+Indeed+Cadremploi")
        self._json({"jobs":jobs,"total":len(jobs)})
    def do_GET(self): self._run()
    def do_POST(self): self._run()


# ── SANITISATION PDF côté serveur (appelé via POST si besoin futur)
import re as _re

def sanitize_cv_text(text: str) -> tuple:
    """
    Valide et nettoie le texte extrait d'un CV PDF.
    Retourne (texte_nettoyé, erreur_ou_None)
    """
    if not text or len(text.strip()) < 200:
        return '', 'CV trop court ou vide'

    if len(text) > 80000:
        return '', 'Document trop volumineux'

    word_count = len([w for w in text.split() if len(w) > 2])
    if word_count < 50:
        return '', 'Contenu illisible — PDF scanné sans OCR'

    # Anti-injection prompt
    patterns = [
        r'ignore\s+(all\s+)?(previous\s+|above\s+)?instructions?',
        r'forget\s+(everything|all|previous)',
        r'you\s+are\s+now\s+',
        r'act\s+as\s+(a\s+|an\s+)',
        r'new\s+instructions?\s*:',
        r'system\s*:\s*you',
        r'\[INST\]|\[\/INST\]|<\|im_start\|>|<\|im_end\|>',
        r'###\s*(instruction|system|prompt)',
        r'return\s+(json|keywords|only)\s*:',
        r'disregard\s+(all|previous|above)',
        r'jailbreak|DAN\s+mode|developer\s+mode',
    ]
    cleaned = text
    injection_found = False
    for p in patterns:
        if _re.search(p, cleaned, _re.IGNORECASE):
            injection_found = True
            cleaned = _re.sub(p, '[supprimé]', cleaned, flags=_re.IGNORECASE)

    # Limiter à 12000 chars (≈3 pages A4)
    cleaned = cleaned[:12000]

    return cleaned, None
