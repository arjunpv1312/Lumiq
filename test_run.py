import requests
import uuid
import os
import time
import shutil

# Make sure we have a sample file
shutil.copy("static/sample_data.csv", "uploads/test_file.csv")

session = requests.Session()

print("Hitting /sample...")
res = session.get("http://127.0.0.1:5001/sample", allow_redirects=True)
print("Status:", res.status_code)

print("Hitting /start_process...")
t0 = time.time()
res = session.get("http://127.0.0.1:5001/start_process")
print(f"Status: {res.status_code} in {time.time()-t0:.2f}s")
print("Response:", res.text)
