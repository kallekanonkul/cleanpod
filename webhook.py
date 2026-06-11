#!/usr/bin/env python3
"""
Auto-deploy webhook – lyssnar på GitHub pushes och uppdaterar CleanPod automatiskt
"""
import hmac
import hashlib
import subprocess
from flask import Flask, request, abort

app = Flask(__name__)

WEBHOOK_SECRET = "cleanpod-deploy-secret-2024"
DEPLOY_SCRIPT  = "/home/robert/cleanpod/deploy.sh"

@app.route("/webhook", methods=["POST"])
def webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(403)
    subprocess.Popen(["bash", DEPLOY_SCRIPT])
    return "OK", 200

if __name__ == "__main__":
    print("🔗 Webhook-server körs på port 9000")
    app.run(host="0.0.0.0", port=9000)
