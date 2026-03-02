<#
.SYNOPSIS
    Exports Entra ID users to a CSV file for Account Discovery matching.

.DESCRIPTION
    Connects to Microsoft Graph and exports Member users with the fields needed
    by the Account Discovery matching pipeline. Uses interactive login via the
    Microsoft Graph PowerShell SDK (Microsoft.Graph.Users module).

.PARAMETER OutputPath
    Path for the output CSV file. Defaults to .\entra_users.csv

.PARAMETER MaxUsers
    Maximum number of users to export. Defaults to 2000.

.PARAMETER IncludeGuests
    If set, includes Guest users in addition to Members.

.EXAMPLE
    .\Export-EntraUsers.ps1
    .\Export-EntraUsers.ps1 -OutputPath C:\data\entra_users.csv -MaxUsers 5000
#>

[CmdletBinding()]
param(
    [string]$OutputPath = ".\entra_users.csv",
    [int]$MaxUsers = 2000,
    [switch]$IncludeGuests
)

$ErrorActionPreference = "Stop"

# ── Check for Microsoft Graph module ──
Write-Host ""
Write-Host "=== Account Discovery - Export Entra Users ===" -ForegroundColor Cyan

$requiredModule = "Microsoft.Graph.Users"
if (-not (Get-Module -ListAvailable -Name $requiredModule)) {
    Write-Host "Installing $requiredModule module..." -ForegroundColor Yellow
    Install-Module $requiredModule -Scope CurrentUser -Force -AllowClobber
}
Import-Module $requiredModule -ErrorAction Stop

# ── Connect to Graph ──
Write-Host "Connecting to Microsoft Graph (interactive login)..." -ForegroundColor Yellow
Connect-MgGraph -Scopes "User.Read.All" -NoWelcome

# ── Build filter ──
$filter = "userType eq 'Member'"
if ($IncludeGuests) {
    $filter = $null
    Write-Host "  Including all user types (Members + Guests)"
} else {
    Write-Host "  Filtering to Member users only"
}

# ── Fetch users ──
Write-Host "Fetching up to $MaxUsers users..." -ForegroundColor Yellow

$selectProperties = @(
    "Id",
    "UserPrincipalName",
    "Mail",
    "DisplayName",
    "GivenName",
    "Surname",
    "BusinessPhones",
    "MobilePhone",
    "Department",
    "JobTitle",
    "EmployeeId",
    "AccountEnabled",
    "UserType"
)

$graphParams = @{
    Select      = $selectProperties
    Top         = [Math]::Min($MaxUsers, 999)
    All         = ($MaxUsers -gt 999)
    CountVariable = "totalCount"
    ConsistencyLevel = "eventual"
}
if ($filter) {
    $graphParams.Filter = $filter
}

$users = Get-MgUser @graphParams | Select-Object -First $MaxUsers

Write-Host "  Retrieved $($users.Count) users" -ForegroundColor Green

# ── Map to CSV format ──
$csvRows = foreach ($u in $users) {
    $phone = if ($u.BusinessPhones -and $u.BusinessPhones.Count -gt 0) {
        $u.BusinessPhones[0]
    } else { "" }

    [PSCustomObject]@{
        ObjectId          = $u.Id
        UserPrincipalName = $u.UserPrincipalName
        Mail              = if ($u.Mail) { $u.Mail } else { "" }
        DisplayName       = if ($u.DisplayName) { $u.DisplayName } else { "" }
        GivenName         = if ($u.GivenName) { $u.GivenName } else { "" }
        Surname           = if ($u.Surname) { $u.Surname } else { "" }
        Phone             = $phone
        MobilePhone       = if ($u.MobilePhone) { $u.MobilePhone } else { "" }
        Department        = if ($u.Department) { $u.Department } else { "" }
        JobTitle          = if ($u.JobTitle) { $u.JobTitle } else { "" }
        EmployeeId        = if ($u.EmployeeId) { $u.EmployeeId } else { "" }
        AccountEnabled    = $u.AccountEnabled
        UserType          = if ($u.UserType) { $u.UserType } else { "Member" }
    }
}

# ── Write CSV ──
$csvRows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host "  Exported $($csvRows.Count) users to: $OutputPath" -ForegroundColor Green

# ── Disconnect ──
Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null
Write-Host "Done." -ForegroundColor Cyan
Write-Host ""
