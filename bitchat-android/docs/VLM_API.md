# Bitchat VLM API Documentation

## Overview

Bitchat exposes a vision-language model (VLM) integration API that allows external applications to send images and text descriptions to the Bitchat mesh network. This enables VLM systems running on other machines to share visual analysis, dense captions, and screen descriptions through Bitchat's decentralized messaging infrastructure.

**API Protocol:** HTTP REST over local network  
**Default Port:** 8765 (configurable in app settings)  
**Transport:** WiFi network or ADB port forwarding  
**Binding:** `0.0.0.0` (all interfaces - accessible from localhost, WiFi, and USB)  
**Security:** Local network only (no authentication, use on trusted networks)

---

## Quick Start

### 1. Enable VLM API on Bitchat

1. Open Bitchat app
2. Navigate to **Settings** → **VLM API Settings**
3. Toggle **Enable VLM API**
4. Note the HTTP port (default: 8765)

### 2. Connect from Your VLM Machine

**Option A: Same WiFi Network**
```bash
# Find your Android device's WiFi IP
adb shell ip addr show wlan0 | grep "inet " | awk '{print $2}' | cut -d/ -f1

# Or check: Settings → WiFi → tap connected network → IP address
```

**Option B: USB/ADB Port Forwarding** (Recommended for development)
```bash
adb forward tcp:8765 tcp:8765

# Test connection
curl http://127.0.0.1:8765/status
```

### 3. Send Your First Message

```python
import requests

# Send text message
response = requests.post(
    "http://127.0.0.1:8765/send/text",
    json={"text": "Hello from VLM!", "channel": "general"}
)
print(response.json())
```

---

## API Endpoints

### Base URL

- **WiFi:** `http://<ANDROID_WIFI_IP>:8765`
- **ADB Forward:** `http://127.0.0.1:8765`

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Get API status and mesh info |
| `/settings` | GET | Get current VLM settings |
| `/settings` | POST | Update VLM settings |
| `/send/text` | POST | Send text message |
| `/send/image` | POST | Send image with optional caption |
| `/send/analysis` | POST | Send image + dense captioning |
| `/silence` | POST | Toggle silence mode (pause messages) |

---

## Endpoint Details

### 1. Status Check

**GET `/status`**

Returns API status and mesh network information.

**Response:**
```json
{
  "status": "ok",
  "api_enabled": true,
  "http_port": 8765,
  "silence_enabled": false,
  "default_destination": {
    "type": "channel",
    "id": "vision"
  },
  "mesh_running": true,
  "peers_count": 3,
  "rate_limit_ms": 5000
}
```

---

### 2. Get Settings

**GET `/settings`**

Returns current VLM API configuration.

**Response:**
```json
{
  "status": "ok",
  "enabled": true,
  "http_port": 8765,
  "silence_enabled": false,
  "rate_limit_ms": 5000,
  "default_destination": {
    "type": "peer",
    "id": "alice"
  }
}
```

---

### 3. Update Settings

**POST `/settings`**

Modify VLM API configuration.

**Request Body:**
```json
{
  "enabled": true,
  "http_port": 8765,
  "silence_enabled": false,
  "rate_limit_ms": 10000,
  "default_destination": {
    "type": "channel",
    "id": "vision"
  }
}
```

**Response:**
```json
{
  "status": "ok",
  "enabled": true,
  "http_port": 8765,
  ...
}
```

---

### 4. Send Text Message

**POST `/send/text`**

Send a text message through the Bitchat mesh.

**Request Body:**
```json
{
  "text": "VLM analysis: Object detected with 98% confidence",
  "peer_id": "alice",    // Optional: for private message
  "channel": "vision"    // Optional: for channel message
}
```

**Response:**
```json
{
  "status": "ok",
  "message_id": "vlm-1699887654321"
}
```

**Error Response:**
```json
{
  "status": "error",
  "error": "VLM API is disabled"
}
```

---

### 5. Send Image

**POST `/send/image`**

Send an image file with optional caption through the Bitchat mesh.

**Request (Multipart Form):**
```
POST /send/image
Content-Type: multipart/form-data

image: <binary image file>
caption: "Optional caption text"
peer_id: "alice"        // Optional
channel: "vision"       // Optional
```

**Alternative: Base64 Encoding**
```
POST /send/image
Content-Type: application/x-www-form-urlencoded

image_base64=<base64_encoded_image>
caption=Optional+caption
peer_id=alice
```

**Response:**
```json
{
  "status": "ok",
  "message": "Image send initiated"
}
```

**Notes:**
- Supported formats: JPEG, PNG, GIF, WebP (auto-detected)
- Maximum file size: 10MB (configurable in `AppConstants.Media.MAX_FILE_SIZE_BYTES`)
- Image is sent asynchronously via mesh file transfer protocol

---

### 6. Send Analysis (Image + Description)

**POST `/send/analysis`**

Send both an image and VLM-generated dense captioning/analysis in a single request.

**Request (Multipart Form):**
```
POST /send/analysis
Content-Type: multipart/form-data

image: <binary image file>
description: "Dense caption: A person standing near a red car in a parking lot. The scene shows..."
peer_id: "alice"        // Optional
channel: "vision"       // Optional
```

**Alternative: Base64 Encoding**
```
POST /send/analysis
Content-Type: application/x-www-form-urlencoded

image_base64=<base64_encoded_image>
description=Your+VLM+analysis+text
```

**Alternative: Text Only (No Image)**
```json
{
  "description": "VLM detected: 3 people, 2 cars, sunny weather"
}
```

**Response:**
```json
{
  "status": "ok",
  "message": "Analysis send initiated"
}
```

**Use Cases:**
- Send screenshot with VLM-generated description
- Share camera frame analysis from VLM
- Describe visual content from video stream
- Report detected objects/scene understanding

---

### 7. Toggle Silence Mode

**POST `/silence`**

Pause or resume all VLM message sending (emergency stop).

**Request Body:**
```json
{
  "enabled": true
}
```

**Response:**
```json
{
  "status": "ok",
  "silence_enabled": true
}
```

---

## Integration Examples

### Python Client (Complete)

```python
import requests
import base64
from PIL import ImageGrab
import io

class BitchatVLMClient:
    """
    Bitchat VLM API client for sending images and dense captions.
    
    Usage:
        # Via ADB forward
        client = BitchatVLMClient("http://127.0.0.1:8765")
        
        # Via WiFi
        client = BitchatVLMClient("http://192.168.1.105:8765")
    """
    
    def __init__(self, base_url="http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")
    
    def check_status(self):
        """Check VLM API status and mesh connection."""
        try:
            response = requests.get(f"{self.base_url}/status", timeout=5)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"status": "error", "error": str(e)}
    
    def send_text(self, text, peer_id=None, channel=None):
        """Send a text message."""
        data = {"text": text}
        if peer_id:
            data["peer_id"] = peer_id
        if channel:
            data["channel"] = channel
        
        response = requests.post(
            f"{self.base_url}/send/text",
            json=data,
            timeout=10
        )
        return response.json()
    
    def send_image(self, image_bytes, caption=None, peer_id=None, channel=None):
        """Send an image with optional caption."""
        files = {"image": ("vlm_image.jpg", image_bytes, "image/jpeg")}
        data = {}
        
        if caption:
            data["caption"] = caption
        if peer_id:
            data["peer_id"] = peer_id
        if channel:
            data["channel"] = channel
        
        response = requests.post(
            f"{self.base_url}/send/image",
            files=files,
            data=data,
            timeout=30
        )
        return response.json()
    
    def send_analysis(self, image_bytes, description, peer_id=None, channel=None):
        """Send image + VLM-generated dense captioning."""
        files = {"image": ("vlm_frame.jpg", image_bytes, "image/jpeg")}
        data = {"description": description}
        
        if peer_id:
            data["peer_id"] = peer_id
        if channel:
            data["channel"] = channel
        
        response = requests.post(
            f"{self.base_url}/send/analysis",
            files=files,
            data=data,
            timeout=30
        )
        return response.json()
    
    def send_text_analysis(self, description, peer_id=None, channel=None):
        """Send VLM analysis text without image."""
        data = {"description": description}
        
        if peer_id:
            data["peer_id"] = peer_id
        if channel:
            data["channel"] = channel
        
        response = requests.post(
            f"{self.base_url}/send/analysis",
            data=data,
            timeout=10
        )
        return response.json()
    
    def set_silence(self, enabled=True):
        """Pause or resume VLM message sending."""
        response = requests.post(
            f"{self.base_url}/silence",
            json={"enabled": enabled},
            timeout=5
        )
        return response.json()
    
    def update_settings(self, settings):
        """Update VLM API settings."""
        response = requests.post(
            f"{self.base_url}/settings",
            json=settings,
            timeout=5
        )
        return response.json()


# Example Usage
if __name__ == "__main__":
    # Initialize client
    client = BitchatVLMClient("http://127.0.0.1:8765")
    
    # Check connection
    status = client.check_status()
    print(f"API Enabled: {status.get('api_enabled')}")
    print(f"Mesh Peers: {status.get('peers_count')}")
    
    # Capture screenshot
    screenshot = ImageGrab.grab()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='JPEG', quality=85)
    image_bytes = img_byte_arr.getvalue()
    
    # Generate VLM description (your VLM model here)
    vlm_description = """
    Scene Analysis:
    - 3 people visible in the frame
    - Indoor environment, office setting
    - One person standing near whiteboard
    - Minified view shows presentation slides
    - Lighting: fluorescent, moderate brightness
    """
    
    # Send to Bitchat mesh
    result = client.send_analysis(
        image_bytes=image_bytes,
        description=vlm_description,
        channel="vision-analysis"
    )
    print(f"Result: {result}")
```

---

### cURL Examples

**Check Status:**
```bash
curl http://127.0.0.1:8765/status
```

**Send Text Message:**
```bash
curl -X POST http://127.0.0.1:8765/send/text \
  -H "Content-Type: application/json" \
  -d '{"text": "VLM Detection: Person entering frame", "channel": "security"}'
```

**Send Image with Caption:**
```bash
curl -X POST http://127.0.0.1:8765/send/image \
  -F "image=@/path/to/screenshot.jpg" \
  -F "caption=VLM captured this frame"
```

**Send Analysis (Image + Description):**
```bash
curl -X POST http://127.0.0.1:8765/send/analysis \
  -F "image=@/path/to/frame.jpg" \
  -F "description=Dense caption: A crowded street with multiple vehicles and pedestrians"
```

**Send Base64 Image:**
```bash
# Encode image to base64
IMAGE_BASE64=$(base64 -w 0 screenshot.jpg)

curl -X POST http://127.0.0.1:8765/send/image \
  -d "image_base64=$IMAGE_BASE64" \
  -d "caption=VLM Frame"
```

---

### JavaScript/Node.js Example

```javascript
const fs = require('fs');
const axios = require('axios');
const FormData = require('form-data');

class BitchatVLMClient {
  constructor(baseUrl = 'http://127.0.0.1:8765') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async checkStatus() {
    try {
      const response = await axios.get(`${this.baseUrl}/status`);
      return response.data;
    } catch (error) {
      return { status: 'error', error: error.message };
    }
  }

  async sendText(text, peerId = null, channel = null) {
    const data = { text };
    if (peerId) data.peer_id = peerId;
    if (channel) data.channel = channel;

    const response = await axios.post(`${this.baseUrl}/send/text`, data);
    return response.data;
  }

  async sendImage(imagePath, caption = null, peerId = null, channel = null) {
    const form = new FormData();
    form.append('image', fs.createReadStream(imagePath));
    if (caption) form.append('caption', caption);
    if (peerId) form.append('peer_id', peerId);
    if (channel) form.append('channel', channel);

    const response = await axios.post(`${this.baseUrl}/send/image`, form, {
      headers: form.getHeaders()
    });
    return response.data;
  }

  async sendAnalysis(imagePath, description, peerId = null, channel = null) {
    const form = new FormData();
    form.append('image', fs.createReadStream(imagePath));
    form.append('description', description);
    if (peerId) form.append('peer_id', peerId);
    if (channel) form.append('channel', channel);

    const response = await axios.post(`${this.baseUrl}/send/analysis`, form, {
      headers: form.getHeaders()
    });
    return response.data;
  }
}

// Usage
(async () => {
  const client = new BitchatVLMClient('http://127.0.0.1:8765');
  
  const status = await client.checkStatus();
  console.log('API Status:', status);
  
  const result = await client.sendAnalysis(
    './screenshot.jpg',
    'VLM Analysis: Code editor with Python file, debugging session active',
    null,
    'vision'
  );
  console.log('Result:', result);
})();
```

---

## Message Routing

Bitchat routes VLM messages using the following priority:

1. **Explicit Peer ID:** Direct private message to specific peer
2. **Explicit Channel:** Public message to specific channel
3. **Default Destination:** Configured in VLM Settings
4. **Public Broadcast:** If no destination specified

**Example:**
```python
# Private message to specific peer
client.send_analysis(image_bytes, description, peer_id="alice_public_key")

# Channel message (topic-based)
client.send_analysis(image_bytes, description, channel="vision-analysis")

# Use default destination from settings
client.send_analysis(image_bytes, description)

# Public broadcast (all peers)
client.send_text("VLM Alert: Motion detected")
```

---

## Rate Limiting

VLM API has built-in rate limiting to prevent spam:

**Default:** 5000ms (5 seconds) between messages  
**Configuration:** Settings → VLM API → Rate Limit (ms)

**Error Response:**
```json
{
  "status": "error",
  "error": "Rate limited - please wait"
}
```

**Best Practice:** Implement client-side throttling to match server limit.

---

## File Transfer Protocol

Images sent via VLM API use Bitchat's mesh file transfer protocol:

1. **Encryption:** Private images use Noise Protocol encryption
2. **Fragmentation:** Large files split into mesh-compatible chunks
3. **Multi-hop:** Routed through up to 7 mesh hops
4. **Retry Logic:** Automatic retry if peer temporarily unreachable
5. **Compression:** Optional compression for faster transfer

**Transfer Time:**
- Bluetooth LE: ~30-60 seconds for 1MB image
- WiFi Aware: ~5-10 seconds for 1MB image (device-dependent)

---

## Security Considerations

### Current Security Model

1. **Local Network Only:** API accessible only via local WiFi or ADB
2. **No Authentication:** Any application on network can send messages
3. **CORS:** Access-Control-Allow-Origin: `*` (all origins)
4. **Rate Limiting:** Prevents message flooding
5. **Silence Mode:** Emergency stop for all VLM messages

### Recommendations

**For Development:**
- Use ADB port forwarding (localhost only)
- Test with silence mode enabled
- Monitor logs: `adb logcat -s VlmApiService:I VlmMessageHandler:I`

**For Production:**
- Run on isolated WiFi network
- Enable silence mode when not in use
- Set conservative rate limits
- Monitor message queue size

**Future Enhancements:**
- Authentication token support
- IP whitelisting
- End-to-end encryption for API traffic
- Audit logging

---

## Architecture

```
┌─────────────────┐
│  VLM Machine    │
│  (Python/JS)    │
└────────┬────────┘
         │ HTTP POST
         ↓
┌─────────────────────────────────────┐
│  Bitchat Android App                │
│  ┌───────────────────────────────┐  │
│  │  VlmApiService (NanoHTTPD)    │  │ ← HTTP :8765
│  │  - /send/text                 │  │
│  │  - /send/image                │  │
│  │  - /send/analysis             │  │
│  └────────────┬──────────────────┘  │
│               ↓                     │
│  ┌───────────────────────────────┐  │
│  │  VlmMessageHandler            │  │
│  │  - Validates input            │  │
│  │  - Rate limiting              │  │
│  │  - Creates messages           │  │
│  └────────────┬──────────────────┘  │
│               ↓                     │
│  ┌───────────────────────────────┐  │
│  │  MeshService                   │  │
│  │  - BLE/WiFi Aware transports   │  │
│  │  - Noise encryption           │  │
│  │  - Multi-hop routing          │  │
│  └────────────┬──────────────────┘  │
└───────────────┼─────────────────────┘
                ↓
         ┌──────────────┐
         │  Mesh Peers   │
         │  (iOS/Android)│
         └──────────────┘
```

**Flow:**
1. VLM captures/processes visual content
2. VLM generates dense captioning/description
3. VLM sends HTTP POST to Bitchat API
4. Bitchat validates and queues message
5. MeshService encrypts and transmits over BLE/WiFi
6. Peer devices receive and decrypt message
7. Image appears in chat with VLM description

---

## Troubleshooting

### Connection Issues

**Problem:** Cannot connect to `http://127.0.0.1:8765`

**Solutions:**
```bash
# Check if ADB forward is active
adb forward --list

# Re-establish forwarding
adb forward --remove tcp:8765
adb forward tcp:8765 tcp:8765

# Verify Bitchat is running
adb shell ps | grep bitchat

# Check VLM API logs
adb logcat -s VlmApiService:I MeshForegroundService:I
```

---

**Problem:** WiFi IP shows `0.0.0.0` in status

**Solutions:**
- Ensure device connected to WiFi network
- Check WiFi_IP from Android Settings → WiFi
- Use `adb shell ip addr show wlan0` to get IP
- Try disconnecting/reconnecting WiFi

---

**Problem:** API responds with "VLM API is disabled"

**Solutions:**
- Open Bitchat → Settings → VLM API → Enable toggle
- Check status: `curl http://127.0.0.1:8765/status`
- Restart mesh service: Disable/Enable VLM toggle

---

### Image Transfer Issues

**Problem:** Image send fails with "Invalid image: empty or too large"

**Solutions:**
```python
# Check file size (max 10MB)
import os
file_size = os.path.getsize("image.jpg")
print(f"Size: {file_size / 1024 / 1024:.2f} MB")

# Compress if needed
from PIL import Image
img = Image.open("image.jpg")
img.save("compressed.jpg", "JPEG", quality=85, optimize=True)
```

---

**Problem:** Image takes too long to send

**Solutions:**
- Reduce image size before sending
- Use WiFi Aware if available (faster than BLE)
- Check mesh hop count: Settings → Peers → Distance
- Monitor transfer: `adb logcat -s FileTransfer:I`

---

### Message Routing Issues

**Problem:** Messages don't reach intended recipient

**Solutions:**
```python
# Check peer is online
status = client.check_status()
print(f"Peers: {status['peers_count']}")

# Use correct peer ID (public key fingerprint)
# Check in Bitchat: Peers → tap peer → Show ID

# Verify channel exists
# Check in Bitchat: Channels → join or create channel

# Use default destination
client.update_settings({
  "default_destination": {
    "type": "channel",
    "id": "vision"
  }
})
```

---

## Advanced Usage

### Streaming Video Frames

```python
import cv2
import time

client = BitchatVLMClient("http://127.0.0.1:8765")

# Open camera
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    # Process frame with VLM every 5 seconds
    if int(time.time()) % 5 == 0:
        # Encode frame to JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_bytes = buffer.tobytes()
        
        # Generate description (your VLM model)
        description = your_vlm_model.describe_frame(frame)
        
        # Send to Bitchat
        client.send_analysis(image_bytes, description, channel="video-feed")
    
    # Display frame
    cv2.imshow('VLM Stream', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

---

### Batch Processing

```python
import os
from pathlib import Path

client = BitchatVLMClient("http://127.0.0.1:8765")

# Process directory of images
image_dir = Path("./screenshots")

for image_path in sorted(image_dir.glob("*.jpg")):
    print(f"Processing: {image_path.name}")
    
    image_bytes = image_path.read_bytes()
    description = your_vlm_model.describe(image_bytes)
    
    # Respect rate limiting
    result = client.send_analysis(image_bytes, description, channel="batch")
    print(f"  Sent: {result['status']}")
    
    # Wait for rate limit
    time.sleep(5.5)  # Default 5000ms + buffer
```

---

### Integration with OpenAI GPT-4V

```python
import openai
import base64
from pathlib import Path

# Initialize clients
openai.api_key = "sk-..."
bitchat = BitchatVLMClient("http://127.0.0.1:8765")

def analyze_and_send(image_path):
    # Read image
    image_data = base64.b64encode(Path(image_path).read_bytes()).decode()
    
    # GPT-4V analysis
    response = openai.ChatCompletion.create(
        model="gpt-4-vision-preview",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Provide a dense caption describing this image in detail."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
            ]
        }],
        max_tokens=500
    )
    
    description = response.choices[0].message.content
    
    # Send to Bitchat
    image_bytes = Path(image_path).read_bytes()
    result = bitchat.send_analysis(
        image_bytes,
        f"GPT-4V Analysis: {description}",
        channel="gpt-vision"
    )
    
    return result

# Usage
analyze_and_send("./screenshot.jpg")
```

---

## API Reference

### VlmApiService

**Implementation:** `app/src/main/java/com/bitchat/android/vlm/VlmApiService.kt`

**Server:** NanoHTTPD embedded HTTP server  
**Binding:** `0.0.0.0` (all interfaces - localhost, WiFi, ADB)  
**Default Port:** 8765  
**Lifecycle:** Started/stopped by MeshForegroundService

**Key Methods:**
- `start()` - Start HTTP server
- `stop()` - Stop HTTP server
- `serve(IHTTPSession)` - Route incoming requests

---

### VlmMessageHandler

**Implementation:** `app/src/main/java/com/bitchat/android/vlm/VlmMessageHandler.kt`

**Validation:**
- Max text length: 16,000 characters
- Max image size: 10MB
- Rate limiting enforcement

**Message Types:**
- Text messages: routed via MeshService
- Image messages: use BitchatFilePacket protocol
- Private messages: Noise Protocol encryption
- Channel messages: AES-256-GCM encryption

---

### VlmSettingsManager

**Implementation:** `app/src/main/java/com/bitchat/android/vlm/VlmSettingsManager.kt`

**Stored Settings:**
- `enabled: Boolean` - API on/off
- `http_port: Int` - Server port (1024-65535)
- `silence_enabled: Boolean` - Emergency mute
- `rate_limit_ms: Long` - Minimum ms between messages
- `default_destination: VlmDestination?` - Default routing

---

## Contributing

To extend the VLM API:

1. Add new endpoints in `VlmApiService.kt`
2. Implement handlers in `VlmMessageHandler.kt`
3. Update settings in `VlmSettingsManager.kt`
4. Add tests in `app/src/test/kotlin/com/bitchat/android/vlm/`
5. Update this documentation

---

## License

Bitchat VLM API is part of the Bitchat project and released into the public domain. See [LICENSE.md](../LICENSE.md) for details.

---

## Support

- **Issues:** [GitHub Issues](https://github.com/permissionlesstech/bitchat-android/issues)
- **Logs:** `adb logcat -s VlmApiService:I VlmMessageHandler:I MeshForegroundService:I`
- **Documentation:** This file at `docs/VLM_API.md`

---

**Last Updated:** 2025-11-01  
**Version:** 1.0.0  
**Compatible with:** Bitchat Android v1.0+
