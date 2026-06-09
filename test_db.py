import requests
import json
import sqlite3

# Query the latest row from job_results
conn = sqlite3.connect('data/lumiq.db')
c = conn.cursor()
c.execute("SELECT * FROM job_results ORDER BY id DESC LIMIT 1")
row = c.fetchone()
col_names = [desc[0] for desc in c.description]
res = dict(zip(col_names, row))

print(json.dumps(json.loads(res['data']), indent=2))
print("Status:", res['status'])
print("Error:", res['error'])
