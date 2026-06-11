#!/bin/bash
cd /home/robert/cleanpod
git pull origin main
sudo systemctl restart cleanpod
echo "✅ CleanPod uppdaterad $(date)"
