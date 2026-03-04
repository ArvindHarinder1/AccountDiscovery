"""
Account Discovery Prototype — Tier 2: Fuzzy / Statistical Matching
Uses string similarity algorithms to find probable matches when no
exact identifier match exists.

Algorithms used:
- Jaro-Winkler: Best for person name matching (bonus for common prefixes)
- Token Set Ratio: Good for department/title matching (handles substrings)
- Phone normalization: Strip formatting, compare digits
- Levenshtein ratio: Email local-part similarity
- Nickname resolution: Maps diminutives to canonical names (Bob↔Robert)
- Unicode normalization: Handles diacritics (José↔Jose, Müller↔Mueller)
"""

import re
import unicodedata
from typing import Optional

from rapidfuzz.distance import JaroWinkler
from thefuzz import fuzz

from src.models import SalesforceAccount, EntraUser, MatchResult
from src.nicknames import are_nickname_equivalent


# ── Attribute weights for composite scoring ──
WEIGHTS = {
    "name": 0.25,             # Display name (Jaro-Winkler)
    "name_parts": 0.20,       # First+Last name tokenized
    "phone": 0.15,            # Normalized phone comparison
    "email_local": 0.20,      # Email local-part similarity (strong cross-domain signal)
    "department": 0.10,       # Department similarity
    "title": 0.05,            # Job title similarity
    "username_local": 0.05,   # Username local-part vs Entra UPN local-part
}


def normalize_phone(phone: str) -> str:
    """
    Normalize a phone number to just digits for comparison.
    Strips formatting, country codes, extensions.
    """
    if not phone:
        return ""
    # Remove everything except digits
    digits = re.sub(r"[^\d]", "", phone)
    # Strip leading country code (1 for US)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def strip_diacritics(text: str) -> str:
    """
    Remove diacritical marks from Unicode text.
    'José García' → 'Jose Garcia', 'Müller' → 'Muller'
    """
    if not text:
        return text
    # NFKD decomposition splits base chars from combining marks
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def score_name_similarity(name1: str, name2: str) -> float:
    """
    Score name similarity using Jaro-Winkler distance.
    Returns 0.0-1.0 where 1.0 is an exact match.

    Jaro-Winkler is ideal for person names because:
    - It gives a bonus for matching prefixes (common in names)
    - It handles transpositions well
    - It's less sensitive to string length differences

    Also normalizes diacritics before comparison so that
    José↔Jose, Müller↔Mueller score as identical.
    """
    if not name1 or not name2:
        return 0.0
    n1 = strip_diacritics(name1.strip().lower())
    n2 = strip_diacritics(name2.strip().lower())
    # Normalize hyphens/spaces for compound names
    n1 = n1.replace("-", " ")
    n2 = n2.replace("-", " ")
    if n1 == n2:
        return 1.0
    return JaroWinkler.similarity(n1, n2)


def score_name_parts(sf_first: str, sf_last: str, entra_given: str, entra_surname: str) -> float:
    """
    Score first+last name similarity with tokenization.
    Handles name-order variations, initials, and nicknames.
    """
    if not (sf_first or sf_last) or not (entra_given or entra_surname):
        return 0.0

    # Normalize diacritics for all components
    sf_f_clean = strip_diacritics(sf_first.strip().lower()) if sf_first else ""
    sf_l_clean = strip_diacritics(sf_last.strip().lower()).replace("-", " ") if sf_last else ""
    en_g_clean = strip_diacritics(entra_given.strip().lower()) if entra_given else ""
    en_s_clean = strip_diacritics(entra_surname.strip().lower()).replace("-", " ") if entra_surname else ""

    # Try direct first↔first, last↔last
    first_score = score_name_similarity(sf_first, entra_given)
    last_score = score_name_similarity(sf_last, entra_surname)
    direct = (first_score + last_score) / 2

    # Try swapped: first↔last, last↔first (handles reversed names)
    swap_first = score_name_similarity(sf_first, entra_surname)
    swap_last = score_name_similarity(sf_last, entra_given)
    swapped = (swap_first + swap_last) / 2

    # Handle initial matching: "J." should partially match "James"
    initial_bonus = 0.0
    sf_f = sf_first.strip().rstrip(".")
    entra_g = entra_given.strip()
    if len(sf_f) == 1 and entra_g and sf_f.lower() == entra_g[0].lower():
        initial_bonus = 0.3  # Partial credit for initial match

    # Nickname bonus: "Bob" ↔ "Robert" gets 0.85 credit
    # Only applies when names are actually different (not identical first names)
    nickname_bonus = 0.0
    if are_nickname_equivalent(sf_f_clean, en_g_clean) and sf_f_clean != en_g_clean:
        # Nickname match on first name — strong signal when last name also matches
        nickname_bonus = 0.85 * 0.5 + last_score * 0.5

    # Compound last name handling: "Johnson-Smith" should match "Smith" partially
    compound_bonus = 0.0
    for sf_part in sf_l_clean.split():
        for en_part in en_s_clean.split():
            if sf_part == en_part and len(sf_part) > 2:
                part_sim = score_name_similarity(sf_first, entra_given)
                compound_bonus = max(compound_bonus, (1.0 + part_sim) / 2 * 0.8)

    # Last-name dissimilarity gate: if last names are clearly different
    # (JW < 0.80 and not nickname-equivalent), cap name_parts to prevent
    # prefix-similar but different last names (Wilber/Wilson, Lorenz/Lopez)
    # from inflating scores.
    best = max(direct, swapped, initial_bonus + last_score * 0.7, nickname_bonus, compound_bonus)
    if last_score < 0.80 and swap_last < 0.80:
        # Neither direct nor swapped last-name pairing is strong
        best = min(best, 0.50)
    return best


def score_phone_match(phone1: str, phone2: str, phone3: str = "") -> float:
    """
    Score phone number matching after normalization.
    Compares against both business and mobile phone.
    Returns 1.0 for exact digit match, 0.0 for no match.
    """
    p1 = normalize_phone(phone1)
    if not p1:
        return 0.0

    for other_phone in [phone2, phone3]:
        p2 = normalize_phone(other_phone)
        if not p2:
            continue
        if p1 == p2:
            return 1.0
        # Partial match: last 7 digits (local number)
        if len(p1) >= 7 and len(p2) >= 7 and p1[-7:] == p2[-7:]:
            return 0.8

    return 0.0


def score_email_local_part(email1: str, email2: str) -> float:
    """
    Score similarity of email local parts using Levenshtein ratio.
    Useful for catching typos: "alice.jonhson" ↔ "alice.johnson"
    """
    def extract_local(email: str) -> str:
        if not email or "@" not in email:
            return ""
        return email.strip().lower().split("@")[0]

    local1 = extract_local(email1)
    local2 = extract_local(email2)

    if not local1 or not local2:
        return 0.0
    if local1 == local2:
        return 1.0

    return fuzz.ratio(local1, local2) / 100.0


def score_department(dept1: str, dept2: str) -> float:
    """
    Score department similarity using token set ratio.
    Handles abbreviations: "Engineering" ≈ "Eng", "HR" ≈ "Human Resources"
    """
    if not dept1 or not dept2:
        return 0.0
    d1 = dept1.strip().lower()
    d2 = dept2.strip().lower()
    if d1 == d2:
        return 1.0

    # Common abbreviation mapping
    abbrevs = {
        "hr": "human resources",
        "eng": "engineering",
        "mktg": "marketing",
        "fin": "finance",
        "it": "information technology",
    }
    d1_expanded = abbrevs.get(d1, d1)
    d2_expanded = abbrevs.get(d2, d2)

    if d1_expanded == d2_expanded:
        return 0.95

    return fuzz.token_set_ratio(d1, d2) / 100.0


def score_title(title1: str, title2: str) -> float:
    """Score job title similarity using token set ratio."""
    if not title1 or not title2:
        return 0.0
    if title1.strip().lower() == title2.strip().lower():
        return 1.0
    return fuzz.token_set_ratio(title1, title2) / 100.0


def compute_composite_score(
    name_score: float,
    name_parts_score: float,
    phone_score: float,
    email_local_score: float,
    dept_score: float,
    title_score: float,
    username_local_score: float = 0.0,
    adaptive: bool = True,
) -> float:
    """
    Compute weighted composite score from individual attribute scores.
    All inputs are 0.0-1.0, output is 0-100.

    When adaptive=True (default), redistributes weight from empty/zero-score
    signals to populated signals. This prevents sparse data (common in real
    customer environments where phone/dept/title are often blank) from
    artificially suppressing scores for obvious matches.
    """
    signal_weights = {
        "name": (name_score, WEIGHTS["name"]),
        "name_parts": (name_parts_score, WEIGHTS["name_parts"]),
        "phone": (phone_score, WEIGHTS["phone"]),
        "email_local": (email_local_score, WEIGHTS["email_local"]),
        "department": (dept_score, WEIGHTS["department"]),
        "title": (title_score, WEIGHTS["title"]),
        "username_local": (username_local_score, WEIGHTS["username_local"]),
    }

    if not adaptive:
        composite = sum(score * weight for score, weight in signal_weights.values())
        return round(composite * 100, 2)

    # Adaptive redistribution: identify which signals have data
    # A signal "has data" if it contributes a score > 0. Signals that are
    # 0 because the fields were empty get their weight redistributed.
    populated = {k: (s, w) for k, (s, w) in signal_weights.items() if s > 0}
    unpopulated = {k: (s, w) for k, (s, w) in signal_weights.items() if s == 0}

    if not populated:
        return 0.0

    # Redistribute unpopulated weight proportionally to populated signals
    total_populated_weight = sum(w for _, w in populated.values())
    total_unpopulated_weight = sum(w for _, w in unpopulated.values())

    if total_populated_weight == 0:
        return 0.0

    # Cap redistribution at 30% boost to prevent name-only matches from
    # inflating into the Medium range. E.g., if only name signals are available
    # (0.45 weight), they can grow to at most 0.45 * 1.3 = 0.585 effective weight.
    boost_factor = min(
        1.0 + total_unpopulated_weight / total_populated_weight,
        1.3,
    )

    composite = sum(score * weight * boost_factor for score, weight in populated.values())
    raw = round(composite * 100, 2)

    # ── Contradicting-evidence penalty ──
    # If name signals are strong (>0.6) but the best email/username signal is
    # weak (<0.3) AND email data actually exists, the mismatch is a red flag.
    # Apply a 0.7x penalty to the composite.
    if email_local_score > 0 and email_local_score < 0.3:
        # Email exists but doesn't match well
        if name_score > 0.6 or name_parts_score > 0.6:
            raw = round(raw * 0.7, 2)

    # ── Corroboration requirement ──
    # If the ONLY populated signals are name-related (name + name_parts) and no
    # corroborating evidence exists (email, phone, dept, title all ≤ 0.5), cap
    # the score just below the Medium threshold. Name-only matches are not
    # sufficient for Medium confidence. The 0.5 threshold ensures that weak/
    # ambiguous email similarities (e.g., "alexw" vs "alex.wilson66824" = 0.48)
    # don't count as real corroboration.
    corroborating = any(
        s > 0.5 for k, (s, _) in signal_weights.items()
        if k not in ("name", "name_parts")
    )
    if not corroborating and raw >= 50:
        raw = 49.0

    return raw


def _score_pair(
    sf_account: SalesforceAccount,
    entra: EntraUser,
) -> tuple[float, dict]:
    """
    Compute the composite score and detail breakdown for a single
    (SalesforceAccount, EntraUser) pair.
    Returns (composite_score, score_details).
    """
    name_score = score_name_similarity(sf_account.display_name, entra.display_name)
    name_parts_score = score_name_parts(
        sf_account.first_name, sf_account.last_name,
        entra.given_name, entra.surname
    )
    phone_score = score_phone_match(sf_account.phone, entra.phone, entra.mobile_phone)
    email_local_score = score_email_local_part(sf_account.email, entra.mail)
    # Also compare SF username local-part against Entra UPN local-part
    username_local_score = score_email_local_part(sf_account.username, entra.user_principal_name)
    # Take the best of email-vs-mail and username-vs-UPN for the email signal.
    # Pass 0.0 for username_local to avoid double-counting (the best is already
    # captured in best_email_score).
    best_email_score = max(email_local_score, username_local_score)
    dept_score = score_department(sf_account.department, entra.department)
    title_score = score_title(sf_account.title, entra.job_title)

    composite = compute_composite_score(
        name_score, name_parts_score, phone_score,
        best_email_score, dept_score, title_score, 0.0
    )

    score_details = {
        "name": round(name_score * 100, 1),
        "name_parts": round(name_parts_score * 100, 1),
        "phone": round(phone_score * 100, 1),
        "email_local": round(email_local_score * 100, 1),
        "department": round(dept_score * 100, 1),
        "title": round(title_score * 100, 1),
    }

    return composite, score_details


def find_fuzzy_matches(
    sf_account: SalesforceAccount,
    entra_users: list[EntraUser],
    already_matched_ids: set[str],
    top_n: int = 3,
) -> list[tuple[EntraUser, float, dict]]:
    """
    Find the top-N fuzzy matches for a single Salesforce account.

    Returns list of (EntraUser, composite_score, score_details) tuples,
    sorted by composite_score descending.
    """
    candidates = []

    for entra in entra_users:
        if entra.object_id in already_matched_ids:
            continue

        composite, score_details = _score_pair(sf_account, entra)
        candidates.append((entra, composite, score_details))

    # Sort by composite score descending and return top N
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:top_n]


def run_fuzzy_matching(
    unmatched_sf: list[SalesforceAccount],
    entra_users: list[EntraUser],
    already_matched_entra_ids: set[str],
    threshold_high: int = 80,
    threshold_medium: int = 50,
    threshold_low: int = 25,
) -> tuple[list[MatchResult], list[SalesforceAccount]]:
    """
    Run Tier 2 fuzzy matching on accounts that didn't match in Tier 1.

    Uses **global optimal matching**: compute ALL pairwise scores first,
    then assign starting from the highest-scoring pairs. This eliminates
    the order-dependent "seat-stealing" problem where a low-quality match
    could claim an Entra user before their true high-scoring counterpart
    gets processed.

    Returns:
        - fuzzy_matches: MatchResults with scores from fuzzy matching
        - still_unmatched: SalesforceAccounts that scored below threshold_low
    """
    # ── Pass 1: Compute ALL pairwise scores ──
    # Build a list of (score, sf_index, EntraUser, score_details)
    all_pairs: list[tuple[float, int, EntraUser, dict]] = []
    available_entra = [e for e in entra_users if e.object_id not in already_matched_entra_ids]

    for sf_idx, sf in enumerate(unmatched_sf):
        for entra in available_entra:
            composite, score_details = _score_pair(sf, entra)
            if composite >= threshold_low:
                all_pairs.append((composite, sf_idx, entra, score_details))

    # ── Pass 2: Greedy-optimal assignment (highest scores first) ──
    # Sort ALL pairs by score descending — high-confidence matches win
    all_pairs.sort(key=lambda x: x[0], reverse=True)

    claimed_sf: set[int] = set()           # SF indices already assigned
    claimed_entra: set[str] = set()        # Entra object_ids already assigned
    sf_assignments: dict[int, tuple[EntraUser, float, dict]] = {}

    for composite, sf_idx, entra, score_details in all_pairs:
        if sf_idx in claimed_sf or entra.object_id in claimed_entra:
            continue
        claimed_sf.add(sf_idx)
        claimed_entra.add(entra.object_id)
        sf_assignments[sf_idx] = (entra, composite, score_details)

    # ── Build results ──
    fuzzy_matches: list[MatchResult] = []
    still_unmatched: list[SalesforceAccount] = []

    for sf_idx, sf in enumerate(unmatched_sf):
        if sf_idx not in sf_assignments:
            still_unmatched.append(sf)
            continue

        best_entra, best_score, score_details = sf_assignments[sf_idx]

        # Classify match category
        if best_score >= threshold_high:
            category = "High"
        elif best_score >= threshold_medium:
            category = "Medium"
        else:
            category = "Low"

        fuzzy_matches.append(MatchResult(
            salesforce_account_id=sf.account_id,
            salesforce_display_name=sf.display_name,
            salesforce_email=sf.email,
            entra_object_id=best_entra.object_id,
            entra_display_name=best_entra.display_name,
            entra_upn=best_entra.user_principal_name,
            match_category=category,
            composite_score=best_score,
            email_match_score=score_details["email_local"],
            name_match_score=score_details["name"],
            phone_match_score=score_details["phone"],
            department_match_score=score_details["department"],
            title_match_score=score_details["title"],
            employee_id_match=False,
            ai_flags="{}",
            ai_reasoning_summary=(
                f"Fuzzy match: name={score_details['name']}%, "
                f"name_parts={score_details['name_parts']}%, "
                f"phone={score_details['phone']}%, "
                f"email_local={score_details['email_local']}%, "
                f"dept={score_details['department']}%, "
                f"title={score_details['title']}%"
            ),
        ))

    high = sum(1 for m in fuzzy_matches if m.match_category == "High")
    med = sum(1 for m in fuzzy_matches if m.match_category == "Medium")
    low = sum(1 for m in fuzzy_matches if m.match_category == "Low")

    print(f"[Tier 2 - Fuzzy] Found {len(fuzzy_matches)} matches "
          f"(High: {high}, Medium: {med}, Low: {low}), "
          f"{len(still_unmatched)} still unmatched")

    return fuzzy_matches, still_unmatched
