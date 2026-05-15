"""
Lucy — Email sender serverless function (Vercel)
Reçoit les données du navigateur, envoie via Gmail SMTP.
Aucune donnée stockée.
"""
import json, smtplib, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from http.server import BaseHTTPRequestHandler

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


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
        data   = json.loads(self.rfile.read(length) or b"{}")

        gmail_user = data.get("gmail_user", "")
        gmail_pass = data.get("gmail_pass", "")
        to_addr    = data.get("to", "")
        subject    = data.get("subject", "")
        body_text  = data.get("body", "")
        cv_ad_b64  = data.get("cv_adapted_b64", "")
        cv_ad_name = data.get("cv_adapted_name", "CV_adapte.pdf")
        cv_or_b64  = data.get("cv_original_b64", "")
        cv_or_name = data.get("cv_original_name", "CV_complet.pdf")

        if not all([gmail_user, gmail_pass, to_addr, subject]):
            self._json({"error": "Champs manquants"}, 400)
            return

        try:
            msg = MIMEMultipart()
            msg["From"]    = gmail_user
            msg["To"]      = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            for b64str, name in [(cv_ad_b64, cv_ad_name), (cv_or_b64, cv_or_name)]:
                if b64str:
                    part = MIMEApplication(base64.b64decode(b64str), Name=name)
                    part["Content-Disposition"] = f'attachment; filename="{name}"'
                    msg.attach(part)

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(gmail_user, gmail_pass)
                smtp.sendmail(gmail_user, to_addr, msg.as_string())

            self._json({"ok": True})

        except Exception as e:
            self._json({"error": str(e)}, 500)
