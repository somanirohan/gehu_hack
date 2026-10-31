# App changes for Rohan (no code here, just what and why)

Good news first: **the app can already talk to the dashboard with zero code changes.**
Its existing sync (SyncFlushWorker → CivilizationSyncClient, schema `bitchat.civ.sync/v1`)
posts exactly what the dashboard now accepts at:

```
https://<tunnel-address>/api/v1/bitchat/civ-sync
```

Set it in Sync settings, turn Sync on, press Send now. Everything below makes it
faster, more reliable and better for the demo. Do them in order; stop wherever time runs out.

The dashboard side of every item below is already built and tested. Nothing on the
server has to change when Rohan ships these.

---

## Must do (day 1, about 2–3 hours total)

### 1. Upload new SOS messages immediately when online
**Problem:** today the app uploads only when internet *comes back* (MeshForegroundService
connectivity listener) or when someone presses **Send now**. A phone that is already online
does not upload a new SOS until one of those happens. For a "real-time" demo that's the
biggest gap.

**Change:** call `SyncWorkScheduler.scheduleFlush(...)` after:
- the user sends an SOS (`ChatViewModel.sendSOS`) or any geo-tagged broadcast, and
- the phone *receives* a geo-tagged public message from the mesh (this makes every online
  phone a gateway for offline phones nearby).

Add a short debounce (about 3 s) so a burst of messages makes one upload.
Also consider changing `ExistingWorkPolicy.REPLACE` to `KEEP` or `APPEND_OR_REPLACE`:
REPLACE can cancel an upload that is already running. Nothing is lost either way, because
the next upload re-sends the last 200 messages and the server ignores repeats.

Optional safety net: a periodic flush every 1–2 minutes while Sync is on and online.

### 2. Never send an SOS without a location silently
**Problem:** `sendSOS` adds `geo:lat,lon` only if `currentLocation()` returns something.
Without the tag, `extractIncidents` drops the message, so it never reaches the dashboard,
and the user doesn't know.

**Change:** if no current fix, use the last known location (and say "approximate location"),
or let the user tap their spot on the offline map. If there's still nothing, show
"No GPS: your SOS reached nearby phones but cannot be placed on the control-room map."

### 3. Show the person their SOS reached the control room
The server's reply now includes `accepted_ids`: the message ids it stored (new or already
seen). After a successful upload, mark those messages with a small "✓ Control room received"
tick. That gives the delivery states the PS asks for:
`saved on phone → sent on mesh → uploaded → control room received`.

### 4. Check: is a message's `id` the same on every phone?
If phone A's SOS is relayed to phones B and C and both upload it, the server de-duplicates
by `id`. Please check that the id is created by the sender and carried in the packet (not
generated again on each receiving phone). If it isn't, tell Shiv; the dashboard will still
merge them by place and time, but the report count will be too high.

---

## Should do (day 1 night / day 2)

### 5. Let the person choose what kind of emergency
Today the dashboard *guesses* the type from the words (English/Hindi/Hinglish rules) and
labels it "rule suggestion". If the SOS screen offers buttons, the guess becomes a choice.

Add two optional fields to each item in `incidents` in SyncBundleBuilder:

| field | example | meaning |
|---|---|---|
| `category` | `"trapped"` | one of: trapped, injured, medical, fire, flood, landslide, collapse, accident, missing, crowd, other, or `road_block` |
| `people` | `4` | how many people need help |

The dashboard already reads these: when present they win over the guess and the label
changes to "chosen in app". Old app versions without them keep working.

### 6. A "Road blocked" quick button
Sends a geo-tagged broadcast starting with ⛔ (for example `⛔ Road blocked: landslide`),
or with `category: "road_block"`. Messages from users whose role is AMBULANCE, FIRE or GOV
block the road immediately and re-route any unit driving through it; citizen reports need
two reports or an officer's confirmation first. So for the demo, set the "official" test
phone's role to GOV.

### 7. Pre-fill the endpoint for the demo
Typing the long tunnel URL on 4 phones is error-prone. A QR scan or a "paste from clipboard"
button in Sync settings is enough.

---

## Nice to have (only if time is left)

### 8. Photos with the SOS
Upload a photo separately (works on slow links, retries on its own):
`POST /api/v1/media` as multipart with `media_id` (any unique string) and `file`.
Then put `"media_ids": ["<that id>"]` on the incident item. Send the SOS text first; the
photo can arrive later; the dashboard shows "Photo arriving…" until it does.

### 9. Camera phone (CCTV / drone camera)
A second phone running a camera app can post detections to `POST /api/v1/events`:

```
{ "event_id": "cam1-<unique>", "kind": "sos", "created_at": "<ISO time>",
  "device_id": "camera-1", "lat": 30.3165, "lon": 78.0322,
  "payload": { "type": "fall", "people": 1, "message": "person down at gate 2",
               "category_source": "camera AI suggestion", "confidence": 0.82 } }
```

The dashboard shows it as an AI suggestion, never as confirmed fact.

### 10. Anything new
Any new kind of event (for example `supply_need`, `safe_checkin`) posted to
`/api/v1/events` appears in the dashboard's Live feed automatically with all its fields.
To give it a nice label and icon, add it to `backend/event_kinds.json` (no code).

---

## How Rohan can test without the dashboard laptop
Point the endpoint at the tunnel, send an SOS, press Send now, then open
`https://<tunnel-address>/api/v1/bitchat/sync-status`: it lists every upload the
server received and how many were new.
