"""
Lucy Job Hunter — Serverless scraping function (Vercel)
Chaque utilisateur envoie ses propres clés FT + Adzuna.
Aucune donnée stockée côté serveur.
"""
import json, urllib.request, urllib.parse, ssl
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode    = ssl.CERT_NONE

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def get_ft_token(app_id, secret):
    body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     app_id,
        "client_secret": secret,
        "scope":         "api_offresdemploiv2 o2dsoffre"
    }).encode()
    req = urllib.request.Request(
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
        return json.loads(r.read())["access_token"]


def scrape_ft(token):
    now      = datetime.utcnow()
    min_date = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    max_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    keywords = ["product%20owner%20agile", "product%20lead%20AMOA%20MOA", "product%20owner%20digital"]
    jobs, seen = [], set()
    for kw in keywords:
        url = (f"https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
               f"?motsCles={kw}&region=11&typeContrat=CDI&range=0-14"
               f"&minCreationDate={min_date}&maxCreationDate={max_date}")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
            data = json.loads(r.read())
        for o in data.get("resultats", []):
            jid = "ft_" + o["id"]
            if jid in seen: continue
            seen.add(jid)
            jobs.append({
                "id": jid, "title": o.get("intitule", ""),
                "company":     o.get("entreprise", {}).get("nom", "Confidentiel"),
                "location":    o.get("lieuTravail", {}).get("libelle", "IDF"),
                "salary":      o.get("salaire", {}).get("commentaire") or o.get("salaire", {}).get("libelle", "Non précisé"),
                "description": o.get("description", "")[:800],
                "link":        f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}",
                "source": "France Travail", "date": o.get("dateCreation", "")
            })
    return jobs


def scrape_adzuna(app_id, key):
    queries = ["product+owner+agile", "product+owner+digital", "AMOA+product+owner"]
    jobs, seen = [], set()
    for q in queries:
        url = (f"https://api.adzuna.com/v1/api/jobs/fr/search/1"
               f"?app_id={app_id}&app_key={key}"
               f"&results_per_page=15&what={q}"
               f"&where=Ile-de-France&distance=30&max_days_old=3&sort_by=date"
               f"&content-type=application/json")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
            data = json.loads(r.read())
        for j in data.get("results", []):
            title   = j.get("title", "")
            company = j.get("company", {}).get("display_name", "")
            raw     = (title + company).lower().replace(" ", "")[:24]
            jid     = "az_" + ''.join(c for c in raw if c.isalnum())
            if jid in seen: continue
            seen.add(jid)
            s_min, s_max = j.get("salary_min"), j.get("salary_max")
            salary = (f"{round(s_min/1000)}k-{round(s_max/1000)}k€"
                      if s_min and s_max else "Non précisé")
            jobs.append({
                "id": jid, "title": title, "company": company,
                "location":    j.get("location", {}).get("display_name", "IDF"),
                "salary":      salary,
                "description": j.get("description", "")[:800],
                "link":        j.get("redirect_url", ""),
                "source": "Adzuna", "date": j.get("created", "")
            })
    return jobs


class handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        for k, v in CORS.items(): self.send_header(k, v)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self._cors(); self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")

        ft_app_id = body.get("ft_app_id", "")
        ft_secret = body.get("ft_secret", "")
        az_app_id = body.get("az_app_id", "")
        az_key    = body.get("az_key", "")

        jobs = []

        if ft_app_id and ft_secret:
            try:
                token = get_ft_token(ft_app_id, ft_secret)
                jobs += scrape_ft(token)
            except Exception as e:
                print(f"[FT] {e}")

        if az_app_id and az_key:
            try:
                jobs += scrape_adzuna(az_app_id, az_key)
            except Exception as e:
                print(f"[Adzuna] {e}")

        # Déduplication cross-sources
        seen, unique = set(), []
        for j in jobs:
            if j["id"] not in seen:
                seen.add(j["id"]); unique.append(j)

        self._json({"jobs": unique, "total": len(unique)})
