"""
Unit tests for Tier 2: Fuzzy Matching
Tests individual scoring functions and the composite fuzzy matcher.
Includes edge cases for sparse data, short names, nicknames, and diacritics.
"""

import pytest
from src.models import SalesforceAccount, EntraUser
from src.tier2_fuzzy import (
    normalize_phone,
    score_name_similarity,
    score_name_parts,
    score_phone_match,
    score_email_local_part,
    score_department,
    score_title,
    compute_composite_score,
    find_fuzzy_matches,
    run_fuzzy_matching,
)


# ── Helper factories ──

def make_sf(**kwargs) -> SalesforceAccount:
    defaults = dict(
        account_id="SF-001", email="alice@company.salesforce.com",
        username="alice@company.salesforce.com", display_name="Alice Johnson",
        first_name="Alice", last_name="Johnson", phone="",
        department="", title="", employee_id="", is_active=True,
    )
    defaults.update(kwargs)
    return SalesforceAccount(**defaults)


def make_entra(**kwargs) -> EntraUser:
    defaults = dict(
        object_id="ENTRA-001", user_principal_name="alice.johnson@contoso.com",
        mail="alice.johnson@contoso.com", display_name="Alice Johnson",
        given_name="Alice", surname="Johnson", phone="", mobile_phone="",
        department="", job_title="", employee_id="", account_enabled=True,
    )
    defaults.update(kwargs)
    return EntraUser(**defaults)


# ── normalize_phone ──

class TestNormalizePhone:
    def test_us_with_country_code(self):
        assert normalize_phone("+1-425-555-0101") == "4255550101"

    def test_parentheses_format(self):
        assert normalize_phone("(425) 555-0101") == "4255550101"

    def test_digits_only(self):
        assert normalize_phone("4255550101") == "4255550101"

    def test_with_11_digit_us(self):
        assert normalize_phone("14255550101") == "4255550101"

    def test_empty(self):
        assert normalize_phone("") == ""

    def test_international(self):
        # Non-US 11-digit number should keep all digits
        assert normalize_phone("+44-20-7946-0958") == "442079460958"


# ── score_name_similarity ──

class TestScoreNameSimilarity:
    def test_identical(self):
        assert score_name_similarity("Alice Johnson", "Alice Johnson") == 1.0

    def test_case_insensitive(self):
        assert score_name_similarity("alice johnson", "ALICE JOHNSON") == 1.0

    def test_similar(self):
        score = score_name_similarity("Alice Johnson", "Alice Jonhson")  # typo
        assert score > 0.9

    def test_very_different(self):
        score = score_name_similarity("Alice Johnson", "Zach King")
        # Jaro-Winkler gives moderate scores to same-length strings;
        # the composite weighting handles disambiguation.
        assert score < 0.7

    def test_empty(self):
        assert score_name_similarity("", "Alice") == 0.0
        assert score_name_similarity("Alice", "") == 0.0

    def test_short_names_high_false_positive_risk(self):
        """Short names like 'Lee Gu' may score dangerously high against other short names."""
        score = score_name_similarity("Lee Gu", "Lee Lu")
        # This documents the risk — score is likely > 0.8 for 2 very different people
        assert score > 0.7, "Documenting: short names inflate Jaro-Winkler scores"


# ── score_name_parts ──

class TestScoreNameParts:
    def test_exact_match(self):
        score = score_name_parts("Alice", "Johnson", "Alice", "Johnson")
        assert score == 1.0

    def test_reversed_names(self):
        """Some cultures put surname first."""
        score = score_name_parts("Johnson", "Alice", "Alice", "Johnson")
        assert score > 0.8

    def test_initial_match(self):
        """'A.' should partially match 'Alice'."""
        score = score_name_parts("A.", "Johnson", "Alice", "Johnson")
        assert score > 0.5

    def test_nickname_now_handled(self):
        """Nickname support: Bob ↔ Robert should score high via nickname dictionary."""
        score = score_name_parts("Bob", "Smith", "Robert", "Smith")
        assert score >= 0.85, f"Nickname Bob→Robert should score high, got {score}"

    def test_empty(self):
        score = score_name_parts("", "", "Alice", "Johnson")
        assert score == 0.0


# ── score_phone_match ──

class TestScorePhoneMatch:
    def test_exact_after_normalization(self):
        assert score_phone_match("+1-425-555-0101", "(425) 555-0101") == 1.0

    def test_last_7_digits(self):
        assert score_phone_match("5550101", "4255550101") == 0.8

    def test_mobile_fallback(self):
        assert score_phone_match("+1-425-555-0101", "", "+1-425-555-0101") == 1.0

    def test_no_match(self):
        assert score_phone_match("+1-425-555-0101", "+1-425-555-9999") == 0.0

    def test_empty(self):
        assert score_phone_match("", "4255550101") == 0.0


# ── score_email_local_part ──

class TestScoreEmailLocalPart:
    def test_identical(self):
        assert score_email_local_part("alice@contoso.com", "alice@contoso.com") == 1.0

    def test_cross_domain(self):
        score = score_email_local_part("alice.johnson@salesforce.com", "alice.johnson@contoso.com")
        assert score == 1.0

    def test_typo(self):
        score = score_email_local_part("alice.jonhson@a.com", "alice.johnson@b.com")
        assert score > 0.85

    def test_very_different(self):
        score = score_email_local_part("alice@a.com", "zach@b.com")
        assert score < 0.5

    def test_empty(self):
        assert score_email_local_part("", "alice@contoso.com") == 0.0

    def test_short_local_parts_false_positive(self):
        """Short local parts like 'leeg' could match 'leeh' — high false positive risk."""
        score = score_email_local_part("leeg@a.com", "leeh@b.com")
        assert score > 0.7, "Short local parts inflate Levenshtein ratio (known risk)"


# ── score_department ──

class TestScoreDepartment:
    def test_identical(self):
        assert score_department("Engineering", "Engineering") == 1.0

    def test_abbreviation(self):
        assert score_department("hr", "human resources") == 0.95

    def test_similar(self):
        score = score_department("Engineering", "Software Engineering")
        assert score > 0.7

    def test_empty(self):
        assert score_department("", "Engineering") == 0.0


# ── score_title ──

class TestScoreTitle:
    def test_identical(self):
        assert score_title("Software Engineer", "Software Engineer") == 1.0

    def test_similar(self):
        score = score_title("Software Engineer", "Senior Software Engineer")
        assert score > 0.7

    def test_empty(self):
        assert score_title("", "Engineer") == 0.0


# ── compute_composite_score ──

class TestCompositeScore:
    def test_all_perfect(self):
        score = compute_composite_score(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert score == 100.0

    def test_all_zero(self):
        score = compute_composite_score(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_name_only_perfect(self):
        """With adaptive weighting, name-only signals get boosted (capped at 1.5x)."""
        score = compute_composite_score(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert 60 < score < 70  # 45 base * 1.5 cap = 67.5

    def test_name_only_non_adaptive(self):
        """Without adaptive weighting, name-only maxes at ~45."""
        score = compute_composite_score(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, adaptive=False)
        assert 40 < score < 50


# ── Sparse data scenario ──

class TestSparseDataScoring:
    """
    Real customer data often has NO phone, NO department, NO title, NO employee ID.
    This tests that scoring still works reasonably.
    """
    def test_name_and_email_only(self):
        """Same person, but only name and email are populated."""
        sf = make_sf(
            display_name="Isaiah Langer", first_name="Isaiah", last_name="Langer",
            email="isaiahl@m365x42521811.onmicrosoft.com",
            username="IsaiahL@M365x42521811.OnMicrosoft.com",
        )
        entra = make_entra(
            display_name="Isaiah Langer", given_name="Isaiah", surname="Langer",
            user_principal_name="isaiahl@m365x42521811.onmicrosoft.com",
            mail="isaiahl@m365x42521811.onmicrosoft.com",
        )
        matches = find_fuzzy_matches(sf, [entra], set(), top_n=1)
        assert len(matches) == 1
        _, score, _ = matches[0]
        # Should score high despite sparse data
        assert score >= 50, f"Sparse data score {score} too low for obvious match"

    def test_sparse_wrong_person(self):
        """Different person, sparse data — should NOT score high."""
        sf = make_sf(
            display_name="Isaiah Langer", first_name="Isaiah", last_name="Langer",
            email="isaiahl@company.com", username="",
        )
        entra = make_entra(
            display_name="Megan Bowen", given_name="Megan", surname="Bowen",
            user_principal_name="meganb@contoso.com", mail="meganb@contoso.com",
        )
        matches = find_fuzzy_matches(sf, [entra], set(), top_n=1)
        if matches:
            _, score, _ = matches[0]
            # With adaptive weighting the score is slightly higher, but still
            # well below the Medium threshold (50)
            assert score < 50, f"Wrong person score {score} crossed Medium threshold"


# ── Disambiguation ──

class TestDisambiguation:
    def test_two_john_smiths(self):
        """When two SF accounts have the same name, they should match different Entra users."""
        sf_list = [
            make_sf(account_id="SF-1", display_name="John Smith", first_name="John",
                    last_name="Smith", email="john.smith1@company.com", department="Engineering"),
            make_sf(account_id="SF-2", display_name="John Smith", first_name="John",
                    last_name="Smith", email="john.smith2@company.com", department="Sales"),
        ]
        entra_list = [
            make_entra(object_id="E-1", display_name="John Smith", given_name="John",
                       surname="Smith", user_principal_name="john.smith@contoso.com",
                       mail="john.smith@contoso.com", department="Engineering"),
            make_entra(object_id="E-2", display_name="John Smith", given_name="John",
                       surname="Smith", user_principal_name="jsmith@contoso.com",
                       mail="jsmith@contoso.com", department="Sales"),
        ]
        matched, unmatched = run_fuzzy_matching(sf_list, entra_list, set())
        matched_entra_ids = {m.entra_object_id for m in matched}
        # Both should match, to DIFFERENT Entra users
        assert len(matched) == 2
        assert len(matched_entra_ids) == 2, "Same Entra user matched twice!"


# ── Edge cases ──

class TestEdgeCases:
    def test_hyphenated_last_name(self):
        score = score_name_similarity("Sarah Johnson-Smith", "Sarah Smith")
        # Should get some credit for partial last name match
        assert score > 0.5

    def test_diacritics(self):
        """José should match Jose — currently does NOT handle this well."""
        score = score_name_similarity("José Garcia", "Jose Garcia")
        # Jaro-Winkler treats é and e as different chars
        # This documents the gap
        assert score > 0.9, "Diacritics cause score drop (known gap if this fails)"

    def test_very_long_name(self):
        score = score_name_similarity(
            "Mohammad Abdul Rahman Al-Rashidi",
            "Mohammed A. Al Rashidi"
        )
        assert score > 0.5
