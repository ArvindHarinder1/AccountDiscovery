"""Quick verification of Kusto data after pipeline run."""
import os
from src.data_loader import _get_cli_token, _kusto_query

token = _get_cli_token(os.environ.get("KUSTO_TENANT_ID", ""))
cluster = os.environ.get("KUSTO_CLUSTER_URI", "")
db = os.environ.get("KUSTO_DATABASE", "accounts")

print("=== Row Counts ===")
for tbl in ["SalesforceAccounts", "EntraUsers", "MatchResults"]:
    rows = _kusto_query(cluster, db, f"{tbl} | count", token)
    print(f"  {tbl}: {rows[0]['Count']} rows")

print("\n=== Match Results by Category ===")
rows = _kusto_query(cluster, db,
    "MatchResults | summarize Count=count() by MatchCategory | order by Count desc", token)
for r in rows:
    print(f"  {r['MatchCategory']}: {r['Count']}")

print("\n=== Top 5 Matches ===")
rows = _kusto_query(cluster, db,
    'MatchResults | where MatchCategory != "None" | top 5 by CompositeScore '
    '| project SalesforceDisplayName, EntraDisplayName, MatchCategory, CompositeScore', token)
for r in rows:
    print(f"  {r['SalesforceDisplayName']} -> {r['EntraDisplayName']}  [{r['MatchCategory']}] score={r['CompositeScore']}")

print("\n=== AI-Flagged Accounts ===")
rows = _kusto_query(cluster, db,
    'MatchResults | where AIFlags != "{}" | project SalesforceDisplayName, SalesforceEmail, AIFlags', token)
for r in rows:
    print(f"  {r['SalesforceDisplayName']} ({r['SalesforceEmail']}): {r['AIFlags']}")

print("\nDone!")
