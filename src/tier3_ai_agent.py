"""
Account Discovery Prototype — Tier 3: AI Agent Layer
Uses Azure OpenAI (GPT-4o) with Azure CLI auth for:
1. Pattern Detection — Flag test accounts, service accounts, anomalies
2. Semantic Match Reasoning — Evaluate borderline matches with context
3. Confidence Calibration — Adjust fuzzy scores based on holistic reasoning

No API keys needed — authenticates via Azure CLI token.
Fallback: GitHub Models with PAT, or rule-based if neither is available.
"""

import json
import os
from typing import Optional

from src.models import SalesforceAccount, EntraUser, MatchResult
from src.config import get_settings


def _get_cli_token_for_openai(tenant_id: str) -> str:
    """Get an Azure AD token for Cognitive Services via Azure CLI.
    If tenant_id is empty, uses the current CLI context (whatever az login is set to).
    """
    import subprocess
    from src.data_loader import _set_az_account
    settings = get_settings()
    # Only switch subscription if explicitly configured (dev scenario with multiple tenants)
    if settings.kusto_subscription_id:
        _set_az_account(settings.kusto_subscription_id)
    az_paths = ["az", r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"]
    for az_cmd in az_paths:
        try:
            cmd = [az_cmd, "account", "get-access-token",
                   "--resource", "https://cognitiveservices.azure.com",
                   "--query", "accessToken", "-o", "tsv"]
            # Only pass --tenant if we have one; otherwise use current CLI context
            if tenant_id:
                cmd.insert(3, "--tenant")
                cmd.insert(4, tenant_id)
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30,
                shell=(az_cmd.endswith(".cmd")),
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except FileNotFoundError:
            continue
    return ""


def _get_ai_client():
    """
    Create an AI client. Tries in order:
    1. Azure OpenAI (CLI token auth — no secrets)
    2. GitHub Models (requires PAT in .env)
    Returns (client, model_name) or (None, None).
    """
    settings = get_settings()

    # ── Explicitly disabled ──
    if settings.ai_provider == "none":
        return None, None

    # ── Option 1: Azure OpenAI with CLI auth ──
    if settings.ai_provider == "azure_openai" and settings.azure_openai_endpoint:
        try:
            from openai import AzureOpenAI
        except ImportError:
            print("  [AI Warning] openai package not installed")
            return None, None

        token = _get_cli_token_for_openai(settings.kusto_tenant_id)
        if not token:
            print("  [AI Warning] Could not get Azure CLI token for Cognitive Services")
            return None, None

        client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            azure_ad_token=token,
            api_version=settings.azure_openai_api_version,
        )
        return client, settings.azure_openai_deployment

    # ── Option 2: GitHub Models with PAT ──
    if settings.github_token and not settings.github_token.startswith("ghp_your"):
        try:
            from openai import OpenAI
        except ImportError:
            return None, None

        client = OpenAI(
            base_url=settings.ai_base_url,
            api_key=settings.github_token,
        )
        return client, settings.ai_model

    return None, None


def _call_ai(client, model: str, system_prompt: str, user_prompt: str, max_tokens: int = 1000) -> str:
    """Make a single AI call. Returns the response text or empty string on failure."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,  # Low temperature for consistent analysis
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [AI Warning] API call failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────
# 1. Pattern Detection: Scan accounts for test/service/anomaly
# ─────────────────────────────────────────────────────────────

PATTERN_DETECTION_SYSTEM = """You are an identity governance analyst. You analyze lists of user accounts 
from third-party applications and identify accounts that are likely NOT real human users.

Categories to detect:
- **test_account**: Accounts created for testing (names like "test", "demo", "sandbox", "qa")
- **service_account**: Machine/integration accounts (names like "bot", "integration", "api", "sync", "admin")
- **shared_account**: Shared/generic accounts (names like "shared", "generic", "team", "group")
- **anomaly**: Accounts with suspicious patterns (incomplete data, unusual naming)

For each flagged account, provide:
- account_id: The account ID
- flags: List of categories that apply
- confidence: 0.0-1.0 how confident you are
- reason: Brief explanation

Respond ONLY with a JSON array. If no accounts are flagged, return [].
Do NOT include any markdown formatting or code fences."""


def detect_patterns(sf_accounts: list[SalesforceAccount]) -> dict[str, dict]:
    """
    Use AI to scan Salesforce accounts for non-human patterns.
    Returns a dict of account_id → {flags, confidence, reason}.
    """
    client, model = _get_ai_client()
    if not client:
        # Fallback: simple rule-based detection
        return _detect_patterns_fallback(sf_accounts)

    # Build account summary for the AI
    account_summaries = []
    for sf in sf_accounts:
        account_summaries.append({
            "account_id": sf.account_id,
            "display_name": sf.display_name,
            "email": sf.email,
            "department": sf.department,
            "title": sf.title,
            "is_active": sf.is_active,
            "has_phone": bool(sf.phone),
            "has_employee_id": bool(sf.employee_id),
        })

    # Process in batches of 50 to stay within token limits
    all_flags: dict[str, dict] = {}
    batch_size = 50

    for i in range(0, len(account_summaries), batch_size):
        batch = account_summaries[i:i + batch_size]
        user_prompt = (
            f"Analyze these {len(batch)} accounts from a Salesforce import. "
            f"Identify any test accounts, service accounts, shared accounts, or anomalies:\n\n"
            f"{json.dumps(batch, indent=2)}"
        )

        response = _call_ai(client, model, PATTERN_DETECTION_SYSTEM, user_prompt, max_tokens=2000)
        if response:
            try:
                flagged = json.loads(response)
                for item in flagged:
                    all_flags[item["account_id"]] = {
                        "flags": item.get("flags", []),
                        "confidence": item.get("confidence", 0.5),
                        "reason": item.get("reason", ""),
                    }
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  [AI Warning] Failed to parse pattern detection response: {e}")

    print(f"[Tier 3 - AI Pattern Detection] Flagged {len(all_flags)} accounts")
    return all_flags


def _detect_patterns_fallback(sf_accounts: list[SalesforceAccount]) -> dict[str, dict]:
    """
    Rule-based fallback for pattern detection when AI is unavailable.
    Uses simple keyword matching.
    """
    # Use word-boundary patterns to avoid false positives (e.g., "developer" matching "dev")
    import re
    test_patterns = [r"\btest\b", r"\bdemo\b", r"\bsandbox\b", r"\bqa\b", r"\bstaging\b"]
    service_patterns = [r"\bbot\b", r"\bintegration\b", r"\bapi\b", r"\bsync\b", r"\badmin\b", r"\bsystem\b", r"\bservice\s*account\b", r"\bnoreply\b"]
    shared_patterns = [r"\bshared\b", r"\bgeneric\b", r"\bteam\b", r"\bgroup\b", r"\bcommon\b", r"\bportal\b"]

    flags: dict[str, dict] = {}

    for sf in sf_accounts:
        name_lower = sf.display_name.lower()
        email_lower = sf.email.lower()
        # Only check name + email for test/service detection, not job title (too many false positives)
        combined = f"{name_lower} {email_lower}"

        detected_flags = []
        reasons = []

        for pattern in test_patterns:
            if re.search(pattern, combined):
                detected_flags.append("test_account")
                reasons.append(f"Matches pattern '{pattern}'")
                break

        for pattern in service_patterns:
            if re.search(pattern, combined):
                detected_flags.append("service_account")
                reasons.append(f"Matches pattern '{pattern}'")
                break

        for pattern in shared_patterns:
            if re.search(pattern, combined):
                detected_flags.append("shared_account")
                reasons.append(f"Matches pattern '{pattern}'")
                break

        # Anomaly: no phone + no employee ID + inactive
        if not sf.phone and not sf.employee_id and not sf.is_active:
            detected_flags.append("anomaly")
            reasons.append("Missing phone, employee ID, and inactive")

        if detected_flags:
            flags[sf.account_id] = {
                "flags": detected_flags,
                "confidence": 0.7,  # Rule-based confidence
                "reason": "; ".join(reasons),
            }

    print(f"[Tier 3 - Pattern Detection (fallback)] Flagged {len(flags)} accounts")
    return flags


# ─────────────────────────────────────────────────────────────
# 2. Semantic Match Reasoning: Evaluate borderline matches
# ─────────────────────────────────────────────────────────────

MATCH_REASONING_SYSTEM = """You are an identity matching expert. You are given a user account from Salesforce 
and a candidate match from Microsoft Entra ID, along with their fuzzy match scores.

Your job is to:
1. Evaluate whether this is likely the same person
2. Provide a confidence adjustment (-30 to +30 points) to the fuzzy score
3. Explain your reasoning in 1-2 sentences for the admin

Consider:
- Do the names look like the same person (accounting for nicknames, initials, typos)?
- Do the other attributes (department, title, phone) corroborate the match?
- Are there any red flags (completely different departments, suspicious patterns)?

Respond ONLY with a JSON object:
{
  "adjustment": <integer -30 to +30>,
  "reasoning": "<1-2 sentence explanation>",
  "is_likely_match": <true/false>
}
Do NOT include any markdown formatting or code fences."""


def evaluate_match_with_ai(
    sf: SalesforceAccount,
    entra: EntraUser,
    fuzzy_score: float,
    score_details: dict,
) -> tuple[float, str]:
    """
    Use AI to evaluate a borderline fuzzy match and adjust the confidence.

    Returns:
        - adjusted_score: The fuzzy score + AI adjustment
        - reasoning: Human-readable explanation
    """
    client, model = _get_ai_client()
    if not client:
        return fuzzy_score, "AI evaluation unavailable"

    user_prompt = f"""Salesforce Account:
- Name: {sf.display_name} ({sf.first_name} {sf.last_name})
- Email: {sf.email}
- Phone: {sf.phone}
- Department: {sf.department}
- Title: {sf.title}
- Employee ID: {sf.employee_id or 'N/A'}

Entra User Candidate:
- Name: {entra.display_name} ({entra.given_name} {entra.surname})
- UPN: {entra.user_principal_name}
- Email: {entra.mail}
- Phone: {entra.phone}, Mobile: {entra.mobile_phone}
- Department: {entra.department}
- Title: {entra.job_title}
- Employee ID: {entra.employee_id or 'N/A'}

Current Fuzzy Match Score: {fuzzy_score}/100
Score Breakdown: {json.dumps(score_details)}"""

    response = _call_ai(client, model, MATCH_REASONING_SYSTEM, user_prompt, max_tokens=300)
    if response:
        try:
            result = json.loads(response)
            adjustment = max(-30, min(30, int(result.get("adjustment", 0))))
            reasoning = result.get("reasoning", "")
            adjusted = max(0, min(99, fuzzy_score + adjustment))
            return adjusted, reasoning
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    return fuzzy_score, "AI evaluation failed to parse"


# ─────────────────────────────────────────────────────────────
# 3. Batch AI Enhancement: Apply AI to all fuzzy match results
# ─────────────────────────────────────────────────────────────

def enhance_matches_with_ai(
    fuzzy_matches: list[MatchResult],
    sf_accounts: list[SalesforceAccount],
    entra_users: list[EntraUser],
    pattern_flags: dict[str, dict],
) -> list[MatchResult]:
    """
    Enhance fuzzy match results with AI reasoning and pattern flags.
    Only calls AI for Medium and Low confidence matches (to save API calls).
    """
    # Build lookup maps
    sf_map = {sf.account_id: sf for sf in sf_accounts}
    entra_map = {e.object_id: e for e in entra_users}

    enhanced = []
    ai_evaluated = 0

    for match in fuzzy_matches:
        # Apply pattern flags
        if match.salesforce_account_id in pattern_flags:
            flags = pattern_flags[match.salesforce_account_id]
            match.ai_flags = json.dumps(flags)

        # Only run AI reasoning on Medium/Low matches (High matches are already confident)
        if match.match_category in ("Medium", "Low") and match.entra_object_id:
            sf = sf_map.get(match.salesforce_account_id)
            entra = entra_map.get(match.entra_object_id)

            if sf and entra:
                score_details = {
                    "name": match.name_match_score,
                    "phone": match.phone_match_score,
                    "email_local": match.email_match_score,
                    "department": match.department_match_score,
                    "title": match.title_match_score,
                }

                adjusted_score, reasoning = evaluate_match_with_ai(
                    sf, entra, match.composite_score, score_details
                )

                match.composite_score = adjusted_score
                match.ai_reasoning_summary = reasoning
                ai_evaluated += 1

                # Re-classify based on adjusted score
                settings = get_settings()
                if adjusted_score >= settings.match_threshold_high:
                    match.match_category = "High"
                elif adjusted_score >= settings.match_threshold_medium:
                    match.match_category = "Medium"
                elif adjusted_score >= settings.match_threshold_low:
                    match.match_category = "Low"
                else:
                    match.match_category = "None"

        enhanced.append(match)

    print(f"[Tier 3 - AI Enhancement] Evaluated {ai_evaluated} borderline matches with AI")
    return enhanced


def create_unmatched_results(
    unmatched_sf: list[SalesforceAccount],
    pattern_flags: dict[str, dict],
) -> list[MatchResult]:
    """
    Create MatchResult entries for accounts that had no match at all.
    These still get AI pattern flags.
    """
    results = []
    for sf in unmatched_sf:
        flags = pattern_flags.get(sf.account_id, {})
        results.append(MatchResult(
            salesforce_account_id=sf.account_id,
            salesforce_display_name=sf.display_name,
            salesforce_email=sf.email,
            match_category="None",
            composite_score=0.0,
            ai_flags=json.dumps(flags) if flags else "{}",
            ai_reasoning_summary=flags.get("reason", "No match found") if flags else "No match found",
        ))
    return results
