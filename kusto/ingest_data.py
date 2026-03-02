"""
Account Discovery: Ingest CSV data into Kusto tables.
Uses Kusto REST API with Azure CLI token. No SDK dependencies beyond requests.
"""

import csv
import json
import os
import subprocess
import sys

import requests

CLUSTER = os.environ.get("KUSTO_CLUSTER_URI", "")
DATABASE = os.environ.get("KUSTO_DATABASE", "accounts")
TENANT = os.environ.get("KUSTO_TENANT_ID", "")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

AZ_CMD = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"


def get_token() -> str:
    print("Acquiring token from Azure CLI...")
    result = subprocess.run(
        [AZ_CMD, "account", "get-access-token",
         "--resource", "https://kusto.kusto.windows.net",
         "--tenant", TENANT,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=30, shell=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        sys.exit(1)
    token = result.stdout.strip()
    print(f"  Token acquired (len={len(token)})")
    return token


def kusto_mgmt(token: str, command: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = json.dumps({"db": DATABASE, "csl": command})
    resp = requests.post(f"{CLUSTER}/v1/rest/mgmt", headers=headers, data=body.encode("utf-8"))
    resp.raise_for_status()
    return resp.json()


def kusto_query(token: str, query: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = json.dumps({"db": DATABASE, "csl": query})
    resp = requests.post(f"{CLUSTER}/v1/rest/query", headers=headers, data=body.encode("utf-8"))
    resp.raise_for_status()
    data = resp.json()
    return data["Tables"][0]["Rows"]


def read_csv(filepath: str) -> list[list[str]]:
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            rows.append(row)
    return rows


def _escape_kql(val: str) -> str:
    """Escape a string value for KQL datatable literal."""
    return val.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def _build_sf_datatable_rows(rows: list[list[str]]) -> str:
    """Build KQL datatable row literals for SalesforceAccounts."""
    kql_rows = []
    for cols in rows:
        if len(cols) < 14:
            continue
        aid, email, uname, dname, fname, lname = [_escape_kql(c) for c in cols[:6]]
        phone, dept, title, empid = [_escape_kql(c) for c in cols[6:10]]
        is_active = "true" if cols[10].strip().lower() == "true" else "false"
        last_login = f'datetime("{cols[11]}")' if cols[11] else "datetime(null)"
        created = f'datetime("{cols[12]}")' if cols[12] else "datetime(null)"
        source = _escape_kql(cols[13])
        kql_rows.append(
            f'  "{aid}", "{email}", "{uname}", "{dname}", "{fname}", "{lname}", '
            f'"{phone}", "{dept}", "{title}", "{empid}", {is_active}, '
            f'{last_login}, {created}, "{source}"'
        )
    return ",\n".join(kql_rows)


def _build_entra_datatable_rows(rows: list[list[str]]) -> str:
    """Build KQL datatable row literals for EntraUsers."""
    kql_rows = []
    for cols in rows:
        if len(cols) < 14:
            continue
        oid, upn, mail, dname, gname, sname = [_escape_kql(c) for c in cols[:6]]
        phone, mobile, dept, jtitle, empid = [_escape_kql(c) for c in cols[6:11]]
        enabled = "true" if cols[11].strip().lower() == "true" else "false"
        created = f'datetime("{cols[12]}")' if cols[12] else "datetime(null)"
        utype = _escape_kql(cols[13])
        kql_rows.append(
            f'  "{oid}", "{upn}", "{mail}", "{dname}", "{gname}", "{sname}", '
            f'"{phone}", "{mobile}", "{dept}", "{jtitle}", "{empid}", {enabled}, '
            f'{created}, "{utype}"'
        )
    return ",\n".join(kql_rows)


SF_SCHEMA = (
    "AccountId:string, Email:string, Username:string, DisplayName:string, "
    "FirstName:string, LastName:string, Phone:string, Department:string, "
    "Title:string, EmployeeId:string, IsActive:bool, LastLoginDate:datetime, "
    "CreatedDate:datetime, SourceApplication:string"
)

ENTRA_SCHEMA = (
    "ObjectId:string, UserPrincipalName:string, Mail:string, DisplayName:string, "
    "GivenName:string, Surname:string, Phone:string, MobilePhone:string, "
    "Department:string, JobTitle:string, EmployeeId:string, AccountEnabled:bool, "
    "CreatedDateTime:datetime, UserType:string"
)


def ingest_table(token: str, table_name: str, csv_file: str, schema: str, build_rows_fn):
    filepath = os.path.join(DATA_DIR, csv_file)
    rows = read_csv(filepath)
    if not rows:
        print(f"  No rows found in {csv_file}")
        return

    # Ingest in batches of 10 (datatable has size limits)
    batch_size = 10
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        row_literals = build_rows_fn(batch)
        cmd = f".set-or-append {table_name} <| datatable({schema}) [\n{row_literals}\n]"
        kusto_mgmt(token, cmd)
        total += len(batch)

    print(f"  {table_name}: {total} rows ingested")


def main():
    print("=" * 55)
    print("Account Discovery — Data Ingestion")
    print("=" * 55)
    print(f"  Cluster : {CLUSTER}")
    print(f"  Database: {DATABASE}")
    print()

    token = get_token()
    print()

    # Clear existing data
    print("Clearing existing data...")
    kusto_mgmt(token, ".clear table SalesforceAccounts data")
    kusto_mgmt(token, ".clear table EntraUsers data")
    kusto_mgmt(token, ".clear table MatchResults data")
    print("  Done.")
    print()

    # Ingest
    print("Ingesting data...")
    ingest_table(token, "SalesforceAccounts", "salesforce_accounts.csv", SF_SCHEMA, _build_sf_datatable_rows)
    ingest_table(token, "EntraUsers", "entra_users.csv", ENTRA_SCHEMA, _build_entra_datatable_rows)
    print()

    # Verify
    print("Verifying row counts...")
    sf_count = kusto_query(token, "SalesforceAccounts | count")[0][0]
    en_count = kusto_query(token, "EntraUsers | count")[0][0]
    print(f"  SalesforceAccounts: {sf_count} rows")
    print(f"  EntraUsers: {en_count} rows")

    # Quick sample
    print()
    print("Sample data (first 2 SalesforceAccounts):")
    sample = kusto_query(token, "SalesforceAccounts | take 2 | project AccountId, Email, DisplayName")
    for row in sample:
        print(f"  {row[0]} | {row[1]} | {row[2]}")

    print()
    print("Done!")


if __name__ == "__main__":
    main()
