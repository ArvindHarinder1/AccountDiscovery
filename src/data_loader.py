"""
Account Discovery Prototype — Data Loader
Abstracts data access: loads from local CSV, Azure Data Explorer (Kusto),
or Microsoft Graph API (correlation reports).
Kusto/Graph access uses REST API + Azure CLI token (no azure-identity SDK needed).
"""

import csv
import json
import os
import subprocess
from typing import Optional

import requests

from src.models import SalesforceAccount, EntraUser, MatchResult
from src.config import get_settings


def _parse_bool(val) -> bool:
    return str(val).lower() in ("true", "1", "yes")


# ── Azure CLI helpers ──

_AZ_PATHS = ["az", r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"]


def _find_az_cmd() -> str:
    """Find the az CLI executable."""
    for az_cmd in _AZ_PATHS:
        try:
            result = subprocess.run(
                [az_cmd, "version"],
                capture_output=True, text=True, timeout=10,
                shell=(az_cmd.endswith(".cmd")),
            )
            if result.returncode == 0:
                return az_cmd
        except FileNotFoundError:
            continue
    raise RuntimeError("Azure CLI 'az' not found. Ensure it's installed and on PATH.")


def _set_az_account(subscription_id: str) -> None:
    """Switch the active Azure CLI subscription/account context."""
    az_cmd = _find_az_cmd()
    result = subprocess.run(
        [az_cmd, "account", "set", "--subscription", subscription_id],
        capture_output=True, text=True, timeout=15,
        shell=(az_cmd.endswith(".cmd")),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to set az account to {subscription_id}: {result.stderr.strip()}"
        )


# ── Kusto REST helpers ──

def _get_cli_token(tenant_id: str) -> str:
    """Get an access token for Kusto from Azure CLI."""
    settings = get_settings()
    _set_az_account(settings.kusto_subscription_id)
    az_cmd = _find_az_cmd()
    result = subprocess.run(
        [az_cmd, "account", "get-access-token",
         "--resource", "https://kusto.kusto.windows.net",
         "--tenant", tenant_id,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=30,
        shell=(az_cmd.endswith(".cmd")),
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise RuntimeError(
        f"Failed to get Kusto token: {result.stderr.strip()}"
    )


def _kusto_query(cluster_uri: str, database: str, query: str, token: str) -> list[dict]:
    """Execute a KQL query via REST API and return rows as list of dicts."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"db": database, "csl": query}
    resp = requests.post(f"{cluster_uri}/v1/rest/query", headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()

    # Parse response: Tables[0] has Columns + Rows
    table = data["Tables"][0]
    col_names = [c["ColumnName"] for c in table["Columns"]]
    rows = []
    for row_data in table["Rows"]:
        rows.append(dict(zip(col_names, row_data)))
    return rows


def _kusto_mgmt(cluster_uri: str, database: str, command: str, token: str):
    """Execute a Kusto management command via REST API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"db": database, "csl": command}
    resp = requests.post(f"{cluster_uri}/v1/rest/mgmt", headers=headers, json=body)
    resp.raise_for_status()
    return resp.json()


# ── Local CSV loaders ──

def load_salesforce_accounts_local(filepath: str) -> list[SalesforceAccount]:
    """Load Salesforce accounts from a local CSV file."""
    accounts = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            accounts.append(SalesforceAccount(
                account_id=row["AccountId"],
                email=row["Email"],
                username=row["Username"],
                display_name=row["DisplayName"],
                first_name=row["FirstName"],
                last_name=row["LastName"],
                phone=row["Phone"],
                department=row["Department"],
                title=row["Title"],
                employee_id=row["EmployeeId"],
                is_active=_parse_bool(row["IsActive"]),
                source_application=row.get("SourceApplication", "Salesforce"),
            ))
    return accounts


def load_entra_users_local(filepath: str) -> list[EntraUser]:
    """Load Entra users from a local CSV file."""
    users = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(EntraUser(
                object_id=row["ObjectId"],
                user_principal_name=row["UserPrincipalName"],
                mail=row["Mail"],
                display_name=row["DisplayName"],
                given_name=row["GivenName"],
                surname=row["Surname"],
                phone=row["Phone"],
                mobile_phone=row["MobilePhone"],
                department=row["Department"],
                job_title=row["JobTitle"],
                employee_id=row["EmployeeId"],
                account_enabled=_parse_bool(row["AccountEnabled"]),
                user_type=row.get("UserType", "Member"),
            ))
    return users


# ── Kusto loaders (REST API) ──

def _get_kusto_connection():
    """Return (cluster_uri, database, token) for Kusto REST calls."""
    settings = get_settings()
    tenant_id = settings.kusto_tenant_id
    token = _get_cli_token(tenant_id)
    return settings.kusto_cluster_uri, settings.kusto_database, token


def load_salesforce_accounts_kusto() -> list[SalesforceAccount]:
    """Load Salesforce accounts from Azure Data Explorer via REST API."""
    cluster, db, token = _get_kusto_connection()
    print("  Querying SalesforceAccounts from Kusto...")
    rows = _kusto_query(cluster, db, "SalesforceAccounts | take 50000", token)

    accounts = []
    for r in rows:
        accounts.append(SalesforceAccount(
            account_id=r["AccountId"],
            email=r["Email"] or "",
            username=r["Username"] or "",
            display_name=r["DisplayName"] or "",
            first_name=r["FirstName"] or "",
            last_name=r["LastName"] or "",
            phone=r["Phone"] or "",
            department=r["Department"] or "",
            title=r["Title"] or "",
            employee_id=r["EmployeeId"] or "",
            is_active=_parse_bool(r["IsActive"]),
            source_application=r["SourceApplication"] or "Salesforce",
        ))
    return accounts


def load_entra_users_kusto() -> list[EntraUser]:
    """Load Entra users from Azure Data Explorer via REST API."""
    cluster, db, token = _get_kusto_connection()
    print("  Querying EntraUsers from Kusto...")
    rows = _kusto_query(cluster, db, "EntraUsers | take 50000", token)

    users = []
    for r in rows:
        users.append(EntraUser(
            object_id=r["ObjectId"],
            user_principal_name=r["UserPrincipalName"] or "",
            mail=r["Mail"] or "",
            display_name=r["DisplayName"] or "",
            given_name=r["GivenName"] or "",
            surname=r["Surname"] or "",
            phone=r["Phone"] or "",
            mobile_phone=r["MobilePhone"] or "",
            department=r["Department"] or "",
            job_title=r["JobTitle"] or "",
            employee_id=r["EmployeeId"] or "",
            account_enabled=_parse_bool(r["AccountEnabled"]),
            user_type=r["UserType"] or "Member",
        ))
    return users


# ── Microsoft Graph API loaders (correlation reports) ──

GRAPH_BASE = "https://graph.microsoft.com/beta"


def _get_graph_token(tenant_id: str) -> str:
    """Get an access token for Microsoft Graph from Azure CLI."""
    settings = get_settings()
    _set_az_account(settings.graph_subscription_id)
    az_cmd = _find_az_cmd()
    result = subprocess.run(
        [az_cmd, "account", "get-access-token",
         "--resource", "https://graph.microsoft.com",
         "--tenant", tenant_id,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=30,
        shell=(az_cmd.endswith(".cmd")),
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise RuntimeError(
        f"Failed to get Graph token: {result.stderr.strip()}\n"
        f"Try: az login --tenant {tenant_id} --scope https://graph.microsoft.com/.default"
    )


def _graph_get(url: str, token: str) -> dict:
    """HTTP GET against Microsoft Graph. Returns JSON response."""
    headers = {"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"}
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _graph_get_all(url: str, token: str, max_items: int = 0) -> list[dict]:
    """GET with automatic @odata.nextLink pagination. Returns all items.
    If max_items > 0, stops after collecting that many items.
    """
    items: list[dict] = []
    while url:
        data = _graph_get(url, token)
        items.extend(data.get("value", []))
        if max_items > 0 and len(items) >= max_items:
            items = items[:max_items]
            break
        url = data.get("@odata.nextLink")
    return items


def _parse_properties(properties_json: str) -> dict[str, str]:
    """
    Parse the Properties JSON string from the correlation identity.
    Values are arrays — extract the first element of each.
    Example: {"Email":["user@contoso.com"]} → {"Email": "user@contoso.com"}
    """
    if not properties_json:
        return {}
    try:
        raw = json.loads(properties_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    parsed = {}
    for key, val in raw.items():
        if isinstance(val, list) and len(val) > 0:
            parsed[key] = str(val[0])
        elif isinstance(val, str):
            parsed[key] = val
        else:
            parsed[key] = str(val) if val is not None else ""
    return parsed


def _get_latest_correlation_id(sp_id: str, token: str) -> str:
    """Fetch the latest correlation report ID for the given service principal."""
    url = (
        f"{GRAPH_BASE}/reports/correlations"
        f"?$filter=servicePrincipal/id eq '{sp_id}'"
        f"&$orderby=startDateTime desc"
        f"&$top=1"
    )
    data = _graph_get(url, token)
    reports = data.get("value", [])
    if not reports:
        raise RuntimeError(
            f"No correlation reports found for service principal '{sp_id}'. "
            "Make sure provisioning has run at least once."
        )
    report_id = reports[0]["id"]
    print(f"  Latest correlation report: {report_id}")
    status = reports[0].get("status", "unknown")
    print(f"  Report status: {status}")
    return report_id


def load_salesforce_accounts_graph() -> list[SalesforceAccount]:
    """
    Load 3rd-party app accounts from a Graph correlation report.
    Reads the 'targetIdentity' from each identity record.
    """
    settings = get_settings()
    sp_id = settings.graph_service_principal_id
    if not sp_id:
        raise ValueError(
            "GRAPH_SERVICE_PRINCIPAL_ID is not set. Configure it in .env."
        )

    tenant_id = settings.graph_tenant_id
    token = _get_graph_token(tenant_id)

    # Get the latest correlation report
    report_id = _get_latest_correlation_id(sp_id, token)

    # Fetch all identities from the report
    url = f"{GRAPH_BASE}/reports/correlations/{report_id}/identities"
    print("  Fetching identities from correlation report...")
    identities = _graph_get_all(url, token)
    print(f"  Found {len(identities)} identities in report")

    accounts = []
    for identity in identities:
        target = identity.get("targetIdentity", {})
        if not target:
            continue

        details = target.get("details", {})
        props = _parse_properties(details.get("Properties", ""))

        # Extract account ID from anchor or properties
        anchor = target.get("anchor", {})
        account_id = anchor.get("value", "") or props.get("id", "") or props.get("Id", "")

        # Map fields — support both SCIM names and Salesforce-style names
        first_name = (
            props.get("name.givenName", "")
            or props.get("FirstName", "")
        )
        last_name = (
            props.get("name.familyName", "")
            or props.get("LastName", "")
        )
        display_name = (
            props.get("displayName", "")
            or props.get("name.formatted", "")
            or f"{first_name} {last_name}".strip()
            or props.get("Alias", "")
        )
        # Handle sentinel "None" value from some SCIM providers
        if display_name == "None":
            display_name = f"{first_name} {last_name}".strip()

        email = (
            props.get('emails[type eq "work"].value', "")
            or props.get("Email", "")
        )
        # Also check the matchingProperty for email
        if not email:
            mp = target.get("matchingProperty", {})
            if "email" in mp.get("name", "").lower():
                email = mp.get("value", "")

        username = props.get("userName", "") or props.get("Username", "")

        accounts.append(SalesforceAccount(
            account_id=account_id,
            email=email,
            username=username,
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            phone=props.get("Phone", "") or props.get("phoneNumbers", ""),
            department=props.get("Department", "") or props.get("department", ""),
            title=props.get("ProfileName", "") or props.get("title", ""),
            employee_id=props.get("EmployeeId", "") or props.get("externalId", ""),
            is_active=_parse_bool(props.get("active", "") or props.get("IsActive", "false")),
            source_application=props.get("CompanyName", "") or "SaaS Application",
        ))

    return accounts


def load_entra_users_graph() -> list[EntraUser]:
    """
    Load Entra ID users from Microsoft Graph /users endpoint.
    Requires User.Read.All permission.
    """
    settings = get_settings()
    tenant_id = settings.graph_tenant_id
    token = _get_graph_token(tenant_id)

    select_fields = (
        "id,userPrincipalName,mail,displayName,givenName,surname,"
        "businessPhones,mobilePhone,department,jobTitle,"
        "employeeId,accountEnabled,createdDateTime,userType"
    )
    # Filter to Members only to skip guests and reduce response size
    url = (
        f"{GRAPH_BASE}/users?$select={select_fields}"
        f"&$filter=userType eq 'Member'"
        f"&$top=999"
    )
    MAX_ENTRA_USERS = 2000
    print(f"  Fetching Entra users from Microsoft Graph (max {MAX_ENTRA_USERS})...")
    raw_users = _graph_get_all(url, token, max_items=MAX_ENTRA_USERS)
    print(f"  Found {len(raw_users)} Entra users")

    users = []
    for u in raw_users:
        # Skip external/guest accounts if desired (keep them for now)
        phones = u.get("businessPhones", [])
        phone = phones[0] if phones else ""

        users.append(EntraUser(
            object_id=u.get("id", ""),
            user_principal_name=u.get("userPrincipalName", ""),
            mail=u.get("mail", "") or "",
            display_name=u.get("displayName", "") or "",
            given_name=u.get("givenName", "") or "",
            surname=u.get("surname", "") or "",
            phone=phone,
            mobile_phone=u.get("mobilePhone", "") or "",
            department=u.get("department", "") or "",
            job_title=u.get("jobTitle", "") or "",
            employee_id=u.get("employeeId", "") or "",
            account_enabled=_parse_bool(u.get("accountEnabled", True)),
            user_type=u.get("userType", "Member") or "Member",
        ))
    return users


def write_results_to_kusto(results: list[MatchResult]) -> int:
    """Write match results to the MatchResults Kusto table. Returns row count."""
    cluster, db, token = _get_kusto_connection()

    # Clear old results
    print("  Clearing old MatchResults...")
    _kusto_mgmt(cluster, db, ".clear table MatchResults data", token)

    MATCH_SCHEMA = (
        "SalesforceAccountId:string, SalesforceDisplayName:string, SalesforceEmail:string, "
        "EntraObjectId:string, EntraDisplayName:string, EntraUPN:string, "
        "MatchCategory:string, CompositeScore:real, EmailMatchScore:real, "
        "NameMatchScore:real, PhoneMatchScore:real, DepartmentMatchScore:real, "
        "TitleMatchScore:real, EmployeeIdMatch:bool, AIFlags:string, "
        "AIReasoningSummary:string, MatchTimestamp:datetime"
    )

    def _esc(val):
        return (val or "").replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")

    # Ingest in batches of 5
    batch_size = 5
    written = 0
    for i in range(0, len(results), batch_size):
        batch = results[i:i + batch_size]
        kql_rows = []
        for r in batch:
            emp_match = "true" if r.employee_id_match else "false"
            ts = r.match_timestamp.strftime("%Y-%m-%dT%H:%M:%S") if r.match_timestamp else "2026-01-01T00:00:00"
            kql_rows.append(
                f'  "{_esc(r.salesforce_account_id)}", "{_esc(r.salesforce_display_name)}", '
                f'"{_esc(r.salesforce_email)}", "{_esc(r.entra_object_id)}", '
                f'"{_esc(r.entra_display_name)}", "{_esc(r.entra_upn)}", '
                f'"{r.match_category}", {r.composite_score:.2f}, {r.email_match_score:.2f}, '
                f'{r.name_match_score:.2f}, {r.phone_match_score:.2f}, '
                f'{r.department_match_score:.2f}, {r.title_match_score:.2f}, '
                f'{emp_match}, "{_esc(r.ai_flags)}", "{_esc(r.ai_reasoning_summary)}", '
                f'datetime("{ts}")'
            )
        row_literals = ",\n".join(kql_rows)
        cmd = f".set-or-append MatchResults <| datatable({MATCH_SCHEMA}) [\n{row_literals}\n]"
        _kusto_mgmt(cluster, db, cmd, token)
        written += len(batch)

    return written


# ── Main entry point ──

def load_data() -> tuple[list[SalesforceAccount], list[EntraUser]]:
    """
    Load data from the configured source (local CSV, Kusto, or Graph).
    Returns (salesforce_accounts, entra_users).
    """
    settings = get_settings()

    if settings.data_source == "graph":
        print("Loading data from Microsoft Graph API (correlation reports)...")
        sf_accounts = load_salesforce_accounts_graph()
        entra_users = load_entra_users_graph()
    elif settings.data_source == "kusto":
        print("Loading data from Azure Data Explorer (Kusto)...")
        sf_accounts = load_salesforce_accounts_kusto()
        entra_users = load_entra_users_kusto()
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(project_root, "data")

        sf_path = os.path.join(data_dir, "salesforce_accounts.csv")
        entra_path = os.path.join(data_dir, "entra_users.csv")

        if not os.path.exists(sf_path) or not os.path.exists(entra_path):
            raise FileNotFoundError(
                f"Sample data not found. Run 'python -m src.generate_sample_data' first.\n"
                f"Expected: {sf_path} and {entra_path}"
            )

        print("Loading data from local CSV files...")
        sf_accounts = load_salesforce_accounts_local(sf_path)
        entra_users = load_entra_users_local(entra_path)

    print(f"  Loaded {len(sf_accounts)} Salesforce accounts")
    print(f"  Loaded {len(entra_users)} Entra users")
    return sf_accounts, entra_users
