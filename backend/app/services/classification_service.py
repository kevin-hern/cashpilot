"""
Transaction classification service.

Plaid's personal_finance_category can be wrong for payroll deposits
(e.g., GUSTO PAY showing as RENT_AND_UTILITIES). This module provides
a normalization layer that overrides Plaid's category when the transaction
name or merchant matches known payroll vendors.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from collections import defaultdict

# ── Payroll keyword patterns ──────────────────────────────────────────────────
# Checked against the combined "raw_name merchant_name" string (lowercased).
#
# NOTE: Do NOT use a leading \b for short vendor names like "gusto" or "adp".
# Plaid sometimes concatenates the vendor name directly onto the ACH description
# with no separator, e.g. "ACH Electronic CreditGUSTO PAY 123456". A leading
# word-boundary anchor would silently miss these.
PAYROLL_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"gusto",                    # matches "GUSTO PAY" and "CreditGUSTO"
    r"\badp\b",                  # short — keep trailing boundary to avoid "adapter"
    r"paychex",
    r"paycor",
    r"direct\s*dep",             # "DIRECT DEP", "DIRECTDEP", "DIRECT DEPOSIT"
    r"payroll",
    r"paycheck",
    r"\bwages\b",
    r"\bsalary\b",
    r"intuit\s*payroll",
    r"workday\s*payroll",
    r"quickbooks\s*payroll",
    r"gusto\s*pay",              # explicit variant
]]

# Plaid categories that indicate a credit/income even when amount sign is wrong
INCOME_CATEGORIES = {"INCOME", "TRANSFER_IN"}


def _combined_name(raw_name: str | None, merchant_name: str | None) -> str:
    return f"{raw_name or ''} {merchant_name or ''}".strip()


def matches_payroll(raw_name: str | None, merchant_name: str | None) -> bool:
    """Return True if any payroll keyword pattern matches the transaction names."""
    text = _combined_name(raw_name, merchant_name)
    return any(p.search(text) for p in PAYROLL_PATTERNS)


def extract_payroll_source(raw_name: str | None, merchant_name: str | None) -> str | None:
    """Return the canonical payroll vendor name, or None if not detected."""
    text = _combined_name(raw_name, merchant_name)
    labels = {
        "gusto": "GUSTO",
        "adp": "ADP",
        "paychex": "PAYCHEX",
        "paycor": "PAYCOR",
        "direct dep": "DIRECT DEPOSIT",
        "payroll": "PAYROLL",
        "intuit payroll": "INTUIT PAYROLL",
        "quickbooks payroll": "QUICKBOOKS PAYROLL",
    }
    text_lower = text.lower()
    for keyword, label in labels.items():
        if keyword in text_lower:
            return label
    return None


def normalize_category(
    raw_name: str | None,
    merchant_name: str | None,
    plaid_category: str | None,
    amount: float,
) -> str:
    """
    Return the correct category_primary for storage.

    Override Plaid's category with "INCOME" when:
    - The transaction name matches a known payroll vendor (regardless of amount
      sign — Plaid sandbox sometimes sends payroll as positive/debit), OR
    - Plaid already said it's income/transfer_in and it's a credit (amount <= 0)
    """
    if matches_payroll(raw_name, merchant_name):
        return "INCOME"
    if plaid_category in INCOME_CATEGORIES and amount <= 0:
        return "INCOME"
    return plaid_category or "OTHER"


def is_paycheck(
    amount: float,
    category_primary: str | None,
    raw_name: str | None,
    merchant_name: str | None,
) -> bool:
    """
    True if this transaction should be stored as a Paycheck record.

    Standard Plaid convention: negative amount = credit (money IN).
    Sandbox quirk: some payroll deposits arrive with a positive amount and a
    wrong category (e.g. RENT_AND_UTILITIES). We catch those via keyword match.
    """
    is_payroll_name = matches_payroll(raw_name, merchant_name)
    is_income_cat = category_primary == "INCOME"
    is_credit = amount <= 0

    if abs(amount) < 200:
        return False

    # Accept if: standard credit, OR income category, OR keyword match regardless of sign
    return is_credit or is_income_cat or is_payroll_name


def detect_pay_frequency(posted_dates: list[date]) -> str | None:
    """
    Infer pay frequency from a sorted list of paycheck dates.
    Needs at least 2 dates to determine a pattern.
    """
    if len(posted_dates) < 2:
        return None

    sorted_dates = sorted(posted_dates)
    gaps: list[int] = [
        (sorted_dates[i + 1] - sorted_dates[i]).days
        for i in range(len(sorted_dates) - 1)
    ]
    avg_gap = sum(gaps) / len(gaps)

    if avg_gap <= 8:
        return "weekly"
    elif avg_gap <= 16:
        return "biweekly"
    elif avg_gap <= 18:
        return "semimonthly"
    elif avg_gap <= 35:
        return "monthly"
    else:
        return "irregular"


def detect_recurring_income(
    transactions: list,   # list of Transaction ORM objects
    min_amount: float = 500,
    min_occurrences: int = 2,
    window_days: int = 90,
) -> list:
    """
    Among transactions not already classified as INCOME, find credits > min_amount
    that recur within window_days. Returns the transactions that should be
    re-classified as INCOME (likely payroll that Plaid mis-categorized).
    """
    cutoff = date.today() - timedelta(days=window_days)
    candidates = [
        t for t in transactions
        if t.amount <= 0                          # credit
        and abs(t.amount) >= min_amount
        and t.category_primary != "INCOME"
        and t.posted_at >= cutoff
    ]

    # Group by rounded amount (within 5% tolerance) + source heuristic
    groups: dict[str, list] = defaultdict(list)
    for txn in candidates:
        bucket = str(round(abs(txn.amount) / 50) * 50)   # bucket to nearest $50
        groups[bucket].append(txn)

    recurring = []
    for txns in groups.values():
        if len(txns) >= min_occurrences:
            recurring.extend(txns)
    return recurring
