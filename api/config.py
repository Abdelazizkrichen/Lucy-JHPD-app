"""Lucy — Config endpoint (Vercel)
Expose Supabase config + clé Groq démo depuis les variables d'environnement.
"""
import json, os
from http.server import BaseHTTPRequestHandler

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

class handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        for k, v in CORS.items(): self.send_header(k, v)
    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors(); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()
    def do_GET(self):
        self._json({
            "supabase_url":      os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", "")
        })
