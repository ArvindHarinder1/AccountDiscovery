<#
.SYNOPSIS
    Account Discovery — Matches 3rd-party app accounts to Entra ID users.

.DESCRIPTION
    Downloads the Account Discovery matching engine from GitHub, installs Python
    dependencies, and runs the 3-tier matching pipeline (deterministic, fuzzy, AI)
    against two input CSV files.

    The input CSVs can be generated using the companion scripts:
      - Export-EntraUsers.ps1      → entra_users.csv
      - Export-AppAccounts.ps1     → target_accounts.csv

.PARAMETER EntraCsv
    Path to the Entra users CSV file. Required.

.PARAMETER AppAccountsCsv
    Path to the target app accounts CSV file. Required.

.PARAMETER OutputDir
    Directory for match results. Defaults to .\output

.PARAMETER AzureOpenAIEndpoint
    (Optional) Azure OpenAI endpoint for AI-powered matching. If not provided,
    the pipeline runs Tier 1 + Tier 2 only (no AI enhancement).
    Example: https://myresource.openai.azure.com/

.PARAMETER AzureOpenAIDeployment
    (Optional) Azure OpenAI deployment name. Defaults to gpt-4o.

.PARAMETER SkipAI
    Skip Tier 3 AI analysis entirely. Faster, no Azure OpenAI needed.

.PARAMETER RepoUrl
    GitHub repo URL to download. Defaults to the official repo.

.PARAMETER LocalRepo
    Use a local checkout instead of downloading from GitHub. Provide the path.

.EXAMPLE
    # Basic run (Tier 1 + Tier 2 only, no AI):
    .\Run-AccountDiscovery.ps1 -EntraCsv .\entra_users.csv -AppAccountsCsv .\target_accounts.csv

    # With Azure OpenAI (Tier 1 + 2 + 3):
    .\Run-AccountDiscovery.ps1 -EntraCsv .\entra_users.csv -AppAccountsCsv .\target_accounts.csv `
        -AzureOpenAIEndpoint "https://myresource.openai.azure.com/"

    # Full workflow from scratch:
    .\Export-EntraUsers.ps1
    .\Export-AppAccounts.ps1 -ServicePrincipalId "<your-sp-id>"
    .\Run-AccountDiscovery.ps1 -EntraCsv .\entra_users.csv -AppAccountsCsv .\target_accounts.csv
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EntraCsv,

    [Parameter(Mandatory = $true)]
    [string]$AppAccountsCsv,

    [string]$OutputDir = ".\output",

    [string]$AzureOpenAIEndpoint = "",
    [string]$AzureOpenAIDeployment = "gpt-4o",
    [string]$AzureOpenAIApiVersion = "2024-10-21",

    [switch]$SkipAI,

    [string]$RepoUrl = "https://github.com/ArvindHarinder1/AccountDiscovery/archive/refs/heads/main.zip",
    [string]$LocalRepo = ""
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ACCOUNT DISCOVERY - Setup and Run" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# ── Validate inputs ──
if (-not (Test-Path $EntraCsv)) {
    Write-Error "Entra users CSV not found: $EntraCsv"
    return
}
if (-not (Test-Path $AppAccountsCsv)) {
    Write-Error "App accounts CSV not found: $AppAccountsCsv"
    return
}

$EntraCsv = (Resolve-Path $EntraCsv).Path
$AppAccountsCsv = (Resolve-Path $AppAccountsCsv).Path
Write-Host "  Entra CSV:     $EntraCsv"
Write-Host "  Accounts CSV:  $AppAccountsCsv"

$entraCount = (Import-Csv $EntraCsv).Count
$accountsCount = (Import-Csv $AppAccountsCsv).Count
Write-Host "  Entra users:   $entraCount"
Write-Host "  App accounts:  $accountsCount"

# ── Check Python ──
Write-Host ""
Write-Host "Checking Python..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-Host "  Found: $ver" -ForegroundColor Green
                break
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Error @"
Python 3.10+ is required but not found.
Install from https://www.python.org/downloads/ and ensure it's on PATH.
"@
    return
}

# ── Get the repo ──
if ($LocalRepo) {
    $repoDir = $LocalRepo
    if (-not (Test-Path "$repoDir\src\main.py")) {
        Write-Error "Local repo path doesn't contain src\main.py: $LocalRepo"
        return
    }
    Write-Host "Using local repo: $repoDir" -ForegroundColor Green
} else {
    $tempDir = Join-Path $env:TEMP "AccountDiscovery"
    $zipPath = Join-Path $env:TEMP "AccountDiscovery.zip"

    Write-Host "Downloading Account Discovery from GitHub..." -ForegroundColor Yellow
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $RepoUrl -OutFile $zipPath -UseBasicParsing
    } catch {
        Write-Error "Failed to download repo: $_"
        return
    }

    Write-Host "  Extracting..." -ForegroundColor Yellow
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    Remove-Item $zipPath -Force

    # Find the extracted folder (GitHub adds a suffix like -main)
    $extracted = Get-ChildItem $tempDir -Directory | Select-Object -First 1
    $repoDir = $extracted.FullName
    Write-Host "  Extracted to: $repoDir" -ForegroundColor Green
}

# ── Install Python dependencies ──
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
$requirementsPath = Join-Path $repoDir "requirements.txt"

$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
if (Test-Path $requirementsPath) {
    & $pythonCmd -m pip install -q -r $requirementsPath 2>&1 | Out-Null
} else {
    # Install known dependencies directly
    $deps = @("rapidfuzz", "thefuzz", "phonenumbers", "pydantic-settings", "python-dotenv", "tabulate", "requests")
    if (-not $SkipAI -and $AzureOpenAIEndpoint) {
        $deps += "openai"
    }
    & $pythonCmd -m pip install -q @deps 2>&1 | Out-Null
}
$ErrorActionPreference = $prevEAP

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies (exit code $LASTEXITCODE)"
    return
}
Write-Host "  Dependencies installed." -ForegroundColor Green

# ── Set up the data directory ──
$dataDir = Join-Path $repoDir "data"
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }

# Copy input CSVs to the repo's data directory with expected names
Copy-Item $AppAccountsCsv (Join-Path $dataDir "salesforce_accounts.csv") -Force
Copy-Item $EntraCsv (Join-Path $dataDir "entra_users.csv") -Force

# ── Create .env file ──
$envContent = @"
# Auto-generated by Run-AccountDiscovery.ps1
DATA_SOURCE=local
"@

if (-not $SkipAI -and $AzureOpenAIEndpoint) {
    $envContent += @"

AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=$AzureOpenAIEndpoint
AZURE_OPENAI_DEPLOYMENT=$AzureOpenAIDeployment
AZURE_OPENAI_API_VERSION=$AzureOpenAIApiVersion
"@
    Write-Host ""
    Write-Host "AI enabled: $AzureOpenAIEndpoint ($AzureOpenAIDeployment)" -ForegroundColor Green
    Write-Host "  Make sure you are logged in with: az login" -ForegroundColor Yellow
} else {
    $envContent += @"

AI_PROVIDER=none
"@
    if (-not $SkipAI) {
        Write-Host ""
        Write-Host "AI disabled (no Azure OpenAI endpoint provided). Running Tier 1 + Tier 2 only." -ForegroundColor Yellow
        Write-Host "  To enable AI, pass -AzureOpenAIEndpoint with your endpoint URL" -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "AI skipped (-SkipAI flag)." -ForegroundColor Yellow
    }
}

$envContent | Set-Content (Join-Path $repoDir ".env") -Encoding UTF8

# ── Set up output directory ──
if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir | Out-Null }
$OutputDir = (Resolve-Path $OutputDir).Path
$repoOutputDir = Join-Path $repoDir "output"
if (-not (Test-Path $repoOutputDir)) { New-Item -ItemType Directory -Path $repoOutputDir | Out-Null }

# ── Run the pipeline ──
Write-Host ""
Push-Location $repoDir
try {
    & $pythonCmd -m src.main
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Error "Pipeline failed with exit code $exitCode"
    return
}

# ── Copy results to output directory ──
$latestCsv = Get-ChildItem (Join-Path $repoDir "output") -Filter "match_report_*.csv" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$latestJson = Get-ChildItem (Join-Path $repoDir "output") -Filter "match_report_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($latestCsv) {
    $destCsv = Join-Path $OutputDir $latestCsv.Name
    Copy-Item $latestCsv.FullName $destCsv -Force
    Write-Host ""
    Write-Host "  Results CSV:  $destCsv" -ForegroundColor Green
}
if ($latestJson) {
    $destJson = Join-Path $OutputDir $latestJson.Name
    Copy-Item $latestJson.FullName $destJson -Force
    Write-Host "  Results JSON: $destJson" -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  Account Discovery complete. See results in: $OutputDir" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
