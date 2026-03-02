# Account Discovery: Create Kusto Tables
# Uses Kusto REST API directly with an Azure CLI token. No SDKs needed.

$cluster  = $env:KUSTO_CLUSTER_URI
$database = if ($env:KUSTO_DATABASE) { $env:KUSTO_DATABASE } else { "accounts" }
$tenant   = $env:KUSTO_TENANT_ID

if (-not $cluster -or -not $tenant) {
    Write-Error "Set KUSTO_CLUSTER_URI and KUSTO_TENANT_ID environment variables first."
    return
}

Write-Host ""
Write-Host "=== Account Discovery - Kusto Table Provisioning ===" -ForegroundColor Cyan
Write-Host "  Cluster : $cluster"
Write-Host "  Database: $database"
Write-Host ""

Write-Host "Acquiring token from Azure CLI..."
$token = az account get-access-token --resource https://kusto.kusto.windows.net --tenant $tenant --query accessToken -o tsv
if (-not $token) { Write-Host "ERROR: Failed to get token." -ForegroundColor Red; exit 1 }
Write-Host "  Token acquired."
Write-Host ""

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type"  = "application/json; charset=utf-8"
}

function Invoke-KustoMgmt {
    param([string]$Command, [string]$Label)
    Write-Host "Creating table '$Label'... " -NoNewline
    $body = @{
        db  = $database
        csl = $Command
    } | ConvertTo-Json

    try {
        $resp = Invoke-RestMethod -Uri "$cluster/v1/rest/mgmt" -Method POST -Headers $headers -Body $body
        Write-Host "OK" -ForegroundColor Green
    } catch {
        Write-Host "FAILED" -ForegroundColor Red
        Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Create Tables
$sfCmd = ".create-merge table SalesforceAccounts (AccountId:string, Email:string, Username:string, DisplayName:string, FirstName:string, LastName:string, Phone:string, Department:string, Title:string, EmployeeId:string, IsActive:bool, LastLoginDate:datetime, CreatedDate:datetime, SourceApplication:string)"
Invoke-KustoMgmt -Command $sfCmd -Label "SalesforceAccounts"

$entraCmd = ".create-merge table EntraUsers (ObjectId:string, UserPrincipalName:string, Mail:string, DisplayName:string, GivenName:string, Surname:string, Phone:string, MobilePhone:string, Department:string, JobTitle:string, EmployeeId:string, AccountEnabled:bool, CreatedDateTime:datetime, UserType:string)"
Invoke-KustoMgmt -Command $entraCmd -Label "EntraUsers"

$matchCmd = ".create-merge table MatchResults (SalesforceAccountId:string, SalesforceDisplayName:string, SalesforceEmail:string, EntraObjectId:string, EntraDisplayName:string, EntraUPN:string, MatchCategory:string, CompositeScore:real, EmailMatchScore:real, NameMatchScore:real, PhoneMatchScore:real, DepartmentMatchScore:real, TitleMatchScore:real, EmployeeIdMatch:bool, AIFlags:string, AIReasoningSummary:string, MatchTimestamp:datetime)"
Invoke-KustoMgmt -Command $matchCmd -Label "MatchResults"

# Verify
Write-Host ""
Write-Host "Verifying tables..."
$verifyBody = @{ db = $database; csl = ".show tables" } | ConvertTo-Json
try {
    $resp = Invoke-RestMethod -Uri "$cluster/v1/rest/mgmt" -Method POST -Headers $headers -Body $verifyBody
    $tables = $resp.Tables[0].Rows | ForEach-Object { $_[0] }
    Write-Host "  Tables found: $($tables -join ', ')"

    $expected = @("SalesforceAccounts", "EntraUsers", "MatchResults")
    $missing = $expected | Where-Object { $_ -notin $tables }
    if ($missing) {
        Write-Host "  Missing: $($missing -join ', ')" -ForegroundColor Yellow
    } else {
        Write-Host "  All 3 Account Discovery tables present!" -ForegroundColor Green
    }
} catch {
    Write-Host "  Error verifying: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Done!"
Write-Host ""
