# Bitchat Wi-Fi & VLM API Bridge Utilities

Collection of diagnostic, network discovery, and testing tools for connecting the AI Surveillance system to Android devices running BitChat.

## Quick Reference

| Tool | Purpose |
|---|---|
| `find_bitchat.py` | Auto-scans all subnets to discover BitChat nodes on port 8765 |
| `diagnose_connection.py` | Tests ping and port reachability on Android Wi-Fi IP |
| `enable_bitchat_api.py` | Guide & checklist to enable the VLM HTTP API in Android settings |
| `setup_wifi_access.py` | Helper script to configure Windows firewall / hotspot routing |
| `test_bitchat_fix.py` | Sends a synthetic test alert to verify the HTTP endpoint |
| `test_image_sending.py` | Encodes and sends a test image frame to the BitChat timeline |
| `monitor_bitchat_api.py` | Continuous polling / heartbeat monitor for the BitChat API |
| `monitor_wifi_access.py` | Continuous Wi-Fi interface & IP monitor |
| `scan_ports.py` | Quick port scanner for targeted IPs |
| `now_connect.py` | Interactive connection assistant |
