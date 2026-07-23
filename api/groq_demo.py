"""Lucy — Proxy Groq mode démo (Vercel)
La clé GROQ_DEMO_KEY reste côté serveur : elle n'est JAMAIS envoyée au navigateur.
Modèle forcé + max_tokens plafonné pour limiter les abus.
"""
import json, os, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
MODEL          = "llama-3.3-70b-versatile"   # forcé côté serveur
MAX_TOKENS_CAP = 2000
MAX_BODY_BYTES = 80_000                       # ~CV 12k chars + prompts

class handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        for k, v in CORS.items(): self.send_header(k, v)

    def _send(self, body: bytes, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors(); self.end_headers(); self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(json.dumps(data).encode(), code)

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        key = os.environ.get("GROQ_DEMO_KEY", "")
        if not key:
            return self._json({"error": {"message": "GROQ_DEMO_KEY manquante dans Vercel"}}, 500)

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._json({"error": {"message": "Payload invalide ou trop volumineux"}}, 413)

        try:
            body = json.loads(self.rfile.read(length))
            messages = body.get("messages", [])
            if not isinstance(messages, list) or not messages:
                raise ValueError("messages manquants")
            payload = {
                "model":       MODEL,
                "max_tokens":  min(int(body.get("max_tokens", 1500)), MAX_TOKENS_CAP),
                "temperature": float(body.get("temperature", 0.65)),
                "messages":    messages,
            }
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json({"error": {"message": "Requête invalide"}}, 400)

        req = urllib.request.Request(
            GROQ_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self._send(r.read(), r.status)
        except urllib.error.HTTPError as e:
            # Préserve le code (429, 400...) pour que le retry côté client fonctionne
            self._send(e.read(), e.code)
        except Exception:
            self._json({"error": {"message": "Groq injoignable"}}, 502)
