"""
Account Discovery — Nickname / Diminutive Dictionary
Maps common English nicknames to their canonical forms.
Used by Tier 2 fuzzy matching to boost name similarity
when a nickname is involved (e.g., "Bob" ↔ "Robert").
"""

# Each key is a canonical name; values are known nicknames/diminutives.
# All comparisons should be case-insensitive.
_NICKNAME_MAP: dict[str, list[str]] = {
    "alexander": ["alex", "al", "xander", "sasha"],
    "alexandra": ["alex", "lexi", "sandra", "sasha"],
    "andrew": ["andy", "drew"],
    "anthony": ["tony", "ant"],
    "benjamin": ["ben", "benny", "benji"],
    "catherine": ["cathy", "kate", "katie", "cat", "kathy"],
    "charles": ["charlie", "chuck", "chas"],
    "charlotte": ["charlie", "lottie", "char"],
    "christopher": ["chris", "topher"],
    "daniel": ["dan", "danny"],
    "david": ["dave", "davey"],
    "deborah": ["debra", "deb", "debbie"],
    "donald": ["don", "donny"],
    "dorothy": ["dot", "dottie", "dorothea"],
    "edward": ["ed", "eddie", "ted", "teddy", "ned"],
    "elizabeth": ["liz", "lizzy", "beth", "betty", "eliza", "ellie"],
    "eugene": ["gene"],
    "evelyn": ["evie", "eve"],
    "frances": ["fran", "francie", "frankie"],
    "francis": ["frank", "fran", "frankie"],
    "frederick": ["fred", "freddy", "fritz"],
    "gabriel": ["gabe"],
    "gerald": ["gerry", "jerry"],
    "gregory": ["greg"],
    "harold": ["harry", "hal"],
    "henry": ["hank", "harry", "hal"],
    "jacob": ["jake"],
    "james": ["jim", "jimmy", "jamie"],
    "jennifer": ["jen", "jenny", "jenn"],
    "jessica": ["jess", "jessie"],
    "jonathan": ["jon", "john"],
    "joseph": ["joe", "joey"],
    "joshua": ["josh"],
    "katherine": ["kate", "kathy", "katie", "kat"],
    "lawrence": ["larry", "laurie"],
    "leonard": ["leo", "len", "lenny"],
    "margaret": ["maggie", "meg", "peggy", "marge", "margie"],
    "matthew": ["matt", "matty"],
    "michael": ["mike", "mikey"],
    "nathaniel": ["nathan", "nate", "nat"],
    "nicholas": ["nick", "nicky"],
    "patricia": ["pat", "patty", "tricia", "trish"],
    "patrick": ["pat", "paddy"],
    "peter": ["pete"],
    "philip": ["phil"],
    "raymond": ["ray"],
    "rebecca": ["becca", "becky"],
    "richard": ["rick", "ricky", "dick", "rich"],
    "robert": ["rob", "bob", "bobby", "robbie", "bert"],
    "ronald": ["ron", "ronnie"],
    "samuel": ["sam", "sammy"],
    "stephen": ["steve", "stevie", "steven"],
    "steven": ["steve", "stevie", "stephen"],
    "susan": ["sue", "susie", "suzy"],
    "theodore": ["ted", "teddy", "theo"],
    "thomas": ["tom", "tommy"],
    "timothy": ["tim", "timmy"],
    "victoria": ["vicky", "tori"],
    "virginia": ["ginny", "ginger"],
    "walter": ["walt", "wally"],
    "william": ["will", "bill", "billy", "liam", "willy"],
    "zachary": ["zach", "zack"],
}

# Build reverse lookup: nickname → set of canonical names
_REVERSE_MAP: dict[str, set[str]] = {}
for _canonical, _nicknames in _NICKNAME_MAP.items():
    _canonical_lower = _canonical.lower()
    # The canonical name maps to itself
    _REVERSE_MAP.setdefault(_canonical_lower, set()).add(_canonical_lower)
    for _nick in _nicknames:
        _nick_lower = _nick.lower()
        _REVERSE_MAP.setdefault(_nick_lower, set()).add(_canonical_lower)
        # Also add the nickname as mapping to itself so clusters work
        _REVERSE_MAP.setdefault(_canonical_lower, set()).add(_nick_lower)


def get_name_cluster(name: str) -> set[str]:
    """
    Get the set of all names that are considered equivalent to the given name.
    Returns a set including the input name itself plus all known nicknames/canonicals.
    
    Example:
        get_name_cluster("Bob") → {"bob", "robert", "rob", "bobby", "robbie", "bert"}
    """
    if not name:
        return set()
    name_lower = name.strip().lower()
    
    cluster = {name_lower}
    
    # Check if it's a canonical name
    if name_lower in _NICKNAME_MAP:
        cluster.update(n.lower() for n in _NICKNAME_MAP[name_lower])
    
    # Check if it's a nickname that maps to canonical(s)
    if name_lower in _REVERSE_MAP:
        for canonical in _REVERSE_MAP[name_lower]:
            cluster.add(canonical)
            if canonical in _NICKNAME_MAP:
                cluster.update(n.lower() for n in _NICKNAME_MAP[canonical])
    
    return cluster


def are_nickname_equivalent(name1: str, name2: str) -> bool:
    """
    Check if two first names are nickname-equivalent.
    
    Examples:
        are_nickname_equivalent("Bob", "Robert") → True
        are_nickname_equivalent("Bill", "William") → True
        are_nickname_equivalent("Alice", "Bob") → False
    """
    if not name1 or not name2:
        return False
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    if n1 == n2:
        return True
    return n2 in get_name_cluster(n1)
