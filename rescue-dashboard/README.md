# Rescue Control Room · Dehradun

The control-room part of our offline-first disaster response system.

- Phones running the **bitchat mesh app** send SOS messages. Any phone that gets internet
  uploads everyone's messages.
- The **dashboard** shows them live on a Dehradun map. It merges duplicates, ranks by
  priority, suggests the nearest unit, and dispatches only after an officer approves.
- The **responder site** shows the assigned ambulance, SDRF, fire or police unit its task
  and road route. It re-routes the unit when a road gets blocked.
- Every action goes into a tamper-evident log.

```
Phones (bitchat app, mesh, offline)
   │  a phone with internet uploads    POST /api/v1/bitchat/civ-sync
   ▼
Laptop: FastAPI backend :8001 + SQLite
   ├─ http://localhost:8001/            control-room dashboard
   ├─ http://localhost:8001/responder/  responder site (open on responder phones)
   └─ http://localhost:8001/docs        all API endpoints
Cloudflare quick tunnel (free) → public https address for the phones
```

Other guides in this folder:
- [DEHRADUN_RUN.md](DEHRADUN_RUN.md): more detail on hosting and phones
- [ROHAN_APP_CHANGES.md](ROHAN_APP_CHANGES.md): app-side changes

---

## 1. What you need

| Tool | Version | Check with |
|---|---|---|
| Python | 3.10 or newer | `python --version` |
| Node.js | 18 or newer | `node --version` |
| Internet | only for setup, map tiles and the tunnel | |

The commands below are for **Windows PowerShell**. On Mac or Linux, use `python3`,
`source .venv/bin/activate`, `export ROAD_GRAPH=...` and `/` instead of `\`.

---

## 2. First-time setup (once, about 15 minutes)

Open PowerShell inside the `rescue-dashboard` folder.

### 2a. Backend (Python)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
```

> If PowerShell says "running scripts is disabled", run this once and try again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 2b. Dashboard and responder site (Node)

```powershell
cd frontend
npm install
npm run build
cd ..\responder
npm install
npm run build
cd ..
```

`npm run build` creates the `dist` folders. The backend serves them, so later you only
run **one** server.

### 2c. Real Dehradun roads (recommended)

This downloads the real road network once. With it, routes follow Dehradun roads and
avoid blocked roads even without internet.

```powershell
.\backend\.venv\Scripts\Activate.ps1
pip install osmnx==2.0.1
python tools\build_graph.py --lat 30.25 --lon 78.07 --km 14 --out backend\roads_dehradun.graphml
```

The 14 km radius covers Prem Nagar, Clock Tower, Sahastradhara, Raipur, Clement Town,
Doiwala and Jolly Grant airport. If you skip this step, routes come from the online OSRM
service and can't avoid blocked roads.

### 2d. Fix approximate place positions (30 seconds)

```powershell
python tools\dehradun_places.py
```

Seven map spots were marked "approximate". This corrects them from OpenStreetMap.

---

## 3. Start it (every time)

### Terminal 1: backend, dashboard and responder site

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:ROAD_GRAPH = "roads_dehradun.graphml"     # skip this line if you skipped step 2c
uvicorn main:app --host 0.0.0.0 --port 8001
```

Open **http://localhost:8001**. The map should open on Dehradun, with blue flood spots
and orange accident spots.

To check routing, open http://localhost:8001/api/v1/routing/status. It should say
`road graph: roads_dehradun.graphml`.

### Terminal 2: public address for the phones (free)

```powershell
winget install --id Cloudflare.cloudflared      # first time only
cloudflared tunnel --url http://localhost:8001
```

Copy the `https://something.trycloudflare.com` address it prints. It changes every
time you restart cloudflared.

### Terminal 3 (optional): practice drill

```powershell
cd rescue-dashboard
.\backend\.venv\Scripts\Activate.ps1
python simulator\drill_dehradun.py
```

---

## 4. Connect the phones (bitchat app)

On every phone, open **Sync settings** in the app:

1. Turn **Sync** on.
2. Set the endpoint URL to `https://something.trycloudflare.com/api/v1/bitchat/civ-sync`.
3. Press **Send now**. "Last synced" should show the time with no error.

The dashboard's top bar now says "Phones last synced just now".

Things to know:
- Only messages **with a location** reach the map. The SOS button adds GPS on its own.
  For normal messages, turn on the 📍 toggle.
- Until Rohan's change #1 is in, an online phone uploads only when internet reconnects
  or when **Send now** is pressed. During the demo, press Send now after each SOS.
- To make a phone's road-block messages count immediately, set its role to **GOV**,
  AMBULANCE or FIRE. Citizen road reports need 2 reports or an officer's confirmation.

---

## 5. Responder phones

Open `https://something.trycloudflare.com/responder/` on the responder's phone and log in:

| Unit | Code | Starts at |
|---|---|---|
| Ambulance 108-A | AMB1 | Railway station |
| Ambulance 108-B | AMB2 | Clement Town |
| SDRF Team 1 | RES3 | Raipur |
| SDRF Boat 2 | BOA4 | Doiwala |
| Fire Tender 3 | FIR5 | City centre |
| Drone Unit 1 | DRO6 | Jolly Grant airport |
| Police PCR 7 | POL7 | Prem Nagar |

The PIN is **1234** for every unit. Change it before a public demo: it's the `pin` column
in the `responders` table of `backend/rescue.db`.

Use "Add to home screen" to make it work like an app, and allow location access so the
unit moves on the dashboard.

---

## 6. Demo flow (about 3 minutes)

1. Press **Reset demo** (top right of the map) to clear old data.
2. Run `python simulator\drill_dehradun.py`. Five Hinglish SOS messages arrive at real
   Dehradun spots, with a beep and a pop-up each time.
3. Duplicates are ignored, and a second report near Tapkeshwar merges into the first.
   Everything from the drill shows a **DRILL** badge.
4. Click the top incident, read why it has that priority, and press **Approve dispatch**.
5. The drill now sends an official "road band, landslide" message on the unit's route.
   The route turns orange on the dashboard, and the responder site shows "New route".
6. Optional: click **Mark road blocked** on the map, then click a road to block it yourself.
7. The **Live feed** tab shows every raw message, which phone and role sent it, how long
   it waited offline, and the words the rules matched ("rule suggestion").
8. The **Action log** tab plus "Log intact" in the top bar show the tamper-evident log.

To use real phones instead of the drill, send SOS messages from the app (section 4).

---

## 7. Working on the code (live reload)

To edit the dashboard and see changes instantly, keep the backend running on 8001 and:

```powershell
cd frontend
npm run dev        # open http://localhost:5173 (it talks to the backend on 8001)
```

Do the same in `responder` (it opens on http://localhost:5174). After editing, run `npm run build`
again so http://localhost:8001 shows the new version.

Run the backend tests:

```powershell
cd backend
pip install pytest httpx
python -m pytest -q          # 27 tests should pass
```

---

## 8. Problems and fixes

| What you see | Fix |
|---|---|
| Dashboard shows "Cannot reach the backend" | Terminal 1 isn't running, or it isn't on port 8001. |
| http://localhost:8001 shows `{"detail":"Not Found"}` | Run `npm run build` in `frontend` (step 2b), then restart the backend. |
| Map is grey | Map tiles need internet. Check the laptop is online. |
| Phone "Last synced" shows an error | Check the URL ends in `/api/v1/bitchat/civ-sync`, cloudflared is still running, and the address hasn't changed. |
| Phone synced but nothing appeared | The message had no location. Use the SOS button or the 📍 toggle. Open `/api/v1/bitchat/sync-status` to see what arrived. |
| Routes are straight lines | No road file and no internet for OSRM. Do step 2c. Drone routes are straight on purpose. |
| Dashboard says "Reconnecting…" through the tunnel | Open the dashboard at http://localhost:8001 on the laptop instead. The phones only need the tunnel to upload. |
| `npm install` errors about a missing module | Delete `node_modules` and `package-lock.json` in that folder, then run `npm install` again. |
| Start fresh | Stop the backend, delete `backend\rescue.db`, start again. |

---

## 9. Folder map

```
backend/
  main.py              API, database, log, websocket (serves both websites)
  logic.py             merging, priority, unit suggestion rules
  v1.py                events, photos, road blocks, re-routing, responder login
  bridge.py            receives the bitchat app's sync upload
  classify.py          English / Hindi / Hinglish word rules
  routing.py           road routing that avoids blocked roads; drone straight line
  places.py + dehradun_places.json   Dehradun spots, risk areas, unit start points
  event_kinds.json     labels and icons for message kinds (add new kinds here)
  test_*.py            automated tests
frontend/              control-room dashboard (React + Leaflet)
responder/             responder site (works offline, installable)
simulator/
  drill_dehradun.py    practice drill in the app's exact format
  simulate.py, simulate_field.py   older demo scripts (Dehradun spots)
tools/
  build_graph.py       download the real road network
  dehradun_places.py   correct place positions from OpenStreetMap
```

---

## 10. API for other teammates (camera AI, new features)

All endpoints with "try it" buttons: **http://localhost:8001/docs**

| Who | Send to | Notes |
|---|---|---|
| bitchat app | `POST /api/v1/bitchat/civ-sync` | The app's existing sync. Optional extra fields per item: `category`, `people`, `media_ids`. The reply lists `accepted_ids`. |
| Camera phone / AI | `POST /api/v1/events` | Example below. Shown as an AI suggestion. |
| Photos | `POST /api/v1/media` | Multipart with `media_id` and `file`. Can arrive before or after the message that names it. |
| Older format | `POST /api/reports` | Still works. |

Camera example:

```json
{ "event_id": "cam1-0001", "kind": "sos", "created_at": "2026-10-31T10:00:00+05:30",
  "device_id": "camera-1", "lat": 30.3165, "lon": 78.0322,
  "payload": { "type": "fall", "people": 1, "message": "person down at gate 2",
               "category_source": "camera AI suggestion", "confidence": 0.82 } }
```

Incident types: `trapped, injured, medical, fire, flood, landslide, collapse, accident,
missing, crowd, fall, other`. Any new `kind` (for example `supply_need`) shows up in the
Live feed automatically. Add it to `backend/event_kinds.json` to give it a label and icon.

## Decision rules

- **Merging:** a report joins an open incident of the same family within 150 m and 30 minutes.
- **Priority 0–100:** type + number of people + extra reports + waiting time. The reason is
  shown next to the score.
- **Suggestion:** the nearest available unit that can handle that type. An officer must approve.
- **Road blocks:** official roles and responders block a road immediately. Citizens need 2
  reports or an officer's confirmation. Units already driving through it are re-routed.
- **No AI sets a number.** Text and camera categories are labelled as suggestions until an
  officer acts.
