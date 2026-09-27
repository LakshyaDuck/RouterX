import urllib.request, json, os

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
endpoints = [
    "/",
    "/api/health",
    "/api/vehicles",
    "/api/deliveries",
    "/api/routes",
    "/api/nodes",
    "/api/roads",
    "/api/events",
]

for ep in endpoints:
    try:
        r = urllib.request.urlopen(BASE + ep)
        data = json.loads(r.read())
        if isinstance(data, list):
            print(f"OK  {ep}  -> [{len(data)} items]")
        elif isinstance(data, dict):
            keys = list(data.keys())[:4]
            print(f"OK  {ep}  -> {{{', '.join(str(k) for k in keys)}...}}")
    except Exception as e:
        print(f"ERR {ep}  -> {e}")
