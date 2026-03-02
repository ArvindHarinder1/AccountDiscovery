# Account Discovery Prototype — Project Plan

## 1. Problem Statement

When 3rd-party application accounts (Salesforce, ServiceNow, Dropbox) are imported into Microsoft Entra Identity Governance, many accounts lack a clear matching attribute (e.g., shared email or UPN). Admins need a way to:

1. **Exact-match** accounts when a deterministic attribute exists (email, employee ID, UPN)
2. **Fuzzy-match** accounts using secondary attributes (display name, phone number, department, etc.) and surface a confidence score
3. **AI-augmented analysis** — detect patterns (test accounts, service accounts, naming anomalies) and provide intelligent match recommendations

This prototype is **reporting-based** (not real-time) and handles **10s to thousands** of users per application.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Azure Data Explorer (Kusto)               │
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │ SalesforceAccounts   │    │ EntraUsers                  │ │
│  │ (3rd-party accounts) │    │ (Entra ID directory users)  │ │
│  └─────────┬───────────┘    └──────────┬──────────────────┘ │
└────────────┼───────────────────────────┼────────────────────┘
             │                           │
             ▼                           ▼
┌─────────────────────────────────────────────────────────────┐
│              Python Matching Engine                          │
│                                                              │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │ Tier 1:      │  │ Tier 2:       │  │ Tier 3:          │ │
│  │ Deterministic│  │ Fuzzy/        │  │ AI Agent         │ │
│  │ Matching     │  │ Statistical   │  │ Analysis         │ │
│  │              │  │ Matching      │  │                  │ │
│  │ - Email      │  │ - Jaro-Winkler│  │ - Pattern detect │ │
│  │ - UPN        │  │ - Phone norm  │  │ - Test accounts  │ │
│  │ - EmployeeID │  │ - Tokenized   │  │ - Semantic match │ │
│  │              │  │   name match  │  │ - Confidence     │ │
│  │              │  │ - Record      │  │   calibration    │ │
│  │              │  │   linkage     │  │                  │ │
│  └──────┬───────┘  └──────┬────────┘  └───────┬──────────┘ │
│         │                 │                    │             │
│         ▼                 ▼                    ▼             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Score Aggregation & Reporting               ││
│  │  - Weighted composite score (0-100)                     ││
│  │  - Match category: Exact / High / Medium / Low / None   ││
│  │  - AI flags: test account, service account, anomaly     ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│  Output: Match Report (CSV/JSON + Kusto results table)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Kusto Table Design

### Table: `SalesforceAccounts`
| Column              | Type     | Description                                    |
|---------------------|----------|------------------------------------------------|
| AccountId           | string   | Salesforce unique account/user ID              |
| Email               | string   | Email address from Salesforce                  |
| Username            | string   | Salesforce username (often email-like)          |
| DisplayName         | string   | Full display name                              |
| FirstName           | string   | First name                                     |
| LastName            | string   | Last name                                      |
| Phone               | string   | Phone number                                   |
| Department          | string   | Department                                     |
| Title               | string   | Job title                                      |
| EmployeeId          | string   | Employee ID (if populated)                     |
| IsActive            | bool     | Whether the account is active in Salesforce    |
| LastLoginDate       | datetime | Last login timestamp                           |
| CreatedDate         | datetime | Account creation date                          |
| SourceApplication   | string   | Always "Salesforce" (extensible for other apps)|

### Table: `EntraUsers`
| Column              | Type     | Description                                    |
|---------------------|----------|------------------------------------------------|
| ObjectId            | string   | Entra Object ID (GUID)                         |
| UserPrincipalName   | string   | UPN (e.g., user@contoso.com)                   |
| Mail                | string   | Primary email                                  |
| DisplayName         | string   | Full display name                              |
| GivenName           | string   | First name                                     |
| Surname             | string   | Last name                                      |
| Phone               | string   | Business phone                                 |
| MobilePhone         | string   | Mobile phone                                   |
| Department          | string   | Department                                     |
| JobTitle            | string   | Job title                                      |
| EmployeeId          | string   | Employee ID                                    |
| AccountEnabled      | bool     | Whether the account is enabled                 |
| CreatedDateTime     | datetime | Account creation date                          |
| UserType            | string   | Member or Guest                                |

### Table: `MatchResults`
| Column                 | Type     | Description                                  |
|------------------------|----------|----------------------------------------------|
| SalesforceAccountId    | string   | FK to SalesforceAccounts                     |
| EntraObjectId          | string   | FK to EntraUsers (null if no match)          |
| MatchCategory          | string   | Exact / High / Medium / Low / None           |
| CompositeScore         | real     | 0-100 weighted confidence score              |
| EmailMatchScore        | real     | Email similarity score                       |
| NameMatchScore         | real     | Name similarity score                        |
| PhoneMatchScore        | real     | Phone match score                            |
| DepartmentMatchScore   | real     | Department similarity                        |
| TitleMatchScore        | real     | Job title similarity                         |
| EmployeeIdMatch        | bool     | Exact employee ID match                      |
| AIFlags                | string   | JSON: test account, service account, etc.    |
| AIReasoningSummary     | string   | LLM-generated explanation of the match       |
| MatchTimestamp         | datetime | When the match was computed                  |

---

## 4. Matching Strategy — Three Tiers

### Tier 1: Deterministic Matching (Score = 100)
Exact matches on unique identifiers. If any of these match, it's a confirmed match:
- **Email ↔ Mail/UPN** (case-insensitive, after stripping aliases)
- **EmployeeId ↔ EmployeeId**
- **Username ↔ UPN** (after domain normalization)

### Tier 2: Fuzzy/Statistical Matching (Score = 0-95)
When no exact match exists, compare multiple attributes with weighted scoring:

| Attribute Comparison       | Algorithm                    | Weight | Rationale                        |
|----------------------------|------------------------------|--------|----------------------------------|
| DisplayName similarity     | **Jaro-Winkler** distance    | 30%    | Best for person name matching    |
| First+Last name similarity | **Jaro-Winkler** + tokenized | 25%    | Handles name order variations    |
| Phone number match         | **Normalized comparison**    | 20%    | Strip formatting, country codes  |
| Email local-part similarity| **Levenshtein** ratio        | 10%    | Catches typos in email prefixes  |
| Department similarity      | **Token set ratio** (fuzzywuzzy) | 10% | "Engineering" ≈ "Eng"          |
| Job title similarity       | **Token set ratio**          | 5%     | Lower weight, often inconsistent |

**Why Jaro-Winkler for names?**
- Specifically designed for name matching (gives bonus to common prefixes)
- Handles transpositions well ("John Smith" vs "Jon Smith")
- Scale: 0.0 (no match) to 1.0 (exact) — intuitive for scoring

**Python libraries:**
- `recordlinkage` — purpose-built for entity resolution / record linkage
- `jellyfish` — fast Jaro-Winkler, Soundex, Metaphone implementations
- `thefuzz` (fuzzywuzzy) — token-based fuzzy string matching
- `phonenumbers` — phone number parsing and normalization

### Tier 3: AI Agent Analysis (Augments Tier 1 & 2)
An Azure OpenAI-powered agent that:

1. **Pattern Detection** — Scans the Salesforce account list and flags:
   - Test accounts (names containing "test", "demo", "sandbox", "admin")
   - Service accounts (non-human naming patterns)
   - Duplicate/similar accounts within the same source
   - Accounts with suspicious or incomplete data

2. **Semantic Match Reasoning** — For medium/low confidence matches:
   - Takes the top-N Entra candidates for each unmatched Salesforce account
   - Uses GPT-4o to reason about whether the match makes sense given all attributes
   - Generates a human-readable explanation ("This Salesforce account 'J. Smith' in Engineering likely matches Entra user 'John Smith' in the Engineering department based on matching department, similar name, and same phone number")

3. **Confidence Calibration** — The AI reviews borderline matches and adjusts scores:
   - Boosts scores when contextual signals align (same department + similar title + close name)
   - Lowers scores when there are red flags (different department, name similarity is coincidental)

---

## 5. Scoring Model

```
CompositeScore = 
  If Tier1_ExactMatch → 100
  Else:
    weighted_fuzzy_score = Σ(attribute_score × weight) × 100
    ai_adjustment = AI_confidence_delta  (range: -15 to +15)
    final_score = clamp(weighted_fuzzy_score + ai_adjustment, 0, 99)
```

### Match Categories
| Category | Score Range | Meaning                                      |
|----------|-------------|----------------------------------------------|
| Exact    | 100         | Deterministic match on unique identifier     |
| High     | 80-99       | Very likely the same person                  |
| Medium   | 50-79       | Probable match, admin should verify          |
| Low      | 25-49       | Possible match, low confidence               |
| None     | 0-24        | No meaningful match found                    |

---

## 6. Implementation Plan

### Phase 1: Infrastructure (Steps 1-2)
1. **Set up Azure MCP Server** — Install the VS Code extension, authenticate, connect to your Azure subscription
2. **Create Kusto tables** — Use Azure MCP or KQL scripts to create the three tables (SalesforceAccounts, EntraUsers, MatchResults)

### Phase 2: Data & Matching Engine (Steps 3-5)
3. **Generate sample data** — Create realistic synthetic data for both tables (50-100 users with intentional overlaps, near-misses, and non-matches)
4. **Build deterministic matcher** — Python module for Tier 1 exact matching
5. **Build fuzzy matcher** — Python module for Tier 2 using recordlinkage + jellyfish + thefuzz

### Phase 3: AI Integration (Step 6)
6. **Build AI agent** — Azure OpenAI integration for pattern detection, semantic matching, and confidence calibration

### Phase 4: Orchestration & Reporting (Steps 7-8)
7. **Build orchestrator** — Main pipeline that reads from Kusto, runs all three tiers, writes results back
8. **Generate reports** — CSV/JSON output with match results, AI flags, and reasoning summaries

---

## 7. Tech Stack

| Component                | Technology                        |
|--------------------------|-----------------------------------|
| Data storage             | Azure Data Explorer (Kusto)       |
| Kusto interaction        | `azure-kusto-data` Python SDK     |
| Matching engine          | Python 3.11+                      |
| Fuzzy matching           | `recordlinkage`, `jellyfish`, `thefuzz` |
| Phone normalization      | `phonenumbers`                    |
| AI agent                 | Azure OpenAI (GPT-4o)             |
| AI SDK                   | `openai` Python SDK               |
| Configuration            | `.env` + `pydantic-settings`      |
| Reporting                | `pandas` → CSV/JSON               |

---

## 8. Key Design Decisions

### Why Kusto (Azure Data Explorer)?
- Native to the Microsoft stack, already used in IGA engineering
- Excellent for batch analytics and reporting workloads
- KQL is powerful for ad-hoc exploration of match results
- Scales from small datasets to millions of records

### Why a hybrid deterministic + AI approach?
- **Deterministic matching** is fast, explainable, and reliable for clear cases
- **Fuzzy matching** handles the "close but not exact" cases with measurable confidence
- **AI agents** catch what rules can't: contextual reasoning, pattern detection, and natural-language explanations for admins
- The combination provides **auditability** (deterministic scores) + **intelligence** (AI reasoning)

### Why not purely ML-based matching?
- For 10s-thousands of users, sophisticated ML models (learned embeddings, trained classifiers) are overkill
- Record linkage + fuzzy string matching is a well-established discipline with proven algorithms
- AI augmentation via LLM gives us the "intelligence" without needing training data
- Easier to explain to admins: "These matched because the names are 92% similar and the phone numbers are identical"
