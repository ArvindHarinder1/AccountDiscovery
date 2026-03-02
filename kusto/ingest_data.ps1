# Account Discovery: Ingest CSV data into Kusto tables
# Uses Kusto streaming ingestion via REST API + Azure CLI token.

$cluster  = $env:KUSTO_CLUSTER_URI
$database = if ($env:KUSTO_DATABASE) { $env:KUSTO_DATABASE } else { "accounts" }
$tenant   = $env:KUSTO_TENANT_ID

if (-not $cluster -or -not $tenant) {
    Write-Error "Set KUSTO_CLUSTER_URI and KUSTO_TENANT_ID environment variables first."
    return
}
$dataDir  = Join-Path $PSScriptRoot "..\data"

Write-Host ""
Write-Host "=== Account Discovery - Data Ingestion ===" -ForegroundColor Cyan
Write-Host "  Cluster : $cluster"
Write-Host "  Database: $database"
Write-Host ""

# Get token
Write-Host "Acquiring token..."
$token = az account get-access-token --resource https://kusto.kusto.windows.net --tenant $tenant --query accessToken -o tsv
if (-not $token) { Write-Host "ERROR: Failed to get token." -ForegroundColor Red; exit 1 }
Write-Host "  Token acquired."
Write-Host ""

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type"  = "application/json; charset=utf-8"
}

function Invoke-KustoMgmtSimple {
    param([string]$Command)
    $body = @{ db = $database; csl = $Command } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$cluster/v1/rest/mgmt" -Method POST -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -ContentType "application/json; charset=utf-8"
    return $resp
}

function Invoke-KustoIngestInline {
    param([string]$TableName, [string[]]$Rows)
    # Build the .ingest inline command with actual \t and \n in JSON
    $inlineData = ($Rows -join "\n")
    $cmd = ".ingest inline into table $TableName <|\n$inlineData"
    # Manually build JSON to ensure \t and \n stay as JSON escape sequences
    $escapedCmd = $cmd -replace '\\', '\\' -replace '"', '\"'
    $jsonBody = "{`"db`":`"$database`",`"csl`":`"$escapedCmd`"}"
    $resp = Invoke-RestMethod -Uri "$cluster/v1/rest/mgmt" -Method POST -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($jsonBody)) -ContentType "application/json; charset=utf-8"
    return $resp
}

function Invoke-KustoQuery {
    param([string]$Query)
    $body = @{ db = $database; csl = $Query } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$cluster/v1/rest/query" -Method POST -Headers $headers -Body $body
    return $resp
}

# Clear existing data (for re-runs)
Write-Host "Clearing existing data..."
Invoke-KustoMgmt -Command ".clear table SalesforceAccounts data" | Out-Null
Invoke-KustoMgmt -Command ".clear table EntraUsers data" | Out-Null
Invoke-KustoMgmt -Command ".clear table MatchResults data" | Out-Null
Write-Host "  Cleared all tables."
Write-Host ""

# ── Ingest SalesforceAccounts ──
Write-Host "Ingesting SalesforceAccounts..."
$sfCsv = Get-Content (Join-Path $dataDir "salesforce_accounts.csv") -Encoding UTF8
$sfHeader = $sfCsv[0]
$sfRows = $sfCsv | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }

# Use .ingest inline - tab-separated values
$sfInlineRows = @()
foreach ($line in $sfRows) {
    # Parse CSV line
    $cols = @()
    $current = ""
    $inQuotes = $false
    foreach ($char in $line.ToCharArray()) {
        if ($char -eq '"') { $inQuotes = -not $inQuotes }
        elseif ($char -eq ',' -and -not $inQuotes) { $cols += $current; $current = "" }
        else { $current += $char }
    }
    $cols += $current.TrimEnd("`r")
    if ($cols.Count -lt 14) { continue }

    # Join with tabs for inline ingestion (replace any embedded tabs)
    $clean = $cols | ForEach-Object { $_ -replace "`t", " " }
    $sfInlineRows += ($clean -join "`t")
}

$sfInlineData = $sfInlineRows -join "`n"
$sfCmd = ".ingest inline into table SalesforceAccounts <|`n$sfInlineData"
try {
    Invoke-KustoMgmt -Command $sfCmd | Out-Null
    Write-Host "  Ingested $($sfInlineRows.Count) rows" -ForegroundColor Green
} catch {
    Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
    # Try to get more detail
    try {
        $errorResp = $_.Exception.Response
        $reader = New-Object System.IO.StreamReader($errorResp.GetResponseStream())
        $errorBody = $reader.ReadToEnd()
        Write-Host "  Detail: $errorBody" -ForegroundColor Yellow
    } catch {}
}

# ── Ingest EntraUsers ──
Write-Host "Ingesting EntraUsers..."
$enCsv = Get-Content (Join-Path $dataDir "entra_users.csv") -Encoding UTF8
$enRows = $enCsv | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }

$enInlineRows = @()
foreach ($line in $enRows) {
    $cols = @()
    $current = ""
    $inQuotes = $false
    foreach ($char in $line.ToCharArray()) {
        if ($char -eq '"') { $inQuotes = -not $inQuotes }
        elseif ($char -eq ',' -and -not $inQuotes) { $cols += $current; $current = "" }
        else { $current += $char }
    }
    $cols += $current.TrimEnd("`r")
    if ($cols.Count -lt 14) { continue }

    $clean = $cols | ForEach-Object { $_ -replace "`t", " " }
    $enInlineRows += ($clean -join "`t")
}

$enInlineData = $enInlineRows -join "`n"
$enCmd = ".ingest inline into table EntraUsers <|`n$enInlineData"
try {
    Invoke-KustoMgmt -Command $enCmd | Out-Null
    Write-Host "  Ingested $($enInlineRows.Count) rows" -ForegroundColor Green
} catch {
    Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
    try {
        $errorResp = $_.Exception.Response
        $reader = New-Object System.IO.StreamReader($errorResp.GetResponseStream())
        $errorBody = $reader.ReadToEnd()
        Write-Host "  Detail: $errorBody" -ForegroundColor Yellow
    } catch {}
}

# ── Verify counts ──
Write-Host ""
Write-Host "Verifying row counts..."
$sfResult = Invoke-KustoQuery -Query "SalesforceAccounts | count"
$sfIngested = $sfResult.Tables[0].Rows[0][0]
Write-Host "  SalesforceAccounts: $sfIngested rows"

$enResult = Invoke-KustoQuery -Query "EntraUsers | count"
$enIngested = $enResult.Tables[0].Rows[0][0]
Write-Host "  EntraUsers: $enIngested rows"

Write-Host ""
Write-Host "Done! Data ingested into Kusto." -ForegroundColor Green
Write-Host ""
