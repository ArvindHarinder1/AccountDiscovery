"""
Ground-Truth Validation & Metrics Framework
════════════════════════════════════════════
Runs the full matching pipeline against synthetic data with KNOWN expected
outcomes, then computes precision, recall, F1, and a confusion matrix.

Usage:
    python -m tests.test_ground_truth          # Run validation
    python -m tests.test_ground_truth --sweep   # Sweep thresholds for P/R curves
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import SalesforceAccount, EntraUser, MatchResult
from src.tier1_deterministic import run_deterministic_matching
from src.tier2_fuzzy import run_fuzzy_matching


# ═══════════════════════════════════════════════════════════════
# 1. Ground-Truth Dataset — Known people with known match types
# ═══════════════════════════════════════════════════════════════

@dataclass
class GroundTruthCase:
    """A test case with a known expected outcome."""
    sf: SalesforceAccount
    entra: EntraUser | None  # None = SF-only, should NOT match
    expected_category: str   # "Exact", "High", "Medium", "Low", "None"
    description: str


def _build_ground_truth() -> list[GroundTruthCase]:
    """Generate test cases covering every matching scenario."""
    cases = []

    # ── 1. Exact email match ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-01", email="alice.johnson@contoso.com",
            username="alice.johnson@salesforce.com", display_name="Alice Johnson",
            first_name="Alice", last_name="Johnson", phone="+1-425-555-0101",
            department="Engineering", title="Software Engineer",
            employee_id="EMP001", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-01", user_principal_name="alice.johnson@contoso.com",
            mail="alice.johnson@contoso.com", display_name="Alice Johnson",
            given_name="Alice", surname="Johnson", phone="+1-425-555-0101",
            mobile_phone="+1-206-555-0101", department="Engineering",
            job_title="Software Engineer", employee_id="EMP001",
            account_enabled=True,
        ),
        expected_category="Exact",
        description="Perfect match — same email, name, phone, employee ID",
    ))

    # ── 2. Employee ID match (different email/domain) ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-02", email="bob.smith@salesforce.com",
            username="bob.smith@salesforce.com", display_name="Bob Smith",
            first_name="Bob", last_name="Smith", phone="+1-425-555-0102",
            department="Sales", title="Account Executive",
            employee_id="EMP002", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-02", user_principal_name="bob.smith@contoso.com",
            mail="bob.smith@contoso.com", display_name="Bob Smith",
            given_name="Bob", surname="Smith", phone="+1-425-555-0102",
            mobile_phone="", department="Sales", job_title="Account Executive",
            employee_id="EMP002", account_enabled=True,
        ),
        expected_category="Exact",
        description="Employee ID match with different email domains",
    ))

    # ── 3. Cross-domain email local-part match (High fuzzy) ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-03", email="carol.williams@salesforce.com",
            username="carol.williams@salesforce.com", display_name="Carol Williams",
            first_name="Carol", last_name="Williams", phone="+1-425-555-0103",
            department="Marketing", title="Marketing Manager",
            employee_id="", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-03", user_principal_name="carol.williams@contoso.com",
            mail="carol.williams@contoso.com", display_name="Carol Williams",
            given_name="Carol", surname="Williams", phone="+1-425-555-0103",
            mobile_phone="", department="Marketing", job_title="Marketing Manager",
            employee_id="", account_enabled=True,
        ),
        expected_category="High",
        description="Same name, same local-part, same phone — different domain",
    ))

    # ── 4. Name typo (fuzzy) ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-04", email="david.brown@salesforce.com",
            username="david.brown@salesforce.com", display_name="Davide Brown",
            first_name="Davide", last_name="Brown", phone="+1 425 555 0104",
            department="Engineering", title="Senior Developer",
            employee_id="EMP004", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-04", user_principal_name="david.brown@contoso.com",
            mail="david.brown@contoso.com", display_name="David Brown",
            given_name="David", surname="Brown", phone="+1-425-555-0104",
            mobile_phone="", department="Engineering", job_title="Senior Developer",
            employee_id="EMP004", account_enabled=True,
        ),
        expected_category="Exact",  # Employee ID should catch this at Tier 1
        description="Name typo (Davide vs David) but employee ID matches",
    ))

    # ── 5. Nickname mismatch (currently a gap) ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-05", email="bob.jones@salesforce.com",
            username="bob.jones@salesforce.com", display_name="Bob Jones",
            first_name="Bob", last_name="Jones", phone="+1-425-555-0200",
            department="Engineering", title="Developer",
            employee_id="", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-05", user_principal_name="robert.jones@contoso.com",
            mail="robert.jones@contoso.com", display_name="Robert Jones",
            given_name="Robert", surname="Jones", phone="+1-425-555-0200",
            mobile_phone="", department="Engineering", job_title="Developer",
            employee_id="", account_enabled=True,
        ),
        expected_category="High",
        description="NICKNAME GAP — Bob=Robert, same phone+dept+title",
    ))

    # ── 6. Sparse data — only name and short email ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-06", email="isaiahl@m365x.onmicrosoft.com",
            username="IsaiahL@M365x.OnMicrosoft.com", display_name="Isaiah Langer",
            first_name="Isaiah", last_name="Langer", phone="", department="",
            title="", employee_id="", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-06", user_principal_name="isaiahl@m365x.onmicrosoft.com",
            mail="", display_name="Isaiah Langer", given_name="Isaiah",
            surname="Langer", phone="", mobile_phone="", department="",
            job_title="", employee_id="", account_enabled=True,
        ),
        expected_category="Exact",  # UPN should match
        description="Sparse data — only name + UPN match, everything else empty",
    ))

    # ── 7. SF-only test account (should be None) ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-07", email="test.user1@company.salesforce.com",
            username="test.user1@company.salesforce.com", display_name="Test User1",
            first_name="Test", last_name="User1", phone="", department="QA",
            title="Tester", employee_id="", is_active=False,
        ),
        entra=None,
        expected_category="None",
        description="Test account — should not match any real Entra user",
    ))

    # ── 8. Initial-only first name ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-08", email="f.miller@salesforce.com",
            username="f.miller@salesforce.com", display_name="F. Miller",
            first_name="F.", last_name="Miller", phone="4255550106",
            department="Finance", title="Financial Analyst",
            employee_id="EMP006", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-08", user_principal_name="frank.miller@contoso.com",
            mail="frank.miller@contoso.com", display_name="Frank Miller",
            given_name="Frank", surname="Miller", phone="+1-425-555-0106",
            mobile_phone="", department="Finance", job_title="Financial Analyst",
            employee_id="EMP006", account_enabled=True,
        ),
        expected_category="Exact",  # Employee ID match
        description="Initial-only name 'F. Miller' matches 'Frank Miller' via employee ID",
    ))

    # ── 9. Diacritics ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-09", email="jose.garcia@salesforce.com",
            username="jose.garcia@salesforce.com", display_name="José García",
            first_name="José", last_name="García", phone="+1-425-555-0301",
            department="Engineering", title="Developer",
            employee_id="", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-09", user_principal_name="jose.garcia@contoso.com",
            mail="jose.garcia@contoso.com", display_name="Jose Garcia",
            given_name="Jose", surname="Garcia", phone="+1-425-555-0301",
            mobile_phone="", department="Engineering", job_title="Developer",
            employee_id="", account_enabled=True,
        ),
        expected_category="High",
        description="DIACRITICS — José/García vs Jose/Garcia, same phone+dept",
    ))

    # ── 10. Hyphenated last name ──
    cases.append(GroundTruthCase(
        sf=SalesforceAccount(
            account_id="GT-10", email="sarah.js@salesforce.com",
            username="sarah.js@salesforce.com", display_name="Sarah Johnson-Smith",
            first_name="Sarah", last_name="Johnson-Smith", phone="+1-425-555-0302",
            department="Legal", title="Counsel",
            employee_id="", is_active=True,
        ),
        entra=EntraUser(
            object_id="E-10", user_principal_name="sarah.johnson-smith@contoso.com",
            mail="sarah.johnsonsmith@contoso.com", display_name="Sarah Johnson Smith",
            given_name="Sarah", surname="Johnson Smith", phone="+1-425-555-0302",
            mobile_phone="", department="Legal", job_title="Counsel",
            employee_id="", account_enabled=True,
        ),
        expected_category="High",
        description="Hyphenated vs space in last name",
    ))

    return cases


# ═══════════════════════════════════════════════════════════════
# 2. Metrics Computation
# ═══════════════════════════════════════════════════════════════

@dataclass
class MatchMetrics:
    true_positives: int = 0      # Correctly matched to the right person
    false_positives: int = 0     # Matched to the WRONG person
    false_negatives: int = 0     # Should have matched but didn't
    true_negatives: int = 0      # Correctly identified as no match
    wrong_category: int = 0      # Right person, wrong confidence tier

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def evaluate_pipeline(
    threshold_high: int = 80,
    threshold_medium: int = 50,
    threshold_low: int = 25,
    verbose: bool = True,
) -> MatchMetrics:
    """
    Run the matching pipeline on ground-truth data and compute metrics.
    """
    cases = _build_ground_truth()
    metrics = MatchMetrics()

    # Separate matchable and non-matchable cases
    sf_accounts = [c.sf for c in cases]
    entra_users = [c.entra for c in cases if c.entra is not None]
    expected_map = {}  # sf_account_id → (expected_entra_object_id, expected_category)
    for c in cases:
        expected_entra_id = c.entra.object_id if c.entra else None
        expected_map[c.sf.account_id] = (expected_entra_id, c.expected_category, c.description)

    # Run Tier 1
    exact_matches, unmatched_after_t1 = run_deterministic_matching(sf_accounts, entra_users)
    matched_entra_ids = {m.entra_object_id for m in exact_matches if m.entra_object_id}

    # Run Tier 2
    fuzzy_matches, still_unmatched = run_fuzzy_matching(
        unmatched_after_t1, entra_users, matched_entra_ids,
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        threshold_low=threshold_low,
    )

    # Build result map
    all_results: dict[str, MatchResult] = {}
    for m in exact_matches + fuzzy_matches:
        all_results[m.salesforce_account_id] = m

    # Evaluate each case
    if verbose:
        print("\n" + "=" * 80)
        print(" GROUND-TRUTH VALIDATION REPORT")
        print(f" Thresholds: High={threshold_high}, Medium={threshold_medium}, Low={threshold_low}")
        print("=" * 80)

    for sf_id, (expected_entra_id, expected_cat, desc) in expected_map.items():
        result = all_results.get(sf_id)
        actual_entra_id = result.entra_object_id if result else None
        actual_cat = result.match_category if result else "None"

        if expected_entra_id is None:
            # Should NOT match
            if actual_entra_id is None or actual_cat == "None":
                metrics.true_negatives += 1
                status = "✓ TN"
            else:
                metrics.false_positives += 1
                status = "✗ FP"
        else:
            # Should match
            if actual_entra_id == expected_entra_id:
                metrics.true_positives += 1
                if actual_cat != expected_cat:
                    metrics.wrong_category += 1
                    status = f"~ TP (category: expected={expected_cat}, got={actual_cat})"
                else:
                    status = "✓ TP"
            elif actual_entra_id is not None:
                metrics.false_positives += 1
                status = f"✗ FP (matched {actual_entra_id} instead of {expected_entra_id})"
            else:
                metrics.false_negatives += 1
                status = "✗ FN (no match found)"

        if verbose:
            print(f"\n  [{status}] {sf_id}: {desc}")
            if result:
                print(f"    Score: {result.composite_score}, Category: {actual_cat}")
                print(f"    Matched: {actual_entra_id} → {result.entra_display_name or 'None'}")

    if verbose:
        print("\n" + "─" * 60)
        print(f"  True Positives:  {metrics.true_positives}")
        print(f"  False Positives: {metrics.false_positives}")
        print(f"  False Negatives: {metrics.false_negatives}")
        print(f"  True Negatives:  {metrics.true_negatives}")
        print(f"  Wrong Category:  {metrics.wrong_category}")
        print(f"\n  Precision: {metrics.precision:.2%}")
        print(f"  Recall:    {metrics.recall:.2%}")
        print(f"  F1 Score:  {metrics.f1:.2%}")
        print("─" * 60)

    return metrics


def sweep_thresholds():
    """Sweep threshold combinations and print precision/recall for each."""
    print("\nThreshold Sweep — Precision / Recall / F1")
    print("=" * 70)
    print(f"{'High':>6} {'Med':>6} {'Low':>6} | {'Prec':>7} {'Recall':>7} {'F1':>7} | TP  FP  FN  TN")
    print("-" * 70)

    for high in range(70, 95, 5):
        for med in range(40, high, 10):
            for low in range(15, med, 10):
                m = evaluate_pipeline(high, med, low, verbose=False)
                print(f"{high:>6} {med:>6} {low:>6} | {m.precision:>7.2%} {m.recall:>7.2%} {m.f1:>7.2%} | {m.true_positives:>2}  {m.false_positives:>2}  {m.false_negatives:>2}  {m.true_negatives:>2}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground-truth validation for matching pipeline")
    parser.add_argument("--sweep", action="store_true", help="Sweep thresholds for P/R curves")
    args = parser.parse_args()

    if args.sweep:
        sweep_thresholds()
    else:
        evaluate_pipeline(verbose=True)
