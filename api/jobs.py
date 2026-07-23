"""Lucy — Job scraping (Vercel)
Sources légales: France Travail + Adzuna + Jooble + Careerjet + Remotive + Arbeitnow (APIs officielles)
"""
import json, os, urllib.request, urllib.parse, ssl, time, gzip, re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

SSL = ssl.create_default_context()
SSL.check_hostname = False
SSL.verify_mode = ssl.CERT_NONE
CORS = {"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"}

# Clés en variables d'environnement Vercel — jamais en dur dans le code public
FT_APP     = os.environ.get("FT_CLIENT_ID", "")
FT_SEC     = os.environ.get("FT_CLIENT_SECRET", "")
AZ_ID      = os.environ.get("AZ_APP_ID",  "cbe5b72d")
AZ_KEY     = os.environ.get("AZ_APP_KEY", "74845cedd88ff4283ce7ec02f573d733")
JOOBLE_KEY = os.environ.get("JOOBLE_KEY", "")
CJ_AFFID   = os.environ.get("CAREERJET_AFFID", "")
MAX_AGE_DAYS = 31  # jamais d'offre de plus d'un mois

def parse_date(d):
    """Date ISO → datetime naïf UTC. None si illisible."""
    if not d: return None
    try:
        dt = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        if dt.tzinfo: dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0 Safari/537.36"

# Seuls typeContrat valides côté API FT : CDI, CDD, MIS (stage/alternance = natureContrat, non filtrable ici)
FT_CONTRACT = {"CDI":"CDI","CDD":"CDD","freelance":"MIS","POEI":"CDI"}
AZ_CONTRACT = {"CDI":"permanent","CDD":"contract","freelance":"contract","stage":"internship","alternance":"apprenticeship","professionalisation":"apprenticeship","POEI":"permanent"}

_ft_cache = {"tok": None, "exp": 0}
_client = {"ip": "127.0.0.1", "ua": UA}

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
    now = datetime.utcnow()
    mn = (now-timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mx = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs, seen = [], set()
    try:
        tok = ft_token()
        ft_types = list({FT_CONTRACT[c] for c in contracts if c in FT_CONTRACT})
        # Aucun type valide sélectionné (ex: stage/alternance seuls) → recherche sans filtre contrat
        ct_params = [f"&typeContrat={ct}" for ct in ft_types[:2]] or [""]
        for kw in keywords[:5]:
            for ctp in ct_params:
                url = (f"https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
                       f"?motsCles={urllib.parse.quote(kw)}&region=11{ctp}"
                       f"&range=0-19&minCreationDate={mn}&maxCreationDate={mx}")
                d = json.loads(fetch(url,{"Authorization":f"Bearer {tok}","Accept":"application/json"}))
                for o in d.get("resultats",[]):
                    jid = "ft_"+o["id"]
                    if jid in seen: continue
                    seen.add(jid)
                    jobs.append({"id":jid,"title":o.get("intitule",""),"company":o.get("entreprise",{}).get("nom","Confidentiel"),"location":o.get("lieuTravail",{}).get("libelle","IDF"),"salary":o.get("salaire",{}).get("commentaire") or o.get("salaire",{}).get("libelle","Non précisé"),"description":o.get("description","")[:800],"link":f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}","source":"France Travail","date":o.get("dateCreation",""),"contract":o.get("typeContratLibelle","Non précisé")})
    except Exception as e: print(f"[FT] {e}")
    return jobs

def detect_contract(title, desc="", fallback="Non précisé"):
    """Détecte le type de contrat depuis le texte de l'offre (au lieu de l'inventer)."""
    t = (title + " " + desc[:200]).lower()
    if "alternance" in t or "apprentissage" in t or "apprenti" in t: return "alternance"
    if "stage" in t or "stagiaire" in t or "internship" in t:        return "stage"
    if "freelance" in t or "indépendant" in t:                        return "freelance"
    if "cdd" in t:  return "CDD"
    if "cdi" in t:  return "CDI"
    return fallback

EXCLUDE_WORDS = {
    "alternance": ["alternance","apprentissage","apprenti"],
    "stage":      ["stage","stagiaire","internship"],
}

def contract_ok(job, contracts):
    """Exclut les offres alternance/stage si ces contrats ne sont pas sélectionnés."""
    title = job.get("title","").lower()
    for ct, words in EXCLUDE_WORDS.items():
        if ct not in contracts and any(w in title for w in words):
            return False
    return True

def scrape_adzuna(keywords, contracts):
    jobs, seen = [], set()
    # Params officiels Adzuna : permanent=1 (CDI), contract=1 (CDD/freelance)
    az_flags = ""
    cset = set(contracts)
    if cset and cset <= {"CDI","POEI"}:              az_flags = "&permanent=1"
    elif cset and cset <= {"CDD","freelance"}:       az_flags = "&contract=1"
    try:
        for kw in keywords[:3]:
            url = (f"https://api.adzuna.com/v1/api/jobs/fr/search/1?app_id={AZ_ID}&app_key={AZ_KEY}"
                   f"&results_per_page=10&what={urllib.parse.quote_plus(kw)}"
                   f"&where=Ile-de-France&distance=30&max_days_old=31&sort_by=date{az_flags}&content-type=application/json")
            d = json.loads(fetch(url))
            for j in d.get("results",[]):
                t=j.get("title",""); co=j.get("company",{}).get("display_name","")
                jid="az_"+"".join(c for c in (t+co).lower().replace(" ","")[:24] if c.isalnum())
                if jid in seen: continue
                seen.add(jid)
                sm,sx=j.get("salary_min"),j.get("salary_max")
                jobs.append({"id":jid,"title":t,"company":co,"location":j.get("location",{}).get("display_name","IDF"),"salary":f"{round(sm/1000)}k-{round(sx/1000)}k€" if sm and sx else "Non précisé","description":j.get("description","")[:800],"link":j.get("redirect_url",""),"source":"Adzuna","date":j.get("created",""),"contract":detect_contract(t, j.get("description",""), contracts[0] if contracts else "Non précisé")})
    except Exception as e: print(f"[Adzuna] {e}")
    return jobs

def scrape_jooble(keywords, contracts):
    """Jooble — API REST officielle (jooble.org/api/about), clé gratuite"""
    jobs, seen = [], set()
    if not JOOBLE_KEY: return jobs
    try:
        for kw in keywords[:2]:  # limite : 500 requêtes/mois sur le plan gratuit
            body = json.dumps({"keywords": kw, "location": "Ile-de-France"}).encode()
            d = json.loads(fetch(f"https://fr.jooble.org/api/{JOOBLE_KEY}", {"Content-Type": "application/json"}, body))
            for j in d.get("jobs", []):
                jid = "jb_" + str(j.get("id", ""))
                if not j.get("id") or jid in seen: continue
                seen.add(jid)
                title = j.get("title", "")
                desc  = strip_html(j.get("snippet", ""))[:800]
                jobs.append({"id": jid, "title": title,
                    "company": j.get("company", "") or "Confidentiel",
                    "location": j.get("location", "IDF"),
                    "salary": j.get("salary", "") or "Non précisé",
                    "description": desc, "link": j.get("link", ""),
                    "source": "Jooble", "date": j.get("updated", ""),
                    "contract": detect_contract(title, desc, j.get("type", "") or "Non précisé")})
    except Exception as e: print(f"[Jooble] {e}")
    return jobs

def scrape_careerjet(keywords, contracts):
    """Careerjet — API publique officielle pour partenaires (affid gratuit)"""
    jobs, seen = [], set()
    if not CJ_AFFID: return jobs
    try:
        for kw in keywords[:3]:
            url = ("https://public.api.careerjet.net/search?locale_code=fr_FR"
                   f"&keywords={urllib.parse.quote_plus(kw)}&location={urllib.parse.quote_plus('Ile-de-France')}"
                   f"&affid={CJ_AFFID}&user_ip={urllib.parse.quote_plus(_client['ip'])}"
                   f"&user_agent={urllib.parse.quote_plus(_client['ua'])}&sort=date&pagesize=10&page=1")
            d = json.loads(fetch(url, {"Accept": "application/json"}))
            if d.get("type") != "JOBS": continue
            for j in d.get("jobs", []):
                title = j.get("title", "")
                co    = j.get("company", "") or "Confidentiel"
                jid   = "cj_" + "".join(c for c in (title + co).lower().replace(" ", "")[:24] if c.isalnum())
                if not title or jid in seen: continue
                seen.add(jid)
                desc = strip_html(j.get("description", ""))[:800]
                jobs.append({"id": jid, "title": title, "company": co,
                    "location": j.get("locations", "IDF") or "IDF",
                    "salary": j.get("salary", "") or "Non précisé",
                    "description": desc, "link": j.get("url", ""),
                    "source": "Careerjet", "date": j.get("date", ""),
                    "contract": detect_contract(title, desc)})
    except Exception as e: print(f"[Careerjet] {e}")
    return jobs

def scrape_remotive(keywords, contracts):
    """Remotive — API publique officielle (remotive.com/api), jobs 100% remote, sans clé"""
    jobs, seen = [], set()
    OK_LOC = ("france", "europe", "emea", "worldwide", "anywhere")
    try:
        for kw in keywords[:2]:
            d = json.loads(fetch(f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote_plus(kw)}&limit=15"))
            for j in d.get("jobs", []):
                loc = (j.get("candidate_required_location") or "").lower()
                if loc and not any(x in loc for x in OK_LOC): continue
                jid = "rm_" + str(j.get("id", ""))
                if not j.get("id") or jid in seen: continue
                seen.add(jid)
                title = j.get("title", "")
                desc  = strip_html(j.get("description", ""))[:800]
                jobs.append({"id": jid, "title": title,
                    "company": j.get("company_name", "") or "Confidentiel",
                    "location": "Remote — " + (j.get("candidate_required_location") or "Monde"),
                    "salary": j.get("salary", "") or "Non précisé",
                    "description": desc, "link": j.get("url", ""),
                    "source": "Remotive", "date": j.get("publication_date", ""),
                    "contract": detect_contract(title, desc, "Remote")})
    except Exception as e: print(f"[Remotive] {e}")
    return jobs

def scrape_arbeitnow(keywords, contracts):
    """Arbeitnow — API publique officielle (arbeitnow.com/api/job-board-api), sans clé"""
    jobs, seen = [], set()
    kws = [w.lower() for k in keywords[:4] for w in k.split() if len(w) > 2]
    try:
        for page in (1, 2):
            d = json.loads(fetch(f"https://www.arbeitnow.com/api/job-board-api?page={page}"))
            for j in d.get("data", []):
                loc = (j.get("location") or "").lower()
                title = j.get("title", "")
                blob = (title + " " + " ".join(j.get("tags", []))).lower()
                # France, ou remote qui matche les keywords du CV
                if not ("france" in loc or "paris" in loc or (j.get("remote") and any(w in blob for w in kws))): continue
                jid = "an_" + str(j.get("slug", ""))[:40]
                if not j.get("slug") or jid in seen: continue
                seen.add(jid)
                desc = strip_html(j.get("description", ""))[:800]
                ts = j.get("created_at")
                date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ts, (int, float)) else ""
                jobs.append({"id": jid, "title": title,
                    "company": j.get("company_name", "") or "Confidentiel",
                    "location": j.get("location", "") or "Europe",
                    "salary": "Non précisé", "description": desc,
                    "link": j.get("url", ""), "source": "Arbeitnow", "date": date,
                    "contract": detect_contract(title, desc, ", ".join(j.get("job_types", [])) or "Non précisé")})
    except Exception as e: print(f"[Arbeitnow] {e}")
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
        _client["ip"] = (self.headers.get("x-forwarded-for", "127.0.0.1") or "127.0.0.1").split(",")[0].strip()
        _client["ua"] = self.headers.get("user-agent", UA) or UA
        print(f"[Scraping] kw={keywords} ct={contracts}")
        jobs, seen = [], set()
        for fn in [scrape_ft, scrape_adzuna, scrape_jooble, scrape_careerjet, scrape_remotive, scrape_arbeitnow]:
            try:
                for j in fn(keywords, contracts):
                    if j["id"] not in seen: seen.add(j["id"]); jobs.append(j)
            except Exception as e: print(f"[Error] {fn.__name__}: {e}")
        # ── FILTRE PERTINENCE ─────────────────────────────────────
        # Garder seulement les offres où au moins 1 keyword apparaît
        # dans le titre OU les 300 premiers chars de description
        # Mots trop génériques — présents partout, ignorés pour le filtre
        GENERIC_WORDS = {'agile','scrum','kanban','digital','web','data','it',
                         'informatique','logiciel','software','cloud','tech'}

        def is_relevant(job, kws):
            title = job.get('title','').lower()
            desc  = job.get('description','')[:500].lower()
            for kw in kws:
                kw_low = kw.lower().strip()
                if len(kw_low) < 2: continue
                kw_words = [w for w in kw_low.split() if len(w) > 2 and w not in GENERIC_WORDS]
                if not kw_words: continue
                # Keyword doit apparaître dans le TITRE
                if any(w in title for w in kw_words):
                    return True
            # Second pass : 2 keywords distincts dans la description
            kw_in_desc = sum(
                1 for kw in kws
                for w in [x for x in kw.lower().split() if len(x) > 2 and x not in GENERIC_WORDS]
                if w in desc
            )
            return kw_in_desc >= 2

        jobs = [j for j in jobs if contract_ok(j, contracts)]
        # Jamais plus d'un mois d'ancienneté (date illisible = conservée)
        cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
        jobs = [j for j in jobs if (parse_date(j.get("date")) or datetime.utcnow()) >= cutoff]
        filtered = [j for j in jobs if is_relevant(j, keywords)]
        # Si le filtre est trop strict (< 3 résultats), relaxer sur description uniquement
        if len(filtered) < 3:
            filtered = jobs  # garder tout si trop restrictif

        # Tri chronologique : du plus récent au plus ancien
        filtered.sort(key=lambda j: parse_date(j.get("date")) or datetime(1970, 1, 1), reverse=True)
        print(f"[Done] {len(jobs)} brutes → {len(filtered)} pertinentes — FT+Adzuna+Jooble+Careerjet+Remotive+Arbeitnow")
        self._json({"jobs":filtered,"total":len(filtered)})
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
