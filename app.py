
#!/usr/bin/env python3
"""
CleanPod – Reklamfri podcast-tjänst
"""

import os
import sys
import json
import uuid
import hashlib
import threading
import time
import subprocess
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

CONFIG = {
    "app_name": "CleanPod",
    "max_users": 5,
    "server_port": 8080,
    "base_url": "https://cleanpod-production.up.railway.app",
    "whisper_model": "large-v3",
    "language": "sv",
    "padding_ms": 8000,
    "min_ad_duration_s": 3,
    "max_ad_duration_s": 300,
    "crossfade_ms": 500,
    "check_interval_hours": 2,
    "ad_keywords": [
        "podme", "sponsor", "rabatt", "rabattkod", "kampanjkod",
        "använd koden", "använd kod", "gå till", "besök", "klicka",
        "länken i beskrivningen", "länk i bio", "prova gratis",
        "första månaden", "prenumerera", "erbjudande", "deal",
        "affiliate", "samarbete", "i samarbete med", "tillsammans med",
        "tacka", "tackar", "tack till", "stödjer", "möjliggör",
        "podcasten stöds", "annons", "reklam",
        "marie stads", "alkoholfri", "diskmaskin", "diskmedel",
        "försvarsmakten", "försvaret", "världspliktig",
        "läs mer på", "läs mer om", "mer information",
        "för livsnjutare", "nordvpn", "incogni", "expressvpn",
        "pengarna tillbaka", "garanti",
    ],
}

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def load_users():
    path = DATA_DIR / "users.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(DATA_DIR / "users.json", "w") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def load_invite_codes():
    path = DATA_DIR / "invite_codes.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_invite_codes(codes):
    with open(DATA_DIR / "invite_codes.json", "w") as f:
        json.dump(codes, f, indent=2)

def load_api_key():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        key = env_path.read_text().strip()
        if key.startswith("sk-ant-"):
            return key
    return None

def user_dir(username):
    d = DATA_DIR / "users" / username
    d.mkdir(parents=True, exist_ok=True)
    return d

def load_user_feeds(username):
    path = user_dir(username) / "feeds.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []

def save_user_feeds(username, feeds):
    with open(user_dir(username) / "feeds.json", "w") as f:
        json.dump(feeds, f, ensure_ascii=False, indent=2)

def load_user_history(username):
    path = user_dir(username) / "history.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []

def save_user_history(username, entry):
    history = load_user_history(username)
    history.insert(0, entry)
    history = history[:50]
    with open(user_dir(username) / "history.json", "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_processed(username):
    path = user_dir(username) / "processed.json"
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()

def save_processed(username, audio_url):
    processed = load_processed(username)
    processed.add(audio_url)
    with open(user_dir(username) / "processed.json", "w") as f:
        json.dump(list(processed), f)

def send_notification(topic, title, message):
    if not topic:
        return
    import requests
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "default"},
            timeout=10
        )
    except Exception:
        pass

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("username") != "admin":
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

# ── Podcast-funktioner ─────────────────────────────────────────────────────────

def fetch_episodes(feed_url):
    import feedparser
    feed = feedparser.parse(feed_url)
    episodes = []
    for entry in feed.entries:
        audio_url = None
        for link in entry.get("links", []):
            if "audio" in link.get("type", ""):
                audio_url = link["href"]
                break
        if not audio_url:
            for enc in entry.get("enclosures", []):
                if "audio" in enc.get("type", ""):
                    audio_url = enc.get("href") or enc.get("url")
                    break
        if audio_url:
            episodes.append({
                "title":     entry.get("title", "Okänd titel"),
                "published": entry.get("published", ""),
                "audio_url": audio_url,
                "image":     (entry.get("image") or {}).get("href", ""),
            })
    return episodes

def download_episode(episode, out_dir):
    import yt_dlp
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in episode["title"])[:80]
    out_path = Path(out_dir) / f"{safe_title}.mp3"
    if out_path.exists():
        return out_path
    ydl_opts = {
        "outtmpl": str(Path(out_dir) / f"{safe_title}.%(ext)s"),
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([episode["audio_url"]])
    candidates = list(Path(out_dir).glob(f"{safe_title}*.mp3"))
    if not candidates:
        raise FileNotFoundError("Kunde inte hitta nedladdad fil.")
    return candidates[0]

def transcribe(audio_path, transcript_dir, model_size, language):
    transcript_path = Path(transcript_dir) / (Path(audio_path).stem + ".json")
    if transcript_path.exists():
        with open(transcript_path) as f:
            return json.load(f)
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(str(audio_path), language=language, beam_size=5)
    segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments_iter]
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return segments

def detect_ads_keywords(segments, keywords):
    hits = []
    kw_lower = [k.lower() for k in keywords]
    for seg in segments:
        text = seg["text"].lower()
        matched = [kw for kw in kw_lower if kw in text]
        if matched:
            hits.append({**seg, "reason": f"nyckelord: {', '.join(matched)}"})
    return hits

def detect_ads_ai(segments, api_key, podcast_name):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    chunk_size = 20
    ad_segments = []
    for i in range(0, len(segments), chunk_size):
        chunk = segments[i:i+chunk_size]
        transcript_text = "\n".join(
            f"[{int(s['start']//60):02d}:{int(s['start']%60):02d}] {s['text']}"
            for s in chunk
        )
        prompt = f"""Du analyserar ett transkript från podcasten "{podcast_name}".
Identifiera rader som är reklam/sponsrat innehåll.
Svara ENDAST med JSON, inga andra ord:
{{"ad_segments": [{{"start_time": "mm:ss", "end_time": "mm:ss", "reason": "kort förklaring"}}]}}
Om inga reklamblock finns: {{"ad_segments": []}}
Transkript:
{transcript_text}"""
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
            def time_to_sec(t):
                parts = t.split(":")
                return int(parts[0]) * 60 + float(parts[1])
            for ad in result.get("ad_segments", []):
                start = time_to_sec(ad["start_time"])
                end   = time_to_sec(ad["end_time"])
                for seg in chunk:
                    if abs(seg["start"] - start) < 10:
                        ad_segments.append({**seg, "end": max(seg["end"], end), "reason": f"AI: {ad['reason']}"})
                        break
        except Exception:
            pass
    return ad_segments

def merge_ad_blocks(hits, padding_ms, min_dur, max_dur):
    if not hits:
        return []
    pad_s = padding_ms / 1000
    sorted_hits = sorted(hits, key=lambda x: x["start"])
    blocks = []
    cs = max(0, sorted_hits[0]["start"] - pad_s)
    ce = sorted_hits[0]["end"] + pad_s
    cr = [sorted_hits[0]["reason"]]
    for hit in sorted_hits[1:]:
        hs = hit["start"] - pad_s
        if hs <= ce:
            ce = max(ce, hit["end"] + pad_s)
            cr.append(hit["reason"])
        else:
            blocks.append({"start": cs, "end": ce, "duration": ce-cs, "reasons": list(set(cr))})
            cs, ce, cr = hs, hit["end"]+pad_s, [hit["reason"]]
    blocks.append({"start": cs, "end": ce, "duration": ce-cs, "reasons": list(set(cr))})
    return [b for b in blocks if min_dur <= b["duration"] <= max_dur]

def cut_audio(audio_path, blocks, out_path, crossfade_ms=500):
    duration_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(audio_path)]
    probe = json.loads(subprocess.check_output(duration_cmd))
    total = float(probe["format"]["duration"])
    keep = []
    cursor = 0.0
    for block in sorted(blocks, key=lambda x: x["start"]):
        if cursor < block["start"]:
            keep.append((cursor, block["start"]))
        cursor = block["end"]
    if cursor < total:
        keep.append((cursor, total))
    tmp_dir = Path(out_path).parent / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    segs = []
    fade_s = crossfade_ms / 1000
    for i, (start, end) in enumerate(keep):
        seg = tmp_dir / f"seg_{i:04d}.mp3"
        dur = end - start
        af = f"afade=t=in:st=0:d={fade_s},afade=t=out:st={max(0,dur-fade_s)}:d={fade_s}"
        subprocess.run(["ffmpeg", "-y", "-i", str(audio_path), "-ss", str(start), "-to", str(end), "-af", af, str(seg)], capture_output=True)
        segs.append(seg)
    concat = tmp_dir / "concat.txt"
    with open(concat, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(out_path)], capture_output=True)
    for s in segs:
        s.unlink()
    concat.unlink()
    tmp_dir.rmdir()
    removed_s = sum(b["duration"] for b in blocks)
    return removed_s

def update_user_feed(username, episode, clean_path):
    feed_dir  = user_dir(username) / "feed"
    feed_dir.mkdir(exist_ok=True)
    feed_path  = feed_dir / "feed.xml"
    items_path = feed_dir / "items.json"
    items = []
    if items_path.exists():
        with open(items_path) as f:
            items = json.load(f)
    file_url  = f"{CONFIG['base_url']}/feed/{username}/{Path(clean_path).name}"
    file_size = Path(clean_path).stat().st_size
    if not any(i["url"] == file_url for i in items):
        items.insert(0, {
            "title":     episode["title"] + " [reklamfri]",
            "url":       file_url,
            "published": datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"),
            "size":      file_size,
        })
        with open(items_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    items_xml = ""
    for item in items:
        items_xml += f"""
    <item>
      <title>{item['title']}</title>
      <enclosure url="{item['url']}" length="{item['size']}" type="audio/mpeg"/>
      <pubDate>{item['published']}</pubDate>
      <guid>{item['url']}</guid>
    </item>"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>CleanPod – {username}</title>
    <link>{CONFIG['base_url']}</link>
    <description>Reklamfria podcasts för {username}</description>
    <language>sv</language>
    <itunes:explicit>no</itunes:explicit>
    {items_xml}
  </channel>
</rss>"""
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(xml)

# ── Processing-kö ──────────────────────────────────────────────────────────────

processing_queue = []
processing_status = {}
queue_lock = threading.Lock()

def process_worker():
    while True:
        job = None
        with queue_lock:
            if processing_queue:
                job = processing_queue.pop(0)
        if job:
            run_job(job)
        else:
            time.sleep(5)

def run_job(job):
    username    = job["username"]
    episode     = job["episode"]
    feed_name   = job["feed_name"]
    job_id      = job["id"]

    api_key = load_api_key()

    def update(msg):
        processing_status[job_id] = {"state": "running", "message": msg}

    try:
        update(f"⬇️ Laddar ner: {episode['title'][:40]}...")
        dl_dir = DATA_DIR / "downloads"
        dl_dir.mkdir(exist_ok=True)
        audio_path = download_episode(episode, dl_dir)

        update("🎙️ Transkriberar... (tar 15–30 min)")
        tr_dir = DATA_DIR / "transcripts"
        tr_dir.mkdir(exist_ok=True)
        segments = transcribe(audio_path, tr_dir, CONFIG["whisper_model"], CONFIG["language"])

        update("🔍 Detekterar reklam...")
        kw_hits = detect_ads_keywords(segments, CONFIG["ad_keywords"])
        ai_hits = detect_ads_ai(segments, api_key, feed_name) if api_key else []
        blocks  = merge_ad_blocks(kw_hits + ai_hits, CONFIG["padding_ms"],
                                  CONFIG["min_ad_duration_s"], CONFIG["max_ad_duration_s"])

        update(f"✂️ Klipper {len(blocks)} reklamblock...")
        out_dir = user_dir(username) / "output"
        out_dir.mkdir(exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in episode["title"])[:80]
        out_path = out_dir / f"{safe}_clean.mp3"
        removed_s = cut_audio(audio_path, blocks, out_path, CONFIG["crossfade_ms"])

        update_user_feed(username, episode, out_path)
        save_processed(username, episode["audio_url"])

        users = load_users()
        ntfy_topic = users.get(username, {}).get("ntfy_topic", "")
        send_notification(ntfy_topic, "CleanPod ✅",
                          f"{episode['title'][:50]}\n{removed_s:.0f}s reklam borttaget")

        save_user_history(username, {
            "podcast":   feed_name,
            "title":     episode["title"],
            "removed_s": removed_s,
            "blocks":    len(blocks),
            "date":      datetime.now().isoformat(),
        })

        processing_status[job_id] = {
            "state": "done",
            "message": f"✅ Klar!\n{episode['title']}\n{removed_s:.0f}s reklam borttaget"
        }

    except Exception as e:
        processing_status[job_id] = {"state": "error", "message": f"❌ Fel: {str(e)}"}

# ── Vyer ──────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    username = session["username"]
    feeds    = load_user_feeds(username)
    history  = load_user_history(username)
    files    = sorted((user_dir(username) / "output").glob("*.mp3"), reverse=True) if (user_dir(username) / "output").exists() else []
    return render_template("index.html",
        username=username,
        feeds=feeds,
        history=history,
        files=files,
        config=CONFIG,
        is_admin=(username == "admin")
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        users = load_users()
        if username in users and users[username]["password"] == hash_password(password):
            session["username"] = username
            return redirect(url_for("index"))
        error = "Fel användarnamn eller lösenord."
    return render_template("login.html", error=error, config=CONFIG)

@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        code     = request.form.get("code", "").strip()
        users    = load_users()
        codes    = load_invite_codes()

        if len(users) >= CONFIG["max_users"]:
            error = "Max antal användare uppnått."
        elif code not in codes or codes[code]["used"]:
            error = "Ogiltig eller redan använd inbjudningskod."
        elif username in users:
            error = "Användarnamnet är redan taget."
        elif len(username) < 3:
            error = "Användarnamnet måste vara minst 3 tecken."
        elif len(password) < 6:
            error = "Lösenordet måste vara minst 6 tecken."
        else:
            users[username] = {
                "password":   hash_password(password),
                "ntfy_topic": "",
                "created":    datetime.now().isoformat(),
            }
            save_users(users)
            codes[code]["used"] = True
            save_invite_codes(codes)
            session["username"] = username
            return redirect(url_for("index"))
    return render_template("register.html", error=error, config=CONFIG)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    username = session["username"]
    users    = load_users()
    message  = ""
    if request.method == "POST":
        ntfy = request.form.get("ntfy_topic", "").strip()
        users[username]["ntfy_topic"] = ntfy
        save_users(users)
        message = "Inställningar sparade!"
    return render_template("settings.html",
        username=username,
        ntfy_topic=users[username].get("ntfy_topic", ""),
        message=message,
        config=CONFIG
    )

@app.route("/admin")
@login_required
@admin_required
def admin():
    users = load_users()
    codes = load_invite_codes()
    return render_template("admin.html",
        users=users,
        codes=codes,
        config=CONFIG
    )

@app.route("/admin/create_code", methods=["POST"])
@login_required
@admin_required
def create_code():
    codes = load_invite_codes()
    code  = str(uuid.uuid4())[:8].upper()
    codes[code] = {"used": False, "created": datetime.now().isoformat()}
    save_invite_codes(codes)
    return redirect(url_for("admin"))

@app.route("/admin/delete_user", methods=["POST"])
@login_required
@admin_required
def delete_user():
    username = request.form.get("username")
    if username and username != "admin":
        users = load_users()
        users.pop(username, None)
        save_users(users)
    return redirect(url_for("admin"))

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/episodes")
@login_required
def api_episodes():
    feed_url  = request.args.get("url", "")
    if not feed_url:
        return jsonify({"episodes": []})
    episodes = fetch_episodes(feed_url)
    return jsonify({"episodes": episodes[:20]})

@app.route("/api/add_feed", methods=["POST"])
@login_required
def api_add_feed():
    username = session["username"]
    data     = request.json
    url      = data.get("url", "").strip()
    name     = data.get("name", "").strip()
    if not url or not name:
        return jsonify({"ok": False, "error": "URL och namn krävs."})
    feeds = load_user_feeds(username)
    if any(f["url"] == url for f in feeds):
        return jsonify({"ok": False, "error": "Podcasten finns redan."})
    feeds.append({"name": name, "url": url, "language": "sv"})
    save_user_feeds(username, feeds)
    return jsonify({"ok": True})

@app.route("/api/remove_feed", methods=["POST"])
@login_required
def api_remove_feed():
    username = session["username"]
    url      = request.json.get("url", "")
    feeds    = [f for f in load_user_feeds(username) if f["url"] != url]
    save_user_feeds(username, feeds)
    return jsonify({"ok": True})

@app.route("/api/process", methods=["POST"])
@login_required
def api_process():
    username = session["username"]
    data     = request.json
    episode  = data.get("episode")
    feed_name = data.get("feed_name", "")
    if not episode:
        return jsonify({"ok": False})
    job_id = str(uuid.uuid4())[:8]
    processing_status[job_id] = {"state": "running", "message": "⏳ Köad..."}
    with queue_lock:
        processing_queue.append({
            "id":        job_id,
            "username":  username,
            "episode":   episode,
            "feed_name": feed_name,
        })
    return jsonify({"ok": True, "job_id": job_id})

@app.route("/api/status/<job_id>")
@login_required
def api_status(job_id):
    return jsonify(processing_status.get(job_id, {"state": "unknown", "message": ""}))

@app.route("/api/queue_status")
@login_required
def api_queue_status():
    with queue_lock:
        return jsonify({"queue_length": len(processing_queue)})

# ── Filservering ───────────────────────────────────────────────────────────────

@app.route("/feed/<username>/feed.xml")
def user_feed(username):
    feed_dir = user_dir(username) / "feed"
    return send_from_directory(feed_dir, "feed.xml")

@app.route("/feed/<username>/<path:filename>")
def user_audio(username, filename):
    out_dir = user_dir(username) / "output"
    return send_from_directory(out_dir, filename)
@app.route("/api/change_password", methods=["POST"])
@login_required
def api_change_password():
    username = session["username"]
    data     = request.json
    old_pw   = data.get("old_password", "")
    new_pw   = data.get("new_password", "")
    users    = load_users()
    if users[username]["password"] != hash_password(old_pw):
        return jsonify({"ok": False, "error": "Fel nuvarande lösenord."})
    if len(new_pw) < 6:
        return jsonify({"ok": False, "error": "Losenordet maste vara minst 6 tecken."})
    users[username]["password"] = hash_password(new_pw)
    save_users(users)
    return jsonify({"ok": True})



if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "users").mkdir(exist_ok=True)

    # Skapa admin-konto om det inte finns
    users = load_users()
    if "admin" not in users:
        users["admin"] = {
            "password": hash_password("admin123"),
            "ntfy_topic": "",
            "created": datetime.now().isoformat(),
        }
        save_users(users)
        print("✅ Admin-konto skapat. Användarnamn: admin, Lösenord: admin123")
        print("   Byt lösenord direkt under Inställningar!")

    # Starta processing-worker
    threading.Thread(target=process_worker, daemon=True).start()
    print(f"🌐 CleanPod startar på port {CONFIG['server_port']}")
    app.run(host='0.0.0.0', port=CONFIG['server_port'], debug=False)
