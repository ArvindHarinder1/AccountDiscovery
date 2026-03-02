"""
Account Discovery Prototype — Data Models
Defines the schemas for Salesforce accounts, Entra users, and match results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SalesforceAccount:
    """A user account imported from Salesforce (or other 3rd-party app)."""
    account_id: str
    email: str
    username: str
    display_name: str
    first_name: str
    last_name: str
    phone: str
    department: str
    title: str
    employee_id: str
    is_active: bool
    last_login_date: Optional[datetime] = None
    created_date: Optional[datetime] = None
    source_application: str = "Salesforce"


@dataclass
class EntraUser:
    """A user record from Microsoft Entra ID."""
    object_id: str
    user_principal_name: str
    mail: str
    display_name: str
    given_name: str
    surname: str
    phone: str
    mobile_phone: str
    department: str
    job_title: str
    employee_id: str
    account_enabled: bool
    created_date_time: Optional[datetime] = None
    user_type: str = "Member"


@dataclass
class MatchResult:
    """The result of matching a Salesforce account against Entra users."""
    salesforce_account_id: str
    salesforce_display_name: str
    salesforce_email: str
    entra_object_id: Optional[str] = None
    entra_display_name: Optional[str] = None
    entra_upn: Optional[str] = None
    match_category: str = "None"  # Exact / High / Medium / Low / None
    composite_score: float = 0.0
    email_match_score: float = 0.0
    name_match_score: float = 0.0
    phone_match_score: float = 0.0
    department_match_score: float = 0.0
    title_match_score: float = 0.0
    employee_id_match: bool = False
    ai_flags: str = "{}"  # JSON string
    ai_reasoning_summary: str = ""
    match_timestamp: datetime = field(default_factory=datetime.utcnow)
