import requests

URL = "https://rss-bridge.org/bridge01/?action=display&bridge=InstagramBridge&context=Username&u=official_me_i_&media_type=all&direct_links=on&format=Json"

r = requests.get(URL, timeout=30)
r.raise_for_status()
print(r.text[:2000])
