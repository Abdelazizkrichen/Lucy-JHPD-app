"""Lucy — Job scraping (Vercel) — keywords dynamiques depuis le CV utilisateur"""
import json, urllib.request, urllib.parse, ssl, time, gzip
from http.server import BaseHTTPRequestHandler

SSL = ssl.create_default_context()
SSL.check_hostname = False
SSL.verify_mode = ssl.CERT_NONE
CORS = {"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"}

FT_APP = "PAR_lucyjobhunter_b4ed148e50022211273f40b6f755af73ece7c4b284eb27ed260ec3104fe697af"
FT_SEC = "9270acaa586d9a752533dc92163a1c127c976eddd5ad9aa6f889759d1e68e62b"
AZ_ID  = "cbe5b72d"
AZ_KEY = "74845cedd88ff4283ce7ec02f573d733"
WJ_APP = "CZMSE9B1IT"
WJ_KEY = "bcca6f7f1a413c65bac9cc5dff4ceac8"
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0 Safari/537.36"

# Pas de fallback — keywords obligatoires depuis le CV utilisateur

_ft_cache = {"tok": None, "exp": 0}

def fetch(url, hdrs=None, data=None, timeout=12):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept-Encoding","gzip")
    for k,v in (hdrs or {}).items(): req.add_header(k,v)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL) as r:
        raw = r.read()
    try: return gzip.decompress(raw).decode("utf-8","ignore")
    except: return raw.decode("utf-8","ignore")

def ft_token():
    if _ft_cache["tok"] and time.time() < _ft_cache["exp"]: return _ft_cache["tok"]
    body = urllib.parse.urlencode({"grant_type":"client_credentials","client_id":FT_APP,"client_secret":FT_SEC,"scope":"api_offresdemploiv2 o2dsoffre"}).encode()
    r = json.loads(fetch("https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire",{"Content-Type":"application/x-www-form-urlencoded"},body,10))
    _ft_cache["tok"] = r["access_token"]
    _ft_cache["exp"] = time.time() + r.get("expires_in",1200) - 60
    return _ft_cache["tok"]

def scrape_ft(keywords):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    mn = (now-timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mx = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs, seen = [], set()
    try:
        tok = ft_token()
        for kw in keywords[:4]:  # max 4 pour FT
            kw_enc = urllib.parse.quote(kw)
            url = f"https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search?motsCles={kw_enc}&region=11&typeContrat=CDI&range=0-9&minCreationDate={mn}&maxCreationDate={mx}"
            d = json.loads(fetch(url,{"Authorization":f"Bearer {tok}","Accept":"application/json"}))
            for o in d.get("resultats",[]):
                jid = "ft_"+o["id"]
                if jid in seen: continue
                seen.add(jid)
                jobs.append({"id":jid,"title":o.get("intitule",""),"company":o.get("entreprise",{}).get("nom","Confidentiel"),"location":o.get("lieuTravail",{}).get("libelle","IDF"),"salary":o.get("salaire",{}).get("commentaire") or o.get("salaire",{}).get("libelle","Non précisé"),"description":o.get("description","")[:800],"link":f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}","source":"France Travail","date":o.get("dateCreation","")})
    except Exception as e: print(f"[FT] {e}")
    return jobs

def scrape_adzuna(keywords):
    jobs, seen = [], set()
    try:
        for kw in keywords[:3]:  # max 3 pour Adzuna
            kw_enc = urllib.parse.quote_plus(kw)
            url = f"https://api.adzuna.com/v1/api/jobs/fr/search/1?app_id={AZ_ID}&app_key={AZ_KEY}&results_per_page=10&what={kw_enc}&where=Ile-de-France&distance=30&max_days_old=5&sort_by=date&content-type=application/json"
            d = json.loads(fetch(url))
            for j in d.get("results",[]):
                t=j.get("title",""); co=j.get("company",{}).get("display_name","")
                raw=(t+co).lower().replace(" ","")[:24]
                jid="az_"+''.join(c for c in raw if c.isalnum())
                if jid in seen: continue
                seen.add(jid)
                sm,sx=j.get("salary_min"),j.get("salary_max")
                sal=f"{round(sm/1000)}k-{round(sx/1000)}k€" if sm and sx else "Non précisé"
                jobs.append({"id":jid,"title":t,"company":co,"location":j.get("location",{}).get("display_name","IDF"),"salary":sal,"description":j.get("description","")[:800],"link":j.get("redirect_url",""),"source":"Adzuna","date":j.get("created","")})
    except Exception as e: print(f"[Adzuna] {e}")
    return jobs

def scrape_wttj(keywords):
    jobs, seen = [], set()
    try:
        for kw in keywords[:3]:  # max 3 pour WTTJ
            payload = json.dumps({"requests":[{"indexName":"wttj-jobs-production","params":urllib.parse.urlencode({"query":kw,"filters":"contract_type:CDI AND offices.country_code:FR","hitsPerPage":8,"attributesToRetrieve":"objectID,name,company,published_at,offices,salary_min,salary_max,description,slug"})}]}).encode()
            d = json.loads(fetch(f"https://{WJ_APP.lower()}-dsn.algolia.net/1/indexes/*/queries",{"Content-Type":"application/json","X-Algolia-Application-Id":WJ_APP,"X-Algolia-API-Key":WJ_KEY},payload))
            for h in d.get("results",[{}])[0].get("hits",[]):
                jid="wttj_"+str(h.get("objectID",""))
                if jid in seen: continue
                seen.add(jid)
                co=h.get("company",{}); cn=co.get("name","Confidentiel") if isinstance(co,dict) else str(co); cs=co.get("slug","") if isinstance(co,dict) else ""
                of=(h.get("offices",[]) or [h.get("office",{})])[0]; loc=(of.get("city","") if isinstance(of,dict) else "") or "France"
                sm,sx=h.get("salary_min"),h.get("salary_max"); sal=f"{round(sm/1000)}k-{round(sx/1000)}k€" if sm and sx else "Non précisé"
                sl=h.get("slug",""); lnk=f"https://www.welcometothejungle.com/fr/companies/{cs}/jobs/{sl}" if cs and sl else "https://www.welcometothejungle.com"
                jobs.append({"id":jid,"title":h.get("name",""),"company":cn,"location":loc,"salary":sal,"description":str(h.get("description",""))[:800],"link":lnk,"source":"WTTJ","date":h.get("published_at","")})
    except Exception as e: print(f"[WTTJ] {e}")
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
        # Lire les mots-clés depuis query string ?kw=mot1,mot2,mot3
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        kw_param = qs.get('kw',[''])[0]
        keywords = [k.strip() for k in kw_param.split(',') if k.strip()]
        if not keywords:
            # Pas de keywords = pas de CV analysé → erreur explicite
            self._json({"jobs":[],"total":0,"error":"Aucun mot-clé fourni — uploadez votre CV d'abord"})
            return
        print(f"[Scraping] keywords: {keywords}")
        jobs, seen = [], set()
        for fn in [scrape_ft, scrape_adzuna, scrape_wttj]:
            try:
                for j in fn(keywords):
                    if j["id"] not in seen: seen.add(j["id"]); jobs.append(j)
            except Exception as e: print(f"[Error] {e}")
        print(f"[Done] {len(jobs)} offres")
        self._json({"jobs":jobs,"total":len(jobs)})
    def do_GET(self): self._run()
    def do_POST(self): self._run()
