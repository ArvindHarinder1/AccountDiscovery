"""
Account Discovery Prototype — Reporting Module
Generates human-readable reports from match results.
Outputs to CSV, JSON, and console summary.
"""

import csv
import json
import os
from datetime import datetime
from typing import Optional

from src.models import MatchResult


def generate_csv_report(results: list[MatchResult], output_dir: str) -> str:
    """Write match results to a CSV file. Returns the file path."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"match_report_{timestamp}.csv")

    fieldnames = [
        "SalesforceAccountId",
        "SalesforceDisplayName",
        "SalesforceEmail",
        "EntraObjectId",
        "EntraDisplayName",
        "EntraUPN",
        "MatchCategory",
        "CompositeScore",
        "EmailMatchScore",
        "NameMatchScore",
        "PhoneMatchScore",
        "DepartmentMatchScore",
        "TitleMatchScore",
        "EmployeeIdMatch",
        "AIFlags",
        "AIReasoningSummary",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "SalesforceAccountId": r.salesforce_account_id,
                "SalesforceDisplayName": r.salesforce_display_name,
                "SalesforceEmail": r.salesforce_email,
                "EntraObjectId": r.entra_object_id or "",
                "EntraDisplayName": r.entra_display_name or "",
                "EntraUPN": r.entra_upn or "",
                "MatchCategory": r.match_category,
                "CompositeScore": r.composite_score,
                "EmailMatchScore": r.email_match_score,
                "NameMatchScore": r.name_match_score,
                "PhoneMatchScore": r.phone_match_score,
                "DepartmentMatchScore": r.department_match_score,
                "TitleMatchScore": r.title_match_score,
                "EmployeeIdMatch": r.employee_id_match,
                "AIFlags": r.ai_flags,
                "AIReasoningSummary": r.ai_reasoning_summary,
            })

    return filepath


def generate_json_report(results: list[MatchResult], output_dir: str) -> str:
    """Write match results to a JSON file. Returns the file path."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"match_report_{timestamp}.json")

    data = []
    for r in results:
        data.append({
            "salesforce_account_id": r.salesforce_account_id,
            "salesforce_display_name": r.salesforce_display_name,
            "salesforce_email": r.salesforce_email,
            "entra_object_id": r.entra_object_id,
            "entra_display_name": r.entra_display_name,
            "entra_upn": r.entra_upn,
            "match_category": r.match_category,
            "composite_score": r.composite_score,
            "scores": {
                "email": r.email_match_score,
                "name": r.name_match_score,
                "phone": r.phone_match_score,
                "department": r.department_match_score,
                "title": r.title_match_score,
                "employee_id_match": r.employee_id_match,
            },
            "ai_flags": json.loads(r.ai_flags) if r.ai_flags else {},
            "ai_reasoning": r.ai_reasoning_summary,
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.utcnow().isoformat(), "results": data}, f, indent=2)

    return filepath


def print_summary(results: list[MatchResult]) -> None:
    """Print a formatted summary of matching results to the console."""
    total = len(results)
    exact = [r for r in results if r.match_category == "Exact"]
    high = [r for r in results if r.match_category == "High"]
    medium = [r for r in results if r.match_category == "Medium"]
    low = [r for r in results if r.match_category == "Low"]
    none = [r for r in results if r.match_category == "None"]

    # Count AI-flagged accounts
    flagged = [r for r in results if r.ai_flags and r.ai_flags != "{}"]

    print("\n" + "=" * 70)
    print("  ACCOUNT DISCOVERY — MATCH REPORT SUMMARY")
    print("=" * 70)
    print(f"\n  Total Salesforce accounts analyzed:  {total}")
    print(f"  ─────────────────────────────────────────")
    print(f"  Exact matches (score = 100):         {len(exact):>3}  ({_pct(len(exact), total)})")
    print(f"  High confidence (score 80-99):       {len(high):>3}  ({_pct(len(high), total)})")
    print(f"  Medium confidence (score 50-79):     {len(medium):>3}  ({_pct(len(medium), total)})")
    print(f"  Low confidence (score 25-49):        {len(low):>3}  ({_pct(len(low), total)})")
    print(f"  No match (score < 25):               {len(none):>3}  ({_pct(len(none), total)})")
    print(f"  ─────────────────────────────────────────")
    print(f"  AI-flagged accounts:                 {len(flagged):>3}  ({_pct(len(flagged), total)})")

    if flagged:
        print(f"\n  AI-Flagged Accounts:")
        for r in flagged:
            try:
                flags_data = json.loads(r.ai_flags)
                flag_types = flags_data.get("flags", [])
                reason = flags_data.get("reason", "")
            except json.JSONDecodeError:
                flag_types = []
                reason = r.ai_flags
            print(f"    • {r.salesforce_display_name} ({r.salesforce_email})")
            print(f"      Flags: {', '.join(flag_types) if flag_types else 'unknown'}")
            print(f"      Reason: {reason}")

    # Show some example matches from each category
    for category, items in [("High", high), ("Medium", medium), ("Low", low)]:
        if items:
            print(f"\n  Sample {category} Confidence Matches:")
            for r in items[:3]:
                print(f"    • {r.salesforce_display_name} → {r.entra_display_name}  "
                      f"(score: {r.composite_score})")
                if r.ai_reasoning_summary:
                    summary = r.ai_reasoning_summary[:100]
                    print(f"      {summary}{'...' if len(r.ai_reasoning_summary) > 100 else ''}")

    if none:
        print(f"\n  Unmatched Accounts (sample):")
        for r in none[:5]:
            print(f"    • {r.salesforce_display_name} ({r.salesforce_email})")

    print("\n" + "=" * 70)


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n / total * 100:.0f}%"
