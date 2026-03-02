"""
Account Discovery Prototype — Main Orchestrator
Runs the full matching pipeline:
  1. Load data (from CSV or Kusto)
  2. Tier 1: Deterministic matching (exact email, employee ID, UPN)
  3. Tier 2: Fuzzy matching (Jaro-Winkler, phone normalization, etc.)
  4. Tier 3: AI agent (pattern detection + semantic reasoning)
  5. Generate reports
"""

import os
import sys
import time

from src.config import get_settings
from src.data_loader import load_data, write_results_to_kusto
from src.tier1_deterministic import run_deterministic_matching
from src.tier2_fuzzy import run_fuzzy_matching
from src.tier3_ai_agent import (
    detect_patterns,
    enhance_matches_with_ai,
    create_unmatched_results,
)
from src.reporting import generate_csv_report, generate_json_report, print_summary


def run_pipeline():
    """Execute the full Account Discovery matching pipeline."""
    settings = get_settings()
    start_time = time.time()

    print("=" * 70)
    print("  ACCOUNT DISCOVERY PROTOTYPE — Matching Pipeline")
    print("=" * 70)
    print(f"\n  Data source:        {settings.data_source}")
    if settings.data_source == "graph":
        print(f"  Service Principal:  {settings.graph_service_principal_id}")
    print(f"  AI provider:        {settings.ai_provider}")
    print(f"  High threshold:     {settings.match_threshold_high}")
    print(f"  Medium threshold:   {settings.match_threshold_medium}")
    print(f"  Low threshold:      {settings.match_threshold_low}")
    print()

    # ── Step 1: Load data ──
    print("─" * 50)
    print("STEP 1: Loading data...")
    sf_accounts, entra_users = load_data()

    # ── Step 2: Tier 1 — Deterministic Matching ──
    print("\n" + "─" * 50)
    print("STEP 2: Tier 1 — Deterministic Matching")
    exact_matches, unmatched_after_t1 = run_deterministic_matching(sf_accounts, entra_users)

    # Track which Entra users are already matched
    matched_entra_ids = {m.entra_object_id for m in exact_matches if m.entra_object_id}

    # ── Step 3: Tier 2 — Fuzzy Matching ──
    print("\n" + "─" * 50)
    print("STEP 3: Tier 2 — Fuzzy Matching")
    fuzzy_matches, unmatched_after_t2 = run_fuzzy_matching(
        unmatched_after_t1,
        entra_users,
        matched_entra_ids,
        threshold_high=settings.match_threshold_high,
        threshold_medium=settings.match_threshold_medium,
        threshold_low=settings.match_threshold_low,
    )

    # ── Step 4: Tier 3 — AI Agent ──
    print("\n" + "─" * 50)
    print("STEP 4: Tier 3 — AI Agent Analysis")

    # 4a: Pattern detection (runs on ALL Salesforce accounts)
    pattern_flags = detect_patterns(sf_accounts)

    # 4b: Enhance fuzzy matches with AI reasoning
    enhanced_fuzzy = enhance_matches_with_ai(
        fuzzy_matches, sf_accounts, entra_users, pattern_flags
    )

    # 4c: Create results for unmatched accounts (with AI flags)
    unmatched_results = create_unmatched_results(unmatched_after_t2, pattern_flags)

    # ── Step 5: Combine all results ──
    all_results = exact_matches + enhanced_fuzzy + unmatched_results

    # Apply pattern flags to exact matches too
    for result in exact_matches:
        if result.salesforce_account_id in pattern_flags:
            import json
            result.ai_flags = json.dumps(pattern_flags[result.salesforce_account_id])

    # Sort by composite score descending
    all_results.sort(key=lambda r: r.composite_score, reverse=True)

    # ── Step 6: Generate reports ──
    print("\n" + "─" * 50)
    print("STEP 5: Generating Reports")

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(project_root, "output")

    csv_path = generate_csv_report(all_results, output_dir)
    json_path = generate_json_report(all_results, output_dir)

    print(f"  CSV report:  {csv_path}")
    print(f"  JSON report: {json_path}")

    # ── Step 6: Write results to Kusto (if using Kusto or Graph) ──
    if settings.data_source in ("kusto", "graph"):
        print("\n" + "─" * 50)
        print("STEP 6: Writing results to Kusto")
        try:
            count = write_results_to_kusto(all_results)
            print(f"  ✓ {count} results written to MatchResults table")
        except Exception as e:
            print(f"  ✗ Error writing to Kusto: {e}")

    # ── Print summary ──
    print_summary(all_results)

    elapsed = time.time() - start_time
    print(f"\n  Pipeline completed in {elapsed:.2f} seconds")
    print(f"  Total accounts processed: {len(sf_accounts)}")
    print(f"  Total results generated: {len(all_results)}")

    return all_results


if __name__ == "__main__":
    run_pipeline()
