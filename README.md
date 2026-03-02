# Account Discovery

A matching engine for **Microsoft Entra Identity Governance** that takes uncorrelated third-party application accounts (from provisioning correlation reports) and matches them against Entra ID users using a three-tier approach:

1. **Deterministic** — exact email and employee ID matching
2. **Fuzzy / statistical** — Jaro-Winkler name similarity, phone normalization, department and title comparison
3. **AI-powered** (optional) — Azure OpenAI pattern detection, semantic reasoning, and confidence calibration

The tool produces a scored match report (CSV + JSON) that administrators can review to correlate accounts that cannot be automatically matched by the provisioning service.

---

## Quick Start (Customer Workflow)

The guided script walks through the entire process interactively. You need:

| Prerequisite | How to get it |
|---|---|
| **PowerShell 5.1+** | Built into Windows |
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) — ensure it's on PATH |
| **Microsoft.Graph PowerShell module** | `Install-Module Microsoft.Graph.Users -Scope CurrentUser` |
| **Azure CLI** | [Install Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) — required only for AI |
| **Service Principal Object ID** | Entra ID → Enterprise Applications → your app → Object ID |

### Run the guided experience

```powershell
# Basic (Tier 1 + Tier 2 only — no Azure OpenAI needed):
.\scripts\Start-AccountDiscovery.ps1 -ServicePrincipalId "<your-sp-object-id>"

# With AI enhancement (Tier 1 + 2 + 3):
.\scripts\Start-AccountDiscovery.ps1 -ServicePrincipalId "<your-sp-object-id>" `
    -AzureOpenAIEndpoint "https://myresource.openai.azure.com/"
```

The script will:
1. **Export Entra users** to CSV via Microsoft Graph
2. **Export uncorrelated app accounts** from the correlation report via Graph beta API
3. **Download the matching engine** (or use a local checkout), install dependencies, and run the pipeline
4. **Output results** to `.\AccountDiscovery_Output\` with a summary of match categories

### Run scripts individually

```powershell
# Step 1 — Export Entra users
.\scripts\Export-EntraUsers.ps1

# Step 2 — Export uncorrelated accounts
.\scripts\Export-AppAccounts.ps1 -ServicePrincipalId "<your-sp-object-id>"

# Step 3 — Run the matching pipeline
.\scripts\Run-AccountDiscovery.ps1 -EntraCsv .\entra_users.csv -AppAccountsCsv .\target_accounts.csv
```

### Run locally with sample data

```powershell
pip install -r requirements.txt
python -m src.generate_sample_data      # creates data/entra_users.csv + data/salesforce_accounts.csv
python -m src.main                      # runs the matching pipeline
```

Reports are written to the `output/` directory (CSV + JSON).

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Data Sources                                                  │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Local CSV │  │ Azure Data       │  │ Microsoft Graph API  │ │
│  │ (default) │  │ Explorer (Kusto) │  │ (correlation reports)│ │
│  └─────┬─────┘  └────────┬─────────┘  └──────────┬───────────┘ │
└────────┼─────────────────┼────────────────────────┼────────────┘
         └─────────────────┼────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Matching Engine (Python)                                      │
│                                                                │
│  Tier 1: Deterministic ──► Exact email + employee ID (100)     │
│          ↓ unmatched                                           │
│  Tier 2: Fuzzy ──────────► Global optimal weighted matching    │
│          ↓ all results                                         │
│  Tier 3: AI Agent ───────► Pattern detection + score adjust    │
│          (optional)         ±15 confidence calibration         │
│                                                                │
│  Score Aggregation ──────► Weighted composite 0–100            │
└────────────────────────────────┬───────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│  Output                                                        │
│  • CSV report (match_results.csv)                              │
│  • JSON report (match_results.json)                            │
│  • Console summary with category breakdown                     │
│  • Optional: write results to Kusto                            │
└────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
Account Discovery/
├── README.md
├── PLAN.md                              # Full design document
├── requirements.txt                     # Python dependencies
├── .env.template                        # Configuration template (copy to .env)
├── .gitignore
│
├── scripts/                             # PowerShell customer scripts
│   ├── Start-AccountDiscovery.ps1       # Guided end-to-end workflow
│   ├── Export-EntraUsers.ps1            # Export Entra users via Graph SDK
│   ├── Export-AppAccounts.ps1           # Export uncorrelated accounts via Graph beta
│   └── Run-AccountDiscovery.ps1         # Download engine + run pipeline
│
├── src/                                 # Python matching engine
│   ├── main.py                          # Entry point (python -m src.main)
│   ├── config.py                        # Pydantic settings from .env
│   ├── models.py                        # SalesforceAccount, EntraUser, MatchResult
│   ├── data_loader.py                   # CSV, Kusto, and Graph data loaders
│   ├── tier1_deterministic.py           # Exact email + employee ID matching
│   ├── tier2_fuzzy.py                   # Global optimal fuzzy matching
│   ├── tier3_ai_agent.py               # AI pattern detection + semantic reasoning
│   ├── orchestrator.py                  # Pipeline orchestration + reporting
│   ├── reporting.py                     # CSV/JSON report generation
│   └── generate_sample_data.py          # Synthetic test data generator
│
├── kusto/                               # Azure Data Explorer utilities
│   ├── create_tables.kql                # Table creation KQL
│   ├── provision_tables.py / .ps1       # Programmatic table provisioning
│   ├── ingest_data.py / .ps1            # Data ingestion scripts
│   ├── test_ingest.py                   # Ingestion smoke test
│   ├── diagnose_match.py               # Match diagnostics
│   └── verify_results.py               # Results verification
│
├── data/                                # Sample CSV data (git-ignored)
└── output/                              # Match reports (git-ignored)
```

---

## Matching Logic

### Tier 1 — Deterministic (Score = 100)

Exact matches on unique identifiers. If any match, the account is confirmed:
- **Email ↔ Mail / UPN** (case-insensitive, cross-domain)
- **Employee ID ↔ Employee ID** (exact)

### Tier 2 — Fuzzy / Statistical (Score = 0–99)

For accounts not matched in Tier 1, all pairwise scores are computed and a **global optimal assignment** (greedy best-first) ensures each Entra user is matched to at most one account:

| Attribute | Algorithm | Weight |
|---|---|---|
| Display name | Jaro-Winkler | 25% |
| First + Last name | Jaro-Winkler + tokenized | 20% |
| Email local-part | Levenshtein ratio | 20% |
| Phone number | Normalized digit comparison | 15% |
| Department | Token set ratio | 10% |
| Username local-part | Levenshtein ratio | 5% |
| Job title | Token set ratio | 5% |

### Tier 3 — AI Agent (Optional)

When `AI_PROVIDER=azure_openai` is set and an Azure OpenAI endpoint is configured:

- **Pattern Detection** — scans all accounts and flags test accounts, service accounts, shared accounts, machine accounts, and naming anomalies
- **Semantic Reasoning** — for low-confidence matches (below medium threshold), GPT-4o evaluates whether the match is plausible and adjusts scores ±15 points
- **Graceful Fallback** — if AI is unavailable or errors occur, the pipeline continues with Tier 1 + 2 results only

Authentication uses Azure CLI tokens (`az login`) — no API keys or secrets are stored.

---

## Match Categories

| Category | Score | Meaning |
|---|---|---|
| **Exact** | 100 | Deterministic match on unique identifier |
| **High** | 80–99 | Very likely the same person |
| **Medium** | 50–79 | Probable match — admin should verify |
| **Low** | 25–49 | Possible match — low confidence |
| **None** | 0–24 | No meaningful match found |

---

## Configuration

Copy `.env.template` to `.env` and fill in the values relevant to your scenario:

```dotenv
# Data source: "local" (CSV files), "kusto" (Azure Data Explorer), "graph" (Microsoft Graph)
DATA_SOURCE=local

# AI: "none" (Tier 1+2 only) or "azure_openai" (Tier 1+2+3)
AI_PROVIDER=none

# Azure OpenAI (only if AI_PROVIDER=azure_openai)
AZURE_OPENAI_ENDPOINT=https://myresource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Azure Data Explorer (only if DATA_SOURCE=kusto)
KUSTO_CLUSTER_URI=https://your-cluster.region.kusto.windows.net
KUSTO_DATABASE=accounts
KUSTO_TENANT_ID=
KUSTO_SUBSCRIPTION_ID=

# Microsoft Graph (only if DATA_SOURCE=graph)
GRAPH_TENANT_ID=
GRAPH_SERVICE_PRINCIPAL_ID=

# Matching thresholds (adjustable)
MATCH_THRESHOLD_HIGH=80
MATCH_THRESHOLD_MEDIUM=50
MATCH_THRESHOLD_LOW=25
```

When using the PowerShell customer scripts, the `.env` file is generated automatically — you don't need to create it manually.

---

## Script Reference

| Script | Purpose |
|---|---|
| `Start-AccountDiscovery.ps1` | Guided end-to-end workflow — runs all three steps with prompts |
| `Export-EntraUsers.ps1` | Exports Entra ID Member users via Microsoft Graph SDK |
| `Export-AppAccounts.ps1` | Exports uncorrelated identities from a correlation report via Graph beta API |
| `Run-AccountDiscovery.ps1` | Downloads the engine, installs deps, runs the matching pipeline |

### Start-AccountDiscovery.ps1 Parameters

| Parameter | Required | Default | Description |
|---|---|---|---|
| `-ServicePrincipalId` | Yes | — | Object ID of the enterprise app |
| `-OutputDir` | No | `.\AccountDiscovery_Output` | Output directory |
| `-MaxUsers` | No | 2000 | Max Entra users to export |
| `-AzureOpenAIEndpoint` | No | — | Enables AI (Tier 3) |
| `-AzureOpenAIDeployment` | No | `gpt-4o` | OpenAI deployment name |
| `-LocalRepo` | No | — | Path to local repo checkout |

---

## Azure Data Explorer (Kusto) Integration

For internal/dev use, the pipeline can read from and write results to Kusto:

1. Provision tables: `python kusto/provision_tables.py` or `.\kusto\provision_tables.ps1`
2. Ingest data: `python kusto/ingest_data.py` or `.\kusto\ingest_data.ps1`
3. Set `DATA_SOURCE=kusto` in `.env`

All Kusto scripts read connection info from environment variables (`KUSTO_CLUSTER_URI`, `KUSTO_TENANT_ID`, `KUSTO_DATABASE`).

---

## Contributing

1. Clone the repo
2. Copy `.env.template` to `.env` and configure
3. `pip install -r requirements.txt`
4. `python -m src.main` to run locally

See [PLAN.md](PLAN.md) for the full architecture and design rationale.
