"""
Account Discovery Prototype — Tier 1: Deterministic Matching
Exact-match on unique identifiers: email, UPN, employee ID.
If any of these match, the account is definitively matched (score = 100).
"""

import re
from src.models import SalesforceAccount, EntraUser, MatchResult


def normalize_email(email: str) -> str:
    """
    Normalize an email address for comparison:
    - Lowercase
    - Strip whitespace
    - Extract the local part (before @) for cross-domain comparison
    """
    if not email:
        return ""
    return email.strip().lower()


def extract_email_local_part(email: str) -> str:
    """Extract the local part of an email (before the @ sign)."""
    if not email or "@" not in email:
        return ""
    return email.strip().lower().split("@")[0]


def normalize_employee_id(emp_id: str) -> str:
    """Normalize employee ID: strip whitespace, uppercase."""
    if not emp_id:
        return ""
    return emp_id.strip().upper()


def match_exact_email(sf: SalesforceAccount, entra: EntraUser) -> bool:
    """Check if the Salesforce email exactly matches Entra mail or UPN."""
    sf_email = normalize_email(sf.email)
    if not sf_email:
        return False

    entra_mail = normalize_email(entra.mail)
    entra_upn = normalize_email(entra.user_principal_name)

    return sf_email == entra_mail or sf_email == entra_upn


def match_email_local_part(sf: SalesforceAccount, entra: EntraUser) -> bool:
    """
    Check if the local part of the Salesforce email/username matches
    the local part of any Entra email/UPN.
    This handles cross-domain matching (e.g., alice.johnson@salesforce.com ↔ alice.johnson@contoso.com).
    """
    sf_locals = set()
    for field in [sf.email, sf.username]:
        local = extract_email_local_part(field)
        if local:
            sf_locals.add(local)

    entra_locals = set()
    for field in [entra.mail, entra.user_principal_name]:
        local = extract_email_local_part(field)
        if local:
            entra_locals.add(local)

    return bool(sf_locals & entra_locals)


def match_employee_id(sf: SalesforceAccount, entra: EntraUser) -> bool:
    """Check if employee IDs match exactly."""
    sf_eid = normalize_employee_id(sf.employee_id)
    entra_eid = normalize_employee_id(entra.employee_id)

    if not sf_eid or not entra_eid:
        return False

    return sf_eid == entra_eid


def run_deterministic_matching(
    sf_accounts: list[SalesforceAccount],
    entra_users: list[EntraUser],
) -> tuple[list[MatchResult], list[SalesforceAccount]]:
    """
    Run Tier 1 deterministic matching.

    Returns:
        - matched: List of MatchResults with score=100 (exact matches)
        - unmatched: List of SalesforceAccounts that had no exact match
    """
    matched: list[MatchResult] = []
    unmatched: list[SalesforceAccount] = []

    # Build lookup indices for fast matching
    email_index: dict[str, EntraUser] = {}
    local_part_index: dict[str, EntraUser] = {}
    emp_id_index: dict[str, EntraUser] = {}

    for entra in entra_users:
        # Index by full email
        for field in [entra.mail, entra.user_principal_name]:
            normalized = normalize_email(field)
            if normalized:
                email_index[normalized] = entra

        # Index by email local part
        for field in [entra.mail, entra.user_principal_name]:
            local = extract_email_local_part(field)
            if local:
                local_part_index[local] = entra

        # Index by employee ID
        eid = normalize_employee_id(entra.employee_id)
        if eid:
            emp_id_index[eid] = entra

    matched_entra_ids: set[str] = set()  # Prevent duplicate matches

    for sf in sf_accounts:
        best_match: EntraUser | None = None
        match_reason = ""

        # Priority 1: Exact full email match (SF email == Entra mail or UPN)
        sf_email = normalize_email(sf.email)
        if sf_email and sf_email in email_index:
            candidate = email_index[sf_email]
            if candidate.object_id not in matched_entra_ids:
                best_match = candidate
                match_reason = "Exact email match"

        # Priority 2: Employee ID match (strong unique identifier)
        if not best_match:
            sf_eid = normalize_employee_id(sf.employee_id)
            if sf_eid and sf_eid in emp_id_index:
                candidate = emp_id_index[sf_eid]
                if candidate.object_id not in matched_entra_ids:
                    best_match = candidate
                    match_reason = "Employee ID match"

        # Note: Email local-part cross-domain matching is handled in Tier 2
        # as a high-weight fuzzy signal (not deterministic enough for Tier 1)

        if best_match:
            matched_entra_ids.add(best_match.object_id)
            matched.append(MatchResult(
                salesforce_account_id=sf.account_id,
                salesforce_display_name=sf.display_name,
                salesforce_email=sf.email,
                entra_object_id=best_match.object_id,
                entra_display_name=best_match.display_name,
                entra_upn=best_match.user_principal_name,
                match_category="Exact",
                composite_score=100.0,
                email_match_score=100.0 if "email" in match_reason.lower() else 0.0,
                name_match_score=0.0,  # Not evaluated for exact matches
                phone_match_score=0.0,
                department_match_score=0.0,
                title_match_score=0.0,
                employee_id_match="Employee ID" in match_reason,
                ai_flags="{}",
                ai_reasoning_summary=match_reason,
            ))
        else:
            unmatched.append(sf)

    print(f"\n[Tier 1 - Deterministic] Found {len(matched)} exact matches, {len(unmatched)} unmatched")
    return matched, unmatched
