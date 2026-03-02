"""
Kusto Table Provisioning Script
Creates the Account Discovery tables using Azure CLI token auth.
No azure-identity dependency needed — uses 'az' CLI for token acquisition.
"""

import json
import subprocess
import sys

from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError

# ── Configuration (set via environment variables) ──
CLUSTER_URI = os.environ.get("KUSTO_CLUSTER_URI", "")
DATABASE = os.environ.get("KUSTO_DATABASE", "accounts")
TENANT_ID = os.environ.get("KUSTO_TENANT_ID", "")
KUSTO_RESOURCE = "https://kusto.kusto.windows.net"


def get_cli_token() -> str:
    """Get an access token from Azure CLI for the Kusto resource."""
    print("  Acquiring token from Azure CLI...")
    try:
        result = subprocess.run(
            [
                "az", "account", "get-access-token",
                "--resource", KUSTO_RESOURCE,
                "--tenant", TENANT_ID,
                "--query", "accessToken",
                "-o", "tsv",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"  ERROR: az CLI failed: {result.stderr.strip()}")
            sys.exit(1)
        token = result.stdout.strip()
        print(f"  Token acquired (length={len(token)})")
        return token
    except FileNotFoundError:
        print("  ERROR: 'az' CLI not found. Please install Azure CLI.")
        sys.exit(1)


def create_kusto_client() -> KustoClient:
    """Build a KustoClient using an Azure CLI access token."""
    token = get_cli_token()
    kcsb = KustoConnectionStringBuilder.with_aad_user_token_authentication(
        connection_string=CLUSTER_URI,
        user_token=token,
    )
    return KustoClient(kcsb)


# ── Table Definitions ──
TABLE_COMMANDS = [
    # SalesforceAccounts
    """
    .create-merge table SalesforceAccounts (
        AccountId: string,
        Email: string,
        Username: string,
        DisplayName: string,
        FirstName: string,
        LastName: string,
        Phone: string,
        Department: string,
        Title: string,
        EmployeeId: string,
        IsActive: bool,
        LastLoginDate: datetime,
        CreatedDate: datetime,
        SourceApplication: string
    )
    """,
    # EntraUsers
    """
    .create-merge table EntraUsers (
        ObjectId: string,
        UserPrincipalName: string,
        Mail: string,
        DisplayName: string,
        GivenName: string,
        Surname: string,
        Phone: string,
        MobilePhone: string,
        Department: string,
        JobTitle: string,
        EmployeeId: string,
        AccountEnabled: bool,
        CreatedDateTime: datetime,
        UserType: string
    )
    """,
    # MatchResults
    """
    .create-merge table MatchResults (
        SalesforceAccountId: string,
        SalesforceDisplayName: string,
        SalesforceEmail: string,
        EntraObjectId: string,
        EntraDisplayName: string,
        EntraUPN: string,
        MatchCategory: string,
        CompositeScore: real,
        EmailMatchScore: real,
        NameMatchScore: real,
        PhoneMatchScore: real,
        DepartmentMatchScore: real,
        TitleMatchScore: real,
        EmployeeIdMatch: bool,
        AIFlags: string,
        AIReasoningSummary: string,
        MatchTimestamp: datetime
    )
    """,
]


def main():
    print("=" * 60)
    print("Account Discovery — Kusto Table Provisioning")
    print("=" * 60)
    print(f"  Cluster : {CLUSTER_URI}")
    print(f"  Database: {DATABASE}")
    print()

    client = create_kusto_client()

    # ── Create tables ──
    for i, cmd in enumerate(TABLE_COMMANDS, 1):
        table_name = cmd.strip().split("table")[1].split("(")[0].strip()
        print(f"[{i}/3] Creating table '{table_name}'...")
        try:
            response = client.execute_mgmt(DATABASE, cmd.strip())
            print(f"       ✓ '{table_name}' created/verified.")
        except KustoServiceError as e:
            print(f"       ✗ Error: {e}")

    # ── Verify tables ──
    print()
    print("Verifying tables...")
    try:
        result = client.execute_mgmt(DATABASE, ".show tables")
        tables = []
        for row in result.primary_results[0]:
            tables.append(row["TableName"])
        print(f"  Tables in '{DATABASE}': {', '.join(tables)}")
        
        expected = {"SalesforceAccounts", "EntraUsers", "MatchResults"}
        found = expected.intersection(set(tables))
        missing = expected - found
        if missing:
            print(f"  ⚠ Missing tables: {', '.join(missing)}")
        else:
            print(f"  ✓ All 3 Account Discovery tables present!")
    except KustoServiceError as e:
        print(f"  Error verifying: {e}")

    # ── Show schema for each table ──
    print()
    for tbl in ["SalesforceAccounts", "EntraUsers", "MatchResults"]:
        try:
            result = client.execute_mgmt(DATABASE, f".show table {tbl} schema as json")
            schema_json = json.loads(list(result.primary_results[0])[0]["Schema"])
            cols = schema_json.get("OrderedColumns", [])
            print(f"  {tbl}: {len(cols)} columns")
        except Exception:
            pass

    print()
    print("Done! Tables are ready for data ingestion.")


if __name__ == "__main__":
    main()
