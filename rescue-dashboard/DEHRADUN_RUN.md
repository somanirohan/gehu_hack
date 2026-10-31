# Running the live Dehradun system (free)

What runs where:

```
Phones with the bitchat app (mesh, offline)
   │  any phone that gets internet uploads everyone's geo-tagged messages
   ▼  POST https://<your-tunnel>/api/v1/bitchat/civ-sync     (the app's EXISTING sync)
Your laptop: FastAPI backend (port 8001) + SQLite
   ├─ /             control-room dashboard (Dehradun map)
   ├─ /responder/   responder site for ambulance / SDRF / fire / police phones
   └─ /api/v1/...   events, hazards, re-routing, shelters, feed
Cloudflare quick tunnel (free, no account) gives the laptop a public https address
```

Nothing here costs money. The laptop must stay on and online during the demo.

---

## 1. One-time setup (Windows, PowerShell)

Needs Python 3.10+ and Node 18+.

```powershell
cd rescue-dashboard\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd ..\frontend
Remove-Item -Recurse -Force node_modules -ErrorAction SilentlyContinue   # old modules came from another PC
npm install
npm run build

cd ..\responder
npm install
npm run build
```

## 2. Real Dehradun roads (do this once, ~5–10 min)

Without this the backend uses OSRM over the internet for routes, and cannot avoid
blocked roads offline. With it, routes follow real Dehradun roads and avoid hazards.

```powershell
cd rescue-dashboard
pip install osmnx==2.0.1
python tools\build_graph.py --lat 30.25 --lon 78.07 --km 14 --out backend\roads_dehradun.graphml
```

A 14 km radius covers Prem Nagar, Clock Tower, Sahastradhara, Raipur, Clement Town,
Doiwala and Jolly Grant airport. (Raiwala is outside it; use `--km 25` if you need it,
which makes a bigger file and a slower start.)

## 3. Check place positions (once, 30 s)

11 places were checked against Wikipedia/latlong.net. 7 are marked "approximate"
(Clock Tower, IT Park, Rispana bridge, Jakhan, ISBT, Mianwala, Lacchiwala).
This fixes them from OpenStreetMap:

```powershell
python tools\dehradun_places.py
```

## 4. Start everything (every time)

Terminal 1, backend:

```powershell
cd rescue-dashboard\backend
.\.venv\Scripts\Activate.ps1
$env:ROAD_GRAPH = "roads_dehradun.graphml"
uvicorn main:app --host 0.0.0.0 --port 8001
```

Open http://localhost:8001: the map should open on Dehradun with flood (blue) and
accident (orange) spots. Check http://localhost:8001/api/v1/routing/status says
`road graph: roads_dehradun.graphml`.

Terminal 2, public address (free):

```powershell
winget install --id Cloudflare.cloudflared      # once
cloudflared tunnel --url http://localhost:8001
```

It prints an address like `https://random-words.trycloudflare.com`. That address
changes every time you restart cloudflared, so re-enter it on the phones if it changes.

## 5. Connect the phones (no code change needed for this step)

On each phone running the app: open **Sync settings**:

1. Turn **Sync** on (it is off by default).
2. Endpoint URL: `https://random-words.trycloudflare.com/api/v1/bitchat/civ-sync`
3. Press **Send now**. "Last synced" should show the time with no error.

On the dashboard the top bar changes to "Phones last synced just now".

Send a test: press the app's SOS button and type "test 2 log fase hain". Then press
**Send now** on any phone with internet (until Rohan's change #1 is done, the app only
uploads when internet comes back or when Send now is pressed). The dashboard beeps,
shows a toast, and the incident appears with a "rule suggestion" label.

Only messages with a location reach the map. The SOS button adds GPS automatically;
for normal messages use the 📍 toggle in the composer.

## 6. Responder phones

Open `https://random-words.trycloudflare.com/responder/` on the responder's phone
and log in with the unit code: AMB1, AMB2, RES3, BOA4, FIR5, DRO6, POL7.
**PIN for all is 1234: change it before any public demo** (table `responders`, column `pin`).
"Add to home screen" makes it work like an app. Turn on GPS sharing so the dashboard sees it move.

## 7. Practice drill (for the video and judges)

With the backend running:

```powershell
python simulator\drill_dehradun.py               # or --url https://random-words.trycloudflare.com
```

It sends 5 Hinglish SOS messages at real Dehradun flood/accident spots in the app's exact
sync format, re-sends 2 (they must not duplicate), sends a second report near Tapkeshwar
(it must merge), waits for you to press **Approve dispatch**, then sends an official
"road band, landslide" message on that unit's route. The unit is re-routed on both the
dashboard (orange route) and the responder site. Everything from the drill shows a
**DRILL** badge. Press Reset (or `POST /api/demo/reset`) afterwards.

## What was tested and what was not

Tested here (26 automated tests + browser check): the sync format from the app's source
code, duplicates, merging, drill labels, official vs citizen road blocks, re-routing on a
synthetic 23,000-junction grid laid over Dehradun, drone straight-line routes, the dashboard
and responder site in a browser.

NOT tested yet, please check on your laptop:
- Routing on the real Dehradun road file (build step 2, then run the drill).
- A real phone posting through the Cloudflare tunnel (step 5).
- Map tiles (they load from OpenStreetMap, which the test machine could not reach).
- WebSockets through the tunnel. If the dashboard says "Reconnecting…" through the tunnel,
  open it at http://localhost:8001 on the laptop instead; phones only need the POST.
