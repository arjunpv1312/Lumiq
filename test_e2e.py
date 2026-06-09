"""
End-to-end test: simulates the browser flow
  1. Hit /sample to load sample data
  2. Hit /start_process to kick off the pipeline (thread in dev mode)
  3. Poll /progress_json/<job_id> until status == "done"
  4. Hit /results to verify the results page loads
"""
import requests
import time
import json
import sys

BASE = "http://127.0.0.1:5000"
session = requests.Session()

# Step 1: Load sample data
print("=" * 60)
print("STEP 1: Loading sample data via /sample...")
res = session.get(f"{BASE}/sample", allow_redirects=True)
print(f"  Status: {res.status_code}")
if res.status_code != 200:
    print("  FAILED to load sample page")
    sys.exit(1)

# Step 2: Start the pipeline
print("\nSTEP 2: Starting pipeline via /start_process...")
res = session.get(f"{BASE}/start_process")
print(f"  Status: {res.status_code}")
data = res.json()
print(f"  Response: {json.dumps(data, indent=2)}")

if data.get("error"):
    print(f"  ERROR: {data['error']}")
    sys.exit(1)

task_id = data.get("task_id", "unknown")
print(f"  Task ID: {task_id}")
job_id = session.cookies.get("session", "") # Not quite, but we don't need it.

# Step 3: Poll for progress
print("\nSTEP 3: Polling progress...")
t0 = time.time()
last_status = ""
while True:
    elapsed = time.time() - t0
    if elapsed > 300:  # 5 minute timeout
        print("\n  TIMEOUT after 5 minutes!")
        sys.exit(1)

    # Since we can't easily parse job_id from the signed Flask session cookie in a script,
    # we'll just check if /results successfully loads. But we must do it slowly to avoid 429.
    time.sleep(3)
    
    res = session.get(f"{BASE}/results", allow_redirects=False)
    
    if res.status_code == 200:
        print(f"\n  DONE in {elapsed:.1f}s! Results page returned 200.")
        break
    elif res.status_code == 302:
        status_char = "." * (int(elapsed) % 4 + 1)
        print(f"  [{elapsed:5.1f}s] Processing{status_char}", end="\r")
    elif res.status_code == 429:
        print(f"  [{elapsed:5.1f}s] Rate limited! Backing off...", end="\r")
        time.sleep(5)
    else:
        print(f"  Unexpected status: {res.status_code}")

# Step 4: Verify results
print("\nSTEP 4: Verifying results page...")
res = session.get(f"{BASE}/results")
print(f"  Status: {res.status_code}")
print(f"  Content length: {len(res.text)} bytes")

# Check for key elements in the results page
checks = {
    "Dashboard charts": "chart" in res.text.lower() or "dashboard" in res.text.lower(),
    "Download links":   "download" in res.text.lower(),
    "No error message": "error" not in res.text.lower()[:500],
}

print("\n  Checks:")
all_pass = True
for name, passed in checks.items():
    icon = "[OK]" if passed else "[FAIL]"
    print(f"    {icon} {name}")
    if not passed:
        all_pass = False

print("\n" + "=" * 60)
if all_pass:
    print("ALL TESTS PASSED! The pipeline works end-to-end.")
else:
    print("SOME CHECKS FAILED — see above.")
print("=" * 60)
