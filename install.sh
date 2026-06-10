#!/bin/bash
# CleanPod – Installationsscript
# Kör med: curl -sSL https://raw.githubusercontent.com/kallekanonkul/cleanpod/main/install.sh | bash

set -e

echo ""
echo "🎙️  CleanPod – Installerar..."
echo ""

# Systempaket
sudo apt-get update -q
sudo apt-get install -y python3 python3-pip ffmpeg curl git

# Klona repo
cd ~
if [ -d "cleanpod" ]; then
    echo "📁 cleanpod-mapp finns redan, uppdaterar..."
    cd cleanpod
    git pull
else
    git clone https://github.com/kallekanonkul/cleanpod.git
    cd cleanpod
fi

# Python-paket
pip3 install --break-system-packages \
    openai-whisper yt-dlp feedparser flask anthropic requests \
    torch --extra-index-url https://download.pytorch.org/whl/cpu

# Skapa datamappar
mkdir -p data/{users,feeds,downloads,transcripts,output,history}

# Systemd-tjänst
USERNAME=$(whoami)
HOME_DIR=$(eval echo ~$USERNAME)

sudo tee /etc/systemd/system/cleanpod.service > /dev/null << EOF
[Unit]
Description=CleanPod Podcast Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 $HOME_DIR/cleanpod/app.py
WorkingDirectory=$HOME_DIR/cleanpod
Restart=always
User=$USERNAME

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable cleanpod
sudo systemctl start cleanpod

echo ""
echo "✅ CleanPod installerat!"
echo ""
echo "Öppna webbläsaren och gå till: http://localhost:8080"
echo "Logga in med: admin / admin123"
echo "Byt lösenord direkt under Inställningar!"
echo ""
