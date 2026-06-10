# 🎙️ CleanPod

CleanPod tar bort reklam från dina favoritpodcasts automatiskt. Du får en personlig RSS-feed som du prenumererar på i Overcast på din iPhone.

## Vad behöver du?

- En Raspberry Pi 4 eller 5 (med Raspberry Pi OS 64-bit)
- Internetuppkoppling
- En iPhone med [Overcast](https://apps.apple.com/se/app/overcast/id888422857) installerat

## Installera

Öppna terminalen på din Raspberry Pi och kör:

```bash
curl -sSL https://raw.githubusercontent.com/kallekanonkul/cleanpod/main/install.sh | bash
```

Det tar 15–30 minuter första gången (laddar ner AI-modellen).

## Kom igång

1. Öppna webbläsaren och gå till `http://localhost:8080`
2. Logga in med **admin / admin123**
3. Byt lösenord under ⚙️ Inställningar
4. Gå till **Admin** och skapa en inbjudningskod för varje användare
5. Dela koden med dina vänner

## För användare

1. Gå till CleanPod-adressen du fått
2. Klicka **Registrera med inbjudningskod**
3. Skapa ditt konto
4. Gå till **Podcasts** och lägg till din RSS-feed
5. Välj ett avsnitt och tryck **Bearbeta**
6. Gå till **Min feed** och kopiera din personliga adress
7. Öppna Overcast → **+** → **Add URL** → klistra in adressen

## Notiser på iPhone

1. Ladda ner [Ntfy](https://apps.apple.com/se/app/ntfy/id1625396347) från App Store
2. Prenumerera på ett unikt ämne t.ex. `dittnamn-cleanpod`
3. Ange samma ämne under ⚙️ Inställningar i CleanPod

Du får nu en notis på iPhone när ett avsnitt är klart!

## Nå CleanPod hemifrån och utifrån

För att nå CleanPod från telefonen utanför hemmet behöver du:

1. Skaffa gratis adress på [dynu.com](https://www.dynu.com)
2. Öppna port 8080 i routerns inställningar
3. Uppdatera `base_url` i `app.py` med din Dynu-adress

## Felsökning

```bash
sudo systemctl status cleanpod
sudo journalctl -u cleanpod -n 50
```
