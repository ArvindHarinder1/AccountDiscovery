"""
Test ingestion approach - datatable method
"""
import json
import subprocess
import requests

import os
TENANT = os.environ.get("KUSTO_TENANT_ID", "")
cluster = os.environ.get("KUSTO_CLUSTER_URI", "")
db = os.environ.get("KUSTO_DATABASE", "accounts")

token = subprocess.run(
    [r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
     "account", "get-access-token",
     "--resource", "https://kusto.kusto.windows.net",
     "--tenant", TENANT,
     "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True, shell=True,
).stdout.strip()
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json; charset=utf-8",
}

def mgmt(cmd):
    r = requests.post(f"{cluster}/v1/rest/mgmt", headers=headers, json={"db": db, "csl": cmd})
    if r.status_code != 200:
        print(f"  ERROR {r.status_code}: {r.text[:300]}")
    return r

def query(q):
    r = requests.post(f"{cluster}/v1/rest/query", headers=headers, json={"db": db, "csl": q})
    r.raise_for_status()
    data = r.json()
    cols = [c["ColumnName"] for c in data["Tables"][0]["Columns"]]
    return [dict(zip(cols, row)) for row in data["Tables"][0]["Rows"]]

# Clear
mgmt(".clear table SalesforceAccounts data")

# Test with datatable
cmd = (
    '.set-or-append SalesforceAccounts <| '
    'datatable(AccountId:string, Email:string, Username:string, DisplayName:string, '
    'FirstName:string, LastName:string, Phone:string, Department:string, Title:string, '
    'EmployeeId:string, IsActive:bool, LastLoginDate:datetime, CreatedDate:datetime, '
    'SourceApplication:string) '
    '["TEST-001", "test@test.com", "test_user", "Test User", "Test", "User", '
    '"555-1234", "Eng", "Dev", "E001", true, datetime(2024-01-01), datetime(2024-01-01), "Salesforce"]'
)
print("Ingesting test row...")
r = mgmt(cmd)
print(f"  Status: {r.status_code}")

# Query back
print("Querying back...")
rows = query("SalesforceAccounts | project AccountId, Email, DisplayName")
for row in rows:
    print(f"  {row}")
