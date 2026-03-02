<#
.SYNOPSIS
    Account Discovery - End-to-End Guided Experience

.DESCRIPTION
    Walks through the complete Account Discovery workflow:
      Step 1: Export Entra ID users to CSV
      Step 2: Export uncorrelated app accounts from a correlation report to CSV
      Step 3: Run the 3-tier matching pipeline

    Each step prompts for confirmation before proceeding. The customer only
    needs to provide the Service Principal ID of the target application.

.PARAMETER ServicePrincipalId
    The Object ID of the service principal (enterprise app) to analyze.
    Find this in Entra ID > Enterprise Applications > your app > Object ID.

.PARAMETER OutputDir
    Directory for all output files. Defaults to .\AccountDiscovery_Output

.PARAMETER MaxUsers
    Maximum number of Entra users to export. Defaults to 2000.

.PARAMETER AzureOpenAIEndpoint
    (Optional) Azure OpenAI endpoint for AI-powered matching (Tier 3).
    If not provided, runs Tier 1 + Tier 2 only.

.PARAMETER AzureOpenAIDeployment
    (Optional) Azure OpenAI deployment name. Defaults to gpt-4o.

.PARAMETER LocalRepo
    (Optional) Use a local repo checkout instead of downloading from GitHub.

.EXAMPLE
    .\Start-AccountDiscovery.ps1 -ServicePrincipalId "your-sp-object-id"

.EXAMPLE
    .\Start-AccountDiscovery.ps1 -ServicePrincipalId "your-sp-id" -AzureOpenAIEndpoint "https://myresource.openai.azure.com/"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServicePrincipalId,

    [string]$OutputDir = ".\AccountDiscovery_Output",

    [int]$MaxUsers = 2000,

    [string]$AzureOpenAIEndpoint = "",
    [string]$AzureOpenAIDeployment = "gpt-4o",

    [string]$LocalRepo = "",
    [string]$RepoUrl = "https://github.com/ArvindHarinder1/AccountDiscovery/archive/refs/heads/main.zip"
)

$ErrorActionPreference = "Stop"

# ── Banner ──
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ACCOUNT DISCOVERY - End-to-End Workflow" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Service Principal:  $ServicePrincipalId"
Write-Host "  Max Entra Users:    $MaxUsers"
if ($AzureOpenAIEndpoint) {
    Write-Host "  AI:                 Enabled ($AzureOpenAIDeployment)" -ForegroundColor Green
} else {
    Write-Host "  AI:                 Disabled (Tier 1 + Tier 2 only)" -ForegroundColor Yellow
}
Write-Host "  Output:             $OutputDir"
Write-Host ""

# ── Create output directory ──
if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir | Out-Null }
$OutputDir = (Resolve-Path $OutputDir).Path

$entraPath = Join-Path $OutputDir "entra_users.csv"
$accountsPath = Join-Path $OutputDir "target_accounts.csv"

# ══════════════════════════════════════════════════════════════════════
#  STEP 1: Export Entra Users
# ══════════════════════════════════════════════════════════════════════

Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  STEP 1 of 3: Export Entra ID Users" -ForegroundColor Cyan
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  This will connect to Microsoft Graph and export up to $MaxUsers"
Write-Host "  Member users from your directory."
Write-Host ""

# Check if we already have the file
if (Test-Path $entraPath) {
    $existingCount = (Import-Csv $entraPath).Count
    Write-Host "  Found existing export: $entraPath ($existingCount users)" -ForegroundColor Yellow
    $reuse = Read-Host "  Use existing file? (Y/n)"
    if ($reuse -eq "" -or $reuse -match "^[Yy]") {
        Write-Host "  Reusing existing Entra users export." -ForegroundColor Green
        $skipStep1 = $true
    } else {
        $skipStep1 = $false
    }
} else {
    $skipStep1 = $false
}

if (-not $skipStep1) {
    $proceed = Read-Host "  Press Enter to start (or 'q' to quit)"
    if ($proceed -match "^[Qq]") {
        Write-Host "  Cancelled." -ForegroundColor Yellow
        return
    }

    $scriptDir = $PSScriptRoot
    & "$scriptDir\Export-EntraUsers.ps1" -OutputPath $entraPath -MaxUsers $MaxUsers
    
    if (-not (Test-Path $entraPath)) {
        Write-Error "Entra users export failed - file not created."
        return
    }
}

$entraCount = (Import-Csv $entraPath).Count
Write-Host ""
Write-Host "  Step 1 complete: $entraCount Entra users exported" -ForegroundColor Green
Write-Host ""

# ══════════════════════════════════════════════════════════════════════
#  STEP 2: Export App Accounts
# ══════════════════════════════════════════════════════════════════════

Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  STEP 2 of 3: Export App Accounts (Correlation Report)" -ForegroundColor Cyan
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  This will fetch the latest correlation report for service principal"
Write-Host "  $ServicePrincipalId and export the uncorrelated"
Write-Host "  third-party app accounts."
Write-Host ""

if (Test-Path $accountsPath) {
    $existingCount = (Import-Csv $accountsPath).Count
    Write-Host "  Found existing export: $accountsPath ($existingCount accounts)" -ForegroundColor Yellow
    $reuse = Read-Host "  Use existing file? (Y/n)"
    if ($reuse -eq "" -or $reuse -match "^[Yy]") {
        Write-Host "  Reusing existing app accounts export." -ForegroundColor Green
        $skipStep2 = $true
    } else {
        $skipStep2 = $false
    }
} else {
    $skipStep2 = $false
}

if (-not $skipStep2) {
    $proceed = Read-Host "  Press Enter to start (or 'q' to quit)"
    if ($proceed -match "^[Qq]") {
        Write-Host "  Cancelled." -ForegroundColor Yellow
        return
    }

    $scriptDir = $PSScriptRoot
    & "$scriptDir\Export-AppAccounts.ps1" -ServicePrincipalId $ServicePrincipalId -OutputPath $accountsPath

    if (-not (Test-Path $accountsPath)) {
        Write-Error "App accounts export failed - file not created."
        return
    }
}

$accountsCount = (Import-Csv $accountsPath).Count
Write-Host ""
Write-Host "  Step 2 complete: $accountsCount app accounts exported" -ForegroundColor Green
Write-Host ""

# ══════════════════════════════════════════════════════════════════════
#  STEP 3: Run Matching Pipeline
# ══════════════════════════════════════════════════════════════════════

Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  STEP 3 of 3: Run Account Discovery Matching" -ForegroundColor Cyan
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Matching $accountsCount app accounts against $entraCount Entra users..."
Write-Host ""
Write-Host "  Tiers:"
Write-Host "    1. Deterministic - Exact email and employee ID matching"
Write-Host "    2. Fuzzy         - Name, username, phone similarity scoring"
if ($AzureOpenAIEndpoint) {
    Write-Host "    3. AI            - GPT-4o semantic analysis of borderline matches" -ForegroundColor Green
} else {
    Write-Host "    3. AI            - Skipped (no Azure OpenAI endpoint provided)" -ForegroundColor Yellow
}
Write-Host ""

$proceed = Read-Host "  Press Enter to start matching (or 'q' to quit)"
if ($proceed -match "^[Qq]") {
    Write-Host "  Cancelled." -ForegroundColor Yellow
    return
}

$resultsDir = Join-Path $OutputDir "results"
$scriptDir = $PSScriptRoot

$runParams = @{
    EntraCsv       = $entraPath
    AppAccountsCsv = $accountsPath
    OutputDir      = $resultsDir
}

if ($LocalRepo) {
    $runParams.LocalRepo = $LocalRepo
} else {
    $runParams.RepoUrl = $RepoUrl
}

if ($AzureOpenAIEndpoint) {
    $runParams.AzureOpenAIEndpoint = $AzureOpenAIEndpoint
    $runParams.AzureOpenAIDeployment = $AzureOpenAIDeployment
} else {
    $runParams.SkipAI = $true
}

& "$scriptDir\Run-AccountDiscovery.ps1" @runParams

# ══════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ALL DONE" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Output files are in: $OutputDir"
Write-Host ""

$resultsCsv = Get-ChildItem (Join-Path $OutputDir "results") -Filter "match_report_*.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($resultsCsv) {
    Write-Host "  Match report: $($resultsCsv.FullName)" -ForegroundColor Green
    Write-Host ""

    # Quick summary from CSV
    $results = Import-Csv $resultsCsv.FullName
    $total = $results.Count
    $exact = ($results | Where-Object { [double]$_.CompositeScore -eq 100 }).Count
    $high = ($results | Where-Object { [double]$_.CompositeScore -ge 80 -and [double]$_.CompositeScore -lt 100 }).Count
    $medium = ($results | Where-Object { [double]$_.CompositeScore -ge 50 -and [double]$_.CompositeScore -lt 80 }).Count
    $low = ($results | Where-Object { [double]$_.CompositeScore -ge 25 -and [double]$_.CompositeScore -lt 50 }).Count
    $none = ($results | Where-Object { [double]$_.CompositeScore -lt 25 }).Count

    Write-Host "  Quick Summary:" -ForegroundColor Cyan
    Write-Host "    Total accounts:     $total"
    Write-Host "    Exact matches:      $exact" -ForegroundColor Green
    Write-Host "    High confidence:    $high" -ForegroundColor Green
    Write-Host "    Medium confidence:  $medium" -ForegroundColor Yellow
    Write-Host "    Low confidence:     $low" -ForegroundColor Yellow
    Write-Host "    No match:           $none" -ForegroundColor Red
}

Write-Host ""
