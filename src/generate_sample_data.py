"""
Account Discovery Prototype — Sample Data Generator
Creates realistic synthetic data for Salesforce accounts and Entra users
with intentional overlaps, near-misses, and non-matches for testing.
"""

import csv
import os
import uuid
from datetime import datetime, timedelta
import random

# ── Base people data ──
# We create a pool of "real people" and then derive both Salesforce and Entra records
# with realistic variation (typos, format differences, missing fields, etc.)

PEOPLE = [
    # (first, last, email_prefix, department, title, phone, employee_id)
    ("Alice", "Johnson", "alice.johnson", "Engineering", "Software Engineer", "+1-425-555-0101", "EMP001"),
    ("Bob", "Smith", "bob.smith", "Sales", "Account Executive", "+1-425-555-0102", "EMP002"),
    ("Carol", "Williams", "carol.williams", "Marketing", "Marketing Manager", "+1-425-555-0103", "EMP003"),
    ("David", "Brown", "david.brown", "Engineering", "Senior Developer", "+1-425-555-0104", "EMP004"),
    ("Eva", "Davis", "eva.davis", "HR", "HR Business Partner", "+1-425-555-0105", "EMP005"),
    ("Frank", "Miller", "frank.miller", "Finance", "Financial Analyst", "+1-425-555-0106", "EMP006"),
    ("Grace", "Wilson", "grace.wilson", "Engineering", "Program Manager", "+1-425-555-0107", "EMP007"),
    ("Henry", "Moore", "henry.moore", "Sales", "Sales Manager", "+1-425-555-0108", "EMP008"),
    ("Irene", "Taylor", "irene.taylor", "Legal", "Corporate Counsel", "+1-425-555-0109", "EMP009"),
    ("James", "Anderson", "james.anderson", "Engineering", "Principal Engineer", "+1-425-555-0110", "EMP010"),
    ("Karen", "Thomas", "karen.thomas", "Support", "Support Engineer", "+1-425-555-0111", "EMP011"),
    ("Leo", "Jackson", "leo.jackson", "Engineering", "DevOps Engineer", "+1-425-555-0112", "EMP012"),
    ("Maria", "White", "maria.white", "Marketing", "Content Strategist", "+1-425-555-0113", "EMP013"),
    ("Nathan", "Harris", "nathan.harris", "Sales", "Business Dev Rep", "+1-425-555-0114", "EMP014"),
    ("Olivia", "Martin", "olivia.martin", "Engineering", "Data Scientist", "+1-425-555-0115", "EMP015"),
    ("Patrick", "Garcia", "patrick.garcia", "IT", "IT Administrator", "+1-425-555-0116", "EMP016"),
    ("Quinn", "Martinez", "quinn.martinez", "Engineering", "QA Engineer", "+1-425-555-0117", "EMP017"),
    ("Rachel", "Robinson", "rachel.robinson", "Finance", "Controller", "+1-425-555-0118", "EMP018"),
    ("Samuel", "Clark", "samuel.clark", "Engineering", "Architect", "+1-425-555-0119", "EMP019"),
    ("Tanya", "Rodriguez", "tanya.rodriguez", "HR", "Recruiter", "+1-425-555-0120", "EMP020"),
    ("Uma", "Lee", "uma.lee", "Engineering", "Frontend Developer", "+1-425-555-0121", "EMP021"),
    ("Victor", "Walker", "victor.walker", "Sales", "Regional Manager", "+1-425-555-0122", "EMP022"),
    ("Wendy", "Hall", "wendy.hall", "Marketing", "Brand Manager", "+1-425-555-0123", "EMP023"),
    ("Xavier", "Allen", "xavier.allen", "Engineering", "Security Engineer", "+1-425-555-0124", "EMP024"),
    ("Yolanda", "Young", "yolanda.young", "Legal", "Paralegal", "+1-425-555-0125", "EMP025"),
    ("Zach", "King", "zach.king", "Engineering", "ML Engineer", "+1-425-555-0126", "EMP026"),
    ("Amir", "Patel", "amir.patel", "Engineering", "Backend Developer", "+1-425-555-0127", "EMP027"),
    ("Bianca", "Nguyen", "bianca.nguyen", "Design", "UX Designer", "+1-425-555-0128", "EMP028"),
    ("Carlos", "Santos", "carlos.santos", "Engineering", "SRE", "+1-425-555-0129", "EMP029"),
    ("Diana", "Chen", "diana.chen", "Product", "Product Manager", "+1-425-555-0130", "EMP030"),
]

# ── Salesforce-only accounts (no Entra match expected) ──
SF_ONLY = [
    ("Test", "User1", "test.user1", "QA", "Tester", "", ""),
    ("Demo", "Account", "demo.account", "Sales", "Demo", "", ""),
    ("Admin", "Salesforce", "admin.sf", "IT", "Admin", "", ""),
    ("Integration", "Bot", "integration.bot", "IT", "Service Account", "", ""),
    ("Sandbox", "Testing", "sandbox.test", "Engineering", "Test Account", "", ""),
    ("External", "Contractor1", "ext.contractor1", "Consulting", "Contractor", "+1-206-555-0901", ""),
    ("Partner", "Portal", "partner.portal", "Partners", "Portal User", "", ""),
]

# ── Entra-only users (no Salesforce account) ──
ENTRA_ONLY = [
    ("Meeting", "Room1", "meetingroom1", "Facilities", "Room Mailbox", "", "", ""),
    ("Shared", "Mailbox", "shared.mailbox", "IT", "Shared Mailbox", "", "", ""),
    ("Michael", "O'Brien", "michael.obrien", "Engineering", "Tech Lead", "+1-425-555-0201", "+1-206-555-0201", "EMP040"),
    ("Sarah", "Kim", "sarah.kim", "Marketing", "VP Marketing", "+1-425-555-0202", "+1-206-555-0202", "EMP041"),
    ("Robert", "Zhang", "robert.zhang", "Finance", "CFO", "+1-425-555-0203", "+1-206-555-0203", "EMP042"),
]


def _sf_email(prefix: str) -> str:
    """Generate a Salesforce email."""
    return f"{prefix}@company.salesforce.com"


def _entra_upn(prefix: str) -> str:
    """Generate an Entra UPN."""
    return f"{prefix}@contoso.com"


def _entra_mail(prefix: str) -> str:
    """Generate an Entra mail address."""
    return f"{prefix}@contoso.com"


def _random_date(start_year=2020, end_year=2025) -> datetime:
    """Generate a random datetime."""
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    random_days = random.randint(0, delta.days)
    return start + timedelta(days=random_days)


def generate_salesforce_accounts() -> list[dict]:
    """
    Generate Salesforce accounts with realistic variations:
    - Some have matching emails to Entra (exact matches)
    - Some have slightly different names (fuzzy matches)
    - Some have no Entra counterpart at all
    - Some are test/service accounts
    """
    accounts = []
    random.seed(42)

    for i, (first, last, prefix, dept, title, phone, emp_id) in enumerate(PEOPLE):
        # Determine the variation for this person
        variation = i % 5  # Cycle through 5 variation patterns

        if variation == 0:
            # EXACT MATCH: Same email, same everything
            email = f"{prefix}@contoso.com"  # Matches Entra mail exactly
            sf_first, sf_last = first, last
            sf_phone = phone
            sf_emp_id = emp_id
        elif variation == 1:
            # NEAR MATCH: Different email domain, same name
            email = _sf_email(prefix)
            sf_first, sf_last = first, last
            sf_phone = phone
            sf_emp_id = ""  # No employee ID in Salesforce
        elif variation == 2:
            # FUZZY MATCH: Slight name variation, different email
            email = _sf_email(prefix)
            # Introduce name variations
            name_vars = [
                (first[:3], last),          # Nickname: "Ali" instead of "Alice"
                (first, last + "s"),         # Typo: "Williamss"
                (first + "e", last),         # Extra char: "Davide"
                (first, last.upper()),       # Case: "BROWN"
            ]
            sf_first, sf_last = random.choice(name_vars)
            sf_phone = phone.replace("-", " ")  # Different phone format
            sf_emp_id = emp_id
        elif variation == 3:
            # WEAK MATCH: Different email, partial name match, different dept name
            email = f"{first.lower()}{last[0].lower()}@partner.com"
            sf_first, sf_last = first, last
            sf_phone = ""  # No phone
            sf_emp_id = ""
        else:
            # MEDIUM MATCH: Same employee ID but different name format
            email = _sf_email(f"{first[0].lower()}.{last.lower()}")
            sf_first = f"{first[0]}."  # Initial only: "F."
            sf_last = last
            sf_phone = phone.replace("+1-", "").replace("-", "")  # Stripped phone
            sf_emp_id = emp_id

        accounts.append({
            "AccountId": f"SF-{uuid.uuid4().hex[:8].upper()}",
            "Email": email,
            "Username": f"{prefix}@company.salesforce.com",
            "DisplayName": f"{sf_first} {sf_last}",
            "FirstName": sf_first,
            "LastName": sf_last,
            "Phone": sf_phone,
            "Department": dept,
            "Title": title,
            "EmployeeId": sf_emp_id,
            "IsActive": True,
            "LastLoginDate": _random_date().isoformat(),
            "CreatedDate": _random_date(2018, 2022).isoformat(),
            "SourceApplication": "Salesforce",
        })

    # Add Salesforce-only accounts (test, demo, service accounts)
    for first, last, prefix, dept, title, phone, emp_id in SF_ONLY:
        accounts.append({
            "AccountId": f"SF-{uuid.uuid4().hex[:8].upper()}",
            "Email": _sf_email(prefix),
            "Username": f"{prefix}@company.salesforce.com",
            "DisplayName": f"{first} {last}",
            "FirstName": first,
            "LastName": last,
            "Phone": phone,
            "Department": dept,
            "Title": title,
            "EmployeeId": emp_id,
            "IsActive": random.choice([True, False]),
            "LastLoginDate": _random_date().isoformat(),
            "CreatedDate": _random_date(2018, 2022).isoformat(),
            "SourceApplication": "Salesforce",
        })

    return accounts


def generate_entra_users() -> list[dict]:
    """
    Generate Entra users. Most correspond to the PEOPLE list (the "ground truth"),
    plus some Entra-only accounts (room mailboxes, shared mailboxes, etc.)
    """
    users = []
    random.seed(42)

    for first, last, prefix, dept, title, phone, emp_id in PEOPLE:
        users.append({
            "ObjectId": str(uuid.uuid4()),
            "UserPrincipalName": _entra_upn(prefix),
            "Mail": _entra_mail(prefix),
            "DisplayName": f"{first} {last}",
            "GivenName": first,
            "Surname": last,
            "Phone": phone,
            "MobilePhone": phone.replace("425", "206"),  # Different mobile
            "Department": dept,
            "JobTitle": title,
            "EmployeeId": emp_id,
            "AccountEnabled": True,
            "CreatedDateTime": _random_date(2018, 2022).isoformat(),
            "UserType": "Member",
        })

    # Add Entra-only accounts
    for first, last, prefix, dept, title, phone, mobile, emp_id in ENTRA_ONLY:
        users.append({
            "ObjectId": str(uuid.uuid4()),
            "UserPrincipalName": _entra_upn(prefix),
            "Mail": _entra_mail(prefix),
            "DisplayName": f"{first} {last}",
            "GivenName": first,
            "Surname": last,
            "Phone": phone,
            "MobilePhone": mobile,
            "Department": dept,
            "JobTitle": title,
            "EmployeeId": emp_id,
            "AccountEnabled": True,
            "CreatedDateTime": _random_date(2018, 2022).isoformat(),
            "UserType": "Member",
        })

    return users


def write_csv(data: list[dict], filepath: str) -> None:
    """Write a list of dicts to a CSV file."""
    if not data:
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)


def main():
    """Generate sample data files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    data_dir = os.path.join(project_root, "data")

    sf_accounts = generate_salesforce_accounts()
    entra_users = generate_entra_users()

    write_csv(sf_accounts, os.path.join(data_dir, "salesforce_accounts.csv"))
    write_csv(entra_users, os.path.join(data_dir, "entra_users.csv"))

    print(f"Generated {len(sf_accounts)} Salesforce accounts → data/salesforce_accounts.csv")
    print(f"Generated {len(entra_users)} Entra users → data/entra_users.csv")
    print()

    # Print summary of expected match types
    exact = sum(1 for i in range(len(PEOPLE)) if i % 5 == 0)
    near = sum(1 for i in range(len(PEOPLE)) if i % 5 == 1)
    fuzzy = sum(1 for i in range(len(PEOPLE)) if i % 5 == 2)
    weak = sum(1 for i in range(len(PEOPLE)) if i % 5 == 3)
    medium = sum(1 for i in range(len(PEOPLE)) if i % 5 == 4)

    print("Expected match distribution:")
    print(f"  Exact matches (same email):        {exact}")
    print(f"  Near matches (same name/phone):     {near}")
    print(f"  Fuzzy matches (name variations):    {fuzzy}")
    print(f"  Weak matches (partial info):        {weak}")
    print(f"  Medium matches (employee ID match): {medium}")
    print(f"  SF-only (test/service accounts):    {len(SF_ONLY)}")
    print(f"  Entra-only (no SF account):         {len(ENTRA_ONLY)}")


if __name__ == "__main__":
    main()
