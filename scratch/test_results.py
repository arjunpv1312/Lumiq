import requests
import sys

BASE = "http://127.0.0.1:5000"
print("Attempting to GET /results...")
try:
    res = requests.get(f"{BASE}/results", timeout=5)
    print(f"Status Code: {res.status_code}")
    print(f"Content Length: {len(res.text)}")
    print(f"Preview (first 200 chars):\n{res.text[:200]}")
except Exception as e:
    print(f"Request failed: {e}")
