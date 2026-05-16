"""
Lucy — Job scraping serverless (Vercel)
Sources: WTTJ (Algolia public), APEC (REST JSON), HelloWork (HTML/JSON-LD)
Zéro clé API requise de l'utilisateur.
"""
import json, urllib.request, urllib.parse, ssl, re, gzip
from http.server import BaseHTTPRequestHandler

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode    = ssl.CERT_NONE

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
KW_WTTJ = ["product owner agile", "AMOA product owner", "product owner digital"]
KW_APEC = ["product+owner+agile", "AMOA+product+owner", "product+owner+digital"]
KW_HW   = ["product+owner+agile", "AMOA+product+owner"]


def fetch_url(url, headers=None, data=None, timeout=12):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept-Language", "fr-FR,fr;q=0.9")
    req.add_header("Accept-Encoding", "gzip, deflate")
    if headers:
        for k, v in headers.items(): req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        raw = r.read()
    try:    return gzip.decompress(raw).decode("utf-8", errors="ignore")
    except: return raw.decode("utf-8", errors="ignore")


def scrape_wttj():
    APP_ID  = "CZMSE9B1IT"
    API_KEY = "bcca6f7f1a413c65bac9cc5dff4ceac8"
    jobs, seen = [], set()
    for kw in KW_WTTJ:
        try:
            payload = json.dumps({"requests": [{
                "indexName": "wttj-jobs-production",
                "params": urllib.parse.urlencode({
                    "query": kw,
                    "filters": "contract_type:CDI AND offices.country_code:FR",
                    "hitsPerPage": 15,
                    "attributesToRetrieve": "objectID,name,company,published_at,offices,office,salary_min,salary_max,description,slug"
                })
            }]}).encode()
            text = fetch_url(
                f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries",
                headers={"Content-Type":"application/json","X-Algolia-Application-Id":APP_ID,"X-Algolia-API-Key":API_KEY},
                data=payload
            )
            hits = json.loads(text).get("results",[{}])[0].get("hits",[])
            for h in hits:
                jid = "wttj_" + str(h.get("objectID",""))
                if jid in seen: continue
                seen.add(jid)
                co = h.get("company",{}); company = (co.get("name","Confidentiel") if isinstance(co,dict) else str(co)); co_slug = (co.get("slug","") if isinstance(co,dict) else "")
                offices = h.get("offices",[]) or [h.get("office",{})]; office = offices[0] if offices else {}
                location = (office.get("city","") if isinstance(office,dict) else "") or "France"
                sm,sx = h.get("salary_min"),h.get("salary_max"); salary = f"{round(sm/1000)}k-{round(sx/1000)}k€" if sm and sx else "Non précisé"
                slug = h.get("slug",""); link = (f"https://www.welcometothejungle.com/fr/companies/{co_slug}/jobs/{slug}" if co_slug and slug else "https://www.welcometothejungle.com/fr/jobs")
                jobs.append({"id":jid,"title":h.get("name",""),"company":company,"location":location,"salary":salary,"description":str(h.get("description",""))[:800],"link":link,"source":"WTTJ","date":h.get("published_at","")})
        except Exception as e: print(f"[WTTJ] {e}")
    return jobs


def scrape_apec():
    jobs, seen = [], set()
    for kw in KW_APEC:
        try:
            url = f"https://www.apec.fr/cms/webservices/rechercheOffre/results?motsCles={kw}&typeContrat=CDI&lieu=IDF&nbParPage=15&page=0&tri=1"
            text = fetch_url(url, headers={"Accept":"application/json","X-Requested-With":"XMLHttpRequest","Referer":"https://www.apec.fr/candidat/recherche-emploi.html"})
            data = json.loads(text)
            resultats = data.get("resultats") or data.get("data") or data.get("results") or data.get("offres") or []
            for o in resultats:
                num = str(o.get("numeroOffre") or o.get("numOffre") or o.get("id") or "")
                if not num: continue
                jid = "apec_" + num
                if jid in seen: continue
                seen.add(jid)
                lieu = o.get("lieuTravail") or o.get("lieu") or {}
                location = (lieu.get("libelle","IDF") if isinstance(lieu,dict) else str(lieu)) or "IDF"
                co = o.get("entreprise",{}); company = o.get("nomEntreprise") or (co.get("nom") if isinstance(co,dict) else str(co)) or "Confidentiel"
                jobs.append({"id":jid,"title":o.get("intitule") or o.get("titre") or "","company":company,"location":location,"salary":o.get("salaireTexte") or "Non précisé","description":str(o.get("texteOffre") or o.get("description") or o.get("accroche") or "")[:800],"link":f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/{num}","source":"APEC","date":o.get("datePublication") or ""})
        except Exception as e: print(f"[APEC] {e}")
    return jobs


def scrape_hellowork():
    jobs, seen = [], set()
    for kw in KW_HW:
        try:
            url  = f"https://www.hellowork.com/fr-fr/emploi/recherche.html?k={kw}&l=Ile-de-France&c=CDI&s=date"
            html = fetch_url(url, headers={"Accept":"text/html,application/xhtml+xml"})
            for ld_str in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL):
                try:
                    ld = json.loads(ld_str.strip()); items = ld if isinstance(ld,list) else [ld]
                    for item in items:
                        if item.get("@type") != "JobPosting": continue
                        title = item.get("title") or item.get("name") or ""
                        co = item.get("hiringOrganization",{}); company = co.get("name","Confidentiel") if isinstance(co,dict) else "Confidentiel"
                        loc = item.get("jobLocation",{}); loc = (loc[0] if isinstance(loc,list) and loc else loc) if isinstance(loc,list) else loc
                        addr = loc.get("address",{}) if isinstance(loc,dict) else {}; location = (addr.get("addressLocality") or addr.get("addressRegion") or "IDF") if isinstance(addr,dict) else "IDF"
                        desc = re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',item.get("description",""))).strip()[:800]
                        sal = item.get("baseSalary",{}); salary = "Non précisé"
                        if isinstance(sal,dict):
                            v = sal.get("value",{})
                            if isinstance(v,dict):
                                mn,mx = v.get("minValue"),v.get("maxValue")
                                if mn and mx: salary = f"{round(mn/1000)}k-{round(mx/1000)}k€"
                        base = "hw_"+re.sub(r'[^a-z0-9]','', (title+company).lower())[:18]; jid = base; n = 0
                        while jid in seen: n+=1; jid=f"{base}{n}"
                        seen.add(jid)
                        jobs.append({"id":jid,"title":title,"company":company,"location":location,"salary":salary,"description":desc,"link":item.get("url",""),"source":"HelloWork","date":item.get("datePosted","")})
                except Exception: pass
        except Exception as e: print(f"[HelloWork] {e}")
    return jobs


class handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        for k,v in CORS.items(): self.send_header(k,v)
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",len(body)); self._cors(); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()
    def _run(self):
        print("[Scraping] WTTJ + APEC + HelloWork...")
        jobs, seen = [], set()
        for fn in [scrape_wttj, scrape_apec, scrape_hellowork]:
            try:
                for j in fn():
                    if j["id"] not in seen: seen.add(j["id"]); jobs.append(j)
            except Exception as e: print(f"[Error] {fn.__name__}: {e}")
        print(f"[Done] {len(jobs)} offres")
        self._json({"jobs": jobs, "total": len(jobs)})
    def do_GET(self):  self._run()
    def do_POST(self): self._run()
