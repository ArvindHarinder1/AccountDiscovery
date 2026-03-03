"""
Unit tests for Tier 1: Deterministic Matching
Tests exact email, UPN, and employee ID matching with various edge cases.
"""

import pytest
from src.models import SalesforceAccount, EntraUser, MatchResult
from src.tier1_deterministic import (
    normalize_email,
    extract_email_local_part,
    normalize_employee_id,
    match_exact_email,
    match_email_local_part,
    match_employee_id,
    run_deterministic_matching,
)


# ── Helper factories ──

def make_sf(
    account_id="SF-001",
    email="alice@contoso.com",
    username="alice@company.salesforce.com",
    display_name="Alice Johnson",
    first_name="Alice",
    last_name="Johnson",
    phone="",
    department="",
    title="",
    employee_id="",
    is_active=True,
) -> SalesforceAccount:
    return SalesforceAccount(
        account_id=account_id, email=email, username=username,
        display_name=display_name, first_name=first_name, last_name=last_name,
        phone=phone, department=department, title=title,
        employee_id=employee_id, is_active=is_active,
    )


def make_entra(
    object_id="ENTRA-001",
    upn="alice.johnson@contoso.com",
    mail="alice.johnson@contoso.com",
    display_name="Alice Johnson",
    given_name="Alice",
    surname="Johnson",
    phone="",
    mobile_phone="",
    department="",
    job_title="",
    employee_id="",
    account_enabled=True,
) -> EntraUser:
    return EntraUser(
        object_id=object_id, user_principal_name=upn, mail=mail,
        display_name=display_name, given_name=given_name, surname=surname,
        phone=phone, mobile_phone=mobile_phone, department=department,
        job_title=job_title, employee_id=employee_id, account_enabled=account_enabled,
    )


# ── normalize_email ──

class TestNormalizeEmail:
    def test_basic(self):
        assert normalize_email("Alice@Contoso.com") == "alice@contoso.com"

    def test_whitespace(self):
        assert normalize_email("  alice@contoso.com  ") == "alice@contoso.com"

    def test_empty(self):
        assert normalize_email("") == ""
        assert normalize_email(None) == ""

    def test_already_lowercase(self):
        assert normalize_email("alice@contoso.com") == "alice@contoso.com"


# ── extract_email_local_part ──

class TestExtractEmailLocalPart:
    def test_basic(self):
        assert extract_email_local_part("alice.johnson@contoso.com") == "alice.johnson"

    def test_no_at(self):
        assert extract_email_local_part("no-at-sign") == ""

    def test_empty(self):
        assert extract_email_local_part("") == ""
        assert extract_email_local_part(None) == ""

    def test_case_insensitive(self):
        assert extract_email_local_part("Alice.Johnson@Contoso.com") == "alice.johnson"


# ── normalize_employee_id ──

class TestNormalizeEmployeeId:
    def test_basic(self):
        assert normalize_employee_id("emp001") == "EMP001"

    def test_whitespace(self):
        assert normalize_employee_id("  EMP001  ") == "EMP001"

    def test_empty(self):
        assert normalize_employee_id("") == ""
        assert normalize_employee_id(None) == ""


# ── match_exact_email ──

class TestMatchExactEmail:
    def test_exact_mail_match(self):
        sf = make_sf(email="alice@contoso.com")
        entra = make_entra(mail="alice@contoso.com")
        assert match_exact_email(sf, entra) is True

    def test_exact_upn_match(self):
        sf = make_sf(email="alice@contoso.com")
        entra = make_entra(upn="alice@contoso.com", mail="")
        assert match_exact_email(sf, entra) is True

    def test_case_insensitive(self):
        sf = make_sf(email="Alice@Contoso.COM")
        entra = make_entra(mail="alice@contoso.com")
        assert match_exact_email(sf, entra) is True

    def test_no_match_different_domain(self):
        sf = make_sf(email="alice@salesforce.com")
        entra = make_entra(mail="alice@contoso.com")
        assert match_exact_email(sf, entra) is False

    def test_empty_sf_email(self):
        sf = make_sf(email="")
        entra = make_entra(mail="alice@contoso.com")
        assert match_exact_email(sf, entra) is False


# ── match_employee_id ──

class TestMatchEmployeeId:
    def test_exact(self):
        sf = make_sf(employee_id="EMP001")
        entra = make_entra(employee_id="EMP001")
        assert match_employee_id(sf, entra) is True

    def test_case_insensitive(self):
        sf = make_sf(employee_id="emp001")
        entra = make_entra(employee_id="EMP001")
        assert match_employee_id(sf, entra) is True

    def test_no_match(self):
        sf = make_sf(employee_id="EMP001")
        entra = make_entra(employee_id="EMP002")
        assert match_employee_id(sf, entra) is False

    def test_empty_ids(self):
        sf = make_sf(employee_id="")
        entra = make_entra(employee_id="EMP001")
        assert match_employee_id(sf, entra) is False


# ── run_deterministic_matching (integration) ──

class TestRunDeterministicMatching:
    def test_exact_email_match(self):
        sf_list = [make_sf(account_id="SF-1", email="alice@contoso.com")]
        entra_list = [make_entra(object_id="E-1", mail="alice@contoso.com")]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 1
        assert len(unmatched) == 0
        assert matched[0].entra_object_id == "E-1"
        assert matched[0].match_category == "Exact"
        assert matched[0].composite_score == 100.0

    def test_employee_id_match(self):
        sf_list = [make_sf(account_id="SF-1", email="alice@other.com", employee_id="EMP001")]
        entra_list = [make_entra(object_id="E-1", mail="bob@contoso.com", employee_id="EMP001")]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 1
        assert "Employee ID" in matched[0].ai_reasoning_summary

    def test_no_match(self):
        sf_list = [make_sf(account_id="SF-1", email="alice@salesforce.com", employee_id="")]
        entra_list = [make_entra(object_id="E-1", mail="bob@contoso.com")]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 0
        assert len(unmatched) == 1

    def test_prevents_duplicate_entra_match(self):
        """Two SF accounts should not match the same Entra user."""
        sf_list = [
            make_sf(account_id="SF-1", email="alice@contoso.com"),
            make_sf(account_id="SF-2", email="alice@contoso.com"),
        ]
        entra_list = [make_entra(object_id="E-1", mail="alice@contoso.com")]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 1  # Only one should match
        assert len(unmatched) == 1

    def test_email_priority_over_employee_id(self):
        """Email match should be preferred over employee ID match."""
        sf_list = [make_sf(account_id="SF-1", email="alice@contoso.com", employee_id="EMP001")]
        entra_list = [
            make_entra(object_id="E-1", mail="alice@contoso.com", employee_id="EMP999"),
            make_entra(object_id="E-2", mail="bob@contoso.com", employee_id="EMP001"),
        ]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 1
        assert matched[0].entra_object_id == "E-1"  # Email match wins

    def test_objectid_as_employee_id(self):
        """
        Real-world edge case: SF EmployeeId field sometimes contains Entra ObjectIds.
        This should still match via employee ID normalization.
        """
        oid = "ec87c72d-5f1f-456d-8a81-88572ea24488"
        sf_list = [make_sf(account_id="SF-1", email="alice@other.com", employee_id=oid)]
        entra_list = [make_entra(object_id="E-1", mail="bob@contoso.com", employee_id=oid)]
        matched, unmatched = run_deterministic_matching(sf_list, entra_list)
        assert len(matched) == 1
