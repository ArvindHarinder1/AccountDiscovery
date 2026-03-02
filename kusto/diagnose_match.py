"""Diagnose: trace who matched to whom for Victor Walker and Xavier Allen."""
import subprocess, requests

import os
CLUSTER = os.environ.get("KUSTO_CLUSTER_URI", "")
DB = os.environ.get("KUSTO_DATABASE", "accounts")
TENANT = os.environ.get("KUSTO_TENANT_ID", "")

def get_token():
    r = subprocess.run(
        [r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
         "account", "get-access-token", "--resource", "https://kusto.kusto.windows.net",
         "--tenant", TENANT, "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=30, shell=True)
    return r.stdout.strip()

def query(kql, token):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(f"{CLUSTER}/v1/rest/query", headers=h, json={"db": DB, "csl": kql})
    r.raise_for_status()
    t = r.json()["Tables"][0]
    cols = [c["ColumnName"] for c in t["Columns"]]
    return [dict(zip(cols, row)) for row in t["Rows"]]

token = get_token()

# Q1: Who matched to Victor Walker (Entra)?
print("=== Who claimed Victor Walker (Entra)? ===")
rows = query("MatchResults | where EntraDisplayName == 'Victor Walker' | project SalesforceDisplayName, SalesforceEmail, MatchCategory, CompositeScore", token)
for r in rows:
    cat = r["MatchCategory"]
    sc = r["CompositeScore"]
    print(f"  {r['SalesforceDisplayName']} ({r['SalesforceEmail']}) -> Victor Walker  [{cat}, {sc}]")
if not rows:
    print("  Nobody matched to Victor Walker (Entra)!")

# Q2: Who claimed Xavier Allen (Entra)?
print("\n=== Who claimed Xavier Allen (Entra)? ===")
rows = query("MatchResults | where EntraDisplayName == 'Xavier Allen' | project SalesforceDisplayName, SalesforceEmail, MatchCategory, CompositeScore", token)
for r in rows:
    cat = r["MatchCategory"]
    sc = r["CompositeScore"]
    print(f"  {r['SalesforceDisplayName']} ({r['SalesforceEmail']}) -> Xavier Allen  [{cat}, {sc}]")

# Q3: Where did Xavier Allen (SF) end up?
print("\n=== Xavier Allen (SF) matched to? ===")
rows = query("MatchResults | where SalesforceDisplayName == 'Xavier Allen' | project SalesforceEmail, EntraDisplayName, EntraUPN, MatchCategory, CompositeScore", token)
for r in rows:
    cat = r["MatchCategory"]
    sc = r["CompositeScore"]
    print(f"  Xavier Allen ({r['SalesforceEmail']}) -> {r['EntraDisplayName']} ({r['EntraUPN']})  [{cat}, {sc}]")

# Q4: Where did Victor Walker (SF) end up?
print("\n=== Victor Walker (SF) matched to? ===")
rows = query("MatchResults | where SalesforceDisplayName == 'Victor Walker' | project SalesforceEmail, EntraDisplayName, EntraUPN, MatchCategory, CompositeScore", token)
for r in rows:
    cat = r["MatchCategory"]
    sc = r["CompositeScore"]
    print(f"  Victor Walker ({r['SalesforceEmail']}) -> {r['EntraDisplayName']} ({r['EntraUPN']})  [{cat}, {sc}]")

# Q5: All non-Exact, non-None matches
print("\n=== All fuzzy matches (sorted by score desc) ===")
rows = query("MatchResults | where MatchCategory !in ('Exact','None') | sort by CompositeScore desc | project SalesforceDisplayName, EntraDisplayName, MatchCategory, CompositeScore", token)
for r in rows:
    sf = r["SalesforceDisplayName"]
    en = r["EntraDisplayName"]
    cat = r["MatchCategory"]
    sc = r["CompositeScore"]
    print(f"  {sf:25s} -> {en:25s}  [{cat:6s}, {sc}]")
