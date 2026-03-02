<#
.SYNOPSIS
    Exports uncorrelated app accounts from a correlation report to CSV.

.DESCRIPTION
    Connects to Microsoft Graph and fetches the latest correlation report for a
    given service principal, then exports the uncorrelated target identities
    (3rd-party app accounts) with SCIM property parsing. Output CSV matches the
    format expected by the Account Discovery matching pipeline.

.PARAMETER ServicePrincipalId
    The Object ID of the service principal (enterprise app) to get the
    correlation report for. Required.

.PARAMETER OutputPath
    Path for the output CSV file. Defaults to .\target_accounts.csv

.PARAMETER IncludeCorrelated
    If set, includes already-correlated identities in addition to uncorrelated.

.EXAMPLE
    .\Export-AppAccounts.ps1 -ServicePrincipalId "<your-service-principal-object-id>"
    .\Export-AppAccounts.ps1 -ServicePrincipalId "<your-sp-id>" -OutputPath C:\data\accounts.csv
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServicePrincipalId,

    [string]$OutputPath = ".\target_accounts.csv",

    [switch]$IncludeCorrelated
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Account Discovery - Export App Accounts ===" -ForegroundColor Cyan
Write-Host "  Service Principal: $ServicePrincipalId"

# ── Connect to Graph ──
# We need beta endpoint access for correlation reports
Write-Host "Connecting to Microsoft Graph (interactive login)..." -ForegroundColor Yellow
Connect-MgGraph -Scopes "AuditLog.Read.All" -NoWelcome

# ── Get latest correlation report ──
Write-Host "Fetching latest correlation report..." -ForegroundColor Yellow

$reportsUri = "beta/reports/correlations?`$filter=servicePrincipal/id eq '$ServicePrincipalId'&`$orderby=startDateTime desc&`$top=1"
$reportsResponse = Invoke-MgGraphRequest -Method GET -Uri $reportsUri

$reports = $reportsResponse.value
if (-not $reports -or $reports.Count -eq 0) {
    Write-Error "No correlation reports found for service principal '$ServicePrincipalId'. Make sure provisioning has run at least once."
    return
}

$report = $reports[0]
$reportId = $report.id
Write-Host "  Report ID: $reportId"
Write-Host "  Status: $($report.status)"
Write-Host "  Start: $($report.startDateTime)"

# ── Fetch identities with pagination ──
Write-Host "Fetching identities from report..." -ForegroundColor Yellow

$identities = @()
$nextUri = "beta/reports/correlations/$reportId/identities"

while ($nextUri) {
    $response = Invoke-MgGraphRequest -Method GET -Uri $nextUri
    $identities += $response.value
    $nextUri = $response.'@odata.nextLink'
    if ($nextUri) {
        # Convert full URL to relative for Invoke-MgGraphRequest
        $nextUri = $nextUri -replace "^https://graph\.microsoft\.com/", ""
    }
}

Write-Host "  Total identities in report: $($identities.Count)"

# ── Filter to uncorrelated only (unless -IncludeCorrelated) ──
if (-not $IncludeCorrelated) {
    $identities = $identities | Where-Object { $_.status -eq "uncorrelated" }
    Write-Host "  Uncorrelated identities: $($identities.Count)" -ForegroundColor Yellow
} else {
    Write-Host "  Including all identities (correlated + uncorrelated)"
}

# ── Parse SCIM Properties and map to CSV ──
$csvRows = foreach ($identity in $identities) {
    $target = $identity.targetIdentity
    if (-not $target) { continue }

    $details = $target.details
    $propsJson = $details.Properties

    # Parse the Properties JSON string
    $props = @{}
    if ($propsJson) {
        try {
            $rawProps = $propsJson | ConvertFrom-Json
            # Values are arrays — extract first element
            foreach ($key in $rawProps.PSObject.Properties.Name) {
                $val = $rawProps.$key
                if ($val -is [System.Array] -and $val.Count -gt 0) {
                    $props[$key] = [string]$val[0]
                } elseif ($val) {
                    $props[$key] = [string]$val
                } else {
                    $props[$key] = ""
                }
            }
        } catch {
            Write-Warning "Failed to parse Properties for identity $($identity.id): $_"
        }
    }

    # Extract account ID from anchor or properties
    $accountId = $target.anchor.value
    if (-not $accountId) { $accountId = $props["id"] }
    if (-not $accountId) { $accountId = $props["Id"] }
    if (-not $accountId) { $accountId = $identity.id }

    # Map SCIM fields to our standard columns (support both SCIM and Salesforce naming)
    $firstName = if ($props["name.givenName"]) { $props["name.givenName"] }
                 elseif ($props["FirstName"]) { $props["FirstName"] }
                 else { "" }

    $lastName = if ($props["name.familyName"]) { $props["name.familyName"] }
                elseif ($props["LastName"]) { $props["LastName"] }
                else { "" }

    $displayName = if ($props["displayName"] -and $props["displayName"] -ne "None") {
                       $props["displayName"]
                   } elseif ($props["name.formatted"]) {
                       $props["name.formatted"]
                   } elseif ($firstName -or $lastName) {
                       "$firstName $lastName".Trim()
                   } else { "" }

    # Email — check SCIM work email, then standard Email field, then matchingProperty
    $emailKey = 'emails[type eq "work"].value'
    $email = if ($props[$emailKey]) { $props[$emailKey] }
             elseif ($props["Email"]) { $props["Email"] }
             else { "" }
    if (-not $email -and $target.matchingProperty.name -match "email") {
        $email = $target.matchingProperty.value
    }

    $username = if ($props["userName"]) { $props["userName"] }
                elseif ($props["Username"]) { $props["Username"] }
                else { "" }

    [PSCustomObject]@{
        AccountId         = $accountId
        Email             = $email
        Username          = $username
        DisplayName       = $displayName
        FirstName         = $firstName
        LastName          = $lastName
        Phone             = if ($props["Phone"]) { $props["Phone"] } else { "" }
        Department        = if ($props["Department"]) { $props["Department"] }
                            elseif ($props["department"]) { $props["department"] }
                            else { "" }
        Title             = if ($props["ProfileName"]) { $props["ProfileName"] }
                            elseif ($props["title"]) { $props["title"] }
                            else { "" }
        EmployeeId        = if ($props["EmployeeId"]) { $props["EmployeeId"] }
                            elseif ($props["externalId"]) { $props["externalId"] }
                            else { "" }
        IsActive          = if ($props["active"]) { $props["active"] }
                            elseif ($props["IsActive"]) { $props["IsActive"] }
                            else { "True" }
        SourceApplication = "SaaS Application"
        Status            = $identity.status
    }
}

# ── Write CSV ──
$csvRows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host "  Exported $($csvRows.Count) accounts to: $OutputPath" -ForegroundColor Green

# Show summary
$activeCount = ($csvRows | Where-Object { $_.IsActive -eq "True" }).Count
$inactiveCount = $csvRows.Count - $activeCount
$withEmail = ($csvRows | Where-Object { $_.Email }).Count
Write-Host "  Active: $activeCount | Inactive: $inactiveCount | With email: $withEmail"

# ── Disconnect ──
Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null
Write-Host "Done." -ForegroundColor Cyan
Write-Host ""
