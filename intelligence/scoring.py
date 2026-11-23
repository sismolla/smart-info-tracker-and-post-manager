from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from typing import Dict, Any

def calculate_relevance_score(item, extracted_entities=None) -> Dict[str, Any]:
    """
    Computes an explainable, multi-factor business relevance score (0 to 100).
    Factors:
      - Source Reliability (Max 25 pts)
      - Information Completeness (Max 25 pts)
      - Recency & Timeliness (Max 25 pts, with progressive staleness penalties)
      - Business & Commercial Importance (Max 25 pts)
      - Deadline Freshness Adjustment (+5 pts active urgency / -30 pts expired penalty)
    """
    factors = {}
    
    # 1. Source Reliability (0 - 25)
    source_priority = item.source.priority if hasattr(item, 'source') and item.source else 3
    source_health = item.source.health_status if hasattr(item, 'source') and item.source else 'healthy'
    
    source_score = (source_priority / 5.0) * 20.0
    if source_health == 'healthy':
        source_score += 5.0
    factors['source_reliability'] = round(source_score, 1)

    # 2. Information Completeness & Verifiability (0 - 25)
    completeness_score = 0.0
    if extracted_entities:
        if getattr(extracted_entities, 'organization', None):
            completeness_score += 5.0
        if getattr(extracted_entities, 'reference_number', None):
            completeness_score += 6.0 # Official verifiable reference number
        if getattr(extracted_entities, 'phone_number', None) or getattr(extracted_entities, 'email', None):
            completeness_score += 4.0
        if getattr(extracted_entities, 'deadline_iso', None) or getattr(extracted_entities, 'tender_deadline', None) or getattr(extracted_entities, 'application_deadline', None):
            completeness_score += 5.0
        if getattr(extracted_entities, 'estimated_budget', None) or getattr(extracted_entities, 'bid_bond_amount', None) or getattr(extracted_entities, 'salary_min', None) or getattr(extracted_entities, 'price', None):
            completeness_score += 5.0
    else:
        # Fallback if entities not yet processed
        if len(item.original_content) > 200:
            completeness_score += 15.0
        if item.canonical_url:
            completeness_score += 10.0
    factors['information_completeness'] = round(min(completeness_score, 25.0), 1)

    # 3. Smart Recency & Timeliness (Max 25 pts with decay & staleness penalties)
    pub_date = item.published_at
    if not pub_date and extracted_entities and getattr(extracted_entities, 'posted_date_iso', None):
        try:
            parsed_iso = datetime.fromisoformat(extracted_entities.posted_date_iso)
            if timezone.is_naive(parsed_iso):
                pub_date = timezone.make_aware(parsed_iso, dt_timezone.utc)
            else:
                pub_date = parsed_iso
        except Exception:
            pass

    if pub_date:
        now = timezone.now()
        age_hours = (now - pub_date).total_seconds() / 3600.0
        age_days = age_hours / 24.0

        if age_hours <= 24:          # <= 1 day
            recency_score = 25.0
            recency_desc = "Fresh (Today)"
        elif age_days <= 3:          # 1 - 3 days
            recency_score = 22.0
            recency_desc = "Recent (1-3 days ago)"
        elif age_days <= 7:          # 3 - 7 days
            recency_score = 18.0
            recency_desc = "Current (Within 1 week)"
        elif age_days <= 14:         # 1 - 2 weeks
            recency_score = 14.0
            recency_desc = "Active (Within 2 weeks)"
        elif age_days <= 30:         # 2 - 4 weeks
            recency_score = 8.0
            recency_desc = "Moderate (Within 1 month)"
        elif age_days <= 90:         # 1 - 3 months
            recency_score = 2.0
            recency_desc = "Aging (1-3 months ago)"
        elif age_days <= 180:        # 3 - 6 months
            recency_score = -15.0
            recency_desc = "Stale (-15 penalty: 3-6 months old)"
        elif age_days <= 365:        # 6 - 12 months
            recency_score = -30.0
            recency_desc = "Old (-30 penalty: 6-12 months old)"
        else:                        # > 1 year
            recency_score = -50.0
            recency_desc = "Obsolete (-50 penalty: >1 year old)"

        factors['recency'] = round(recency_score, 1)
        factors['recency_age_days'] = round(age_days, 1)
        factors['recency_status'] = recency_desc
    else:
        factors['recency'] = 8.0
        factors['recency_age_days'] = None
        factors['recency_status'] = "Undated (Baseline 8 pts)"

    # 4. Business & Commercial Keywords (0 - 25)
    text_lower = (item.title + " " + item.original_content).lower()
    high_value_keywords = [
        'tender', 'procurement', 'bid', 'ጨረታ', 'invitation', 'rfp',
        'job', 'vacancy', 'hiring', 'recruitment', 'ስራ',
        'health', 'medical', 'pharma', 'hospital', 'medicine', 'ህክምና',
        'investment', 'contract', 'supply', 'dealer', 'license', 'market'
    ]
    matched_kw = [kw for kw in high_value_keywords if kw in text_lower]
    keyword_score = min(len(matched_kw) * 5.0, 25.0)
    factors['business_importance'] = round(keyword_score, 1)
    factors['matched_keywords'] = matched_kw

    # 5. Deadline & Opportunity Freshness Adjustment (Tenders & Jobs)
    deadline_adj = 0.0
    now_date = timezone.now().date()
    dl_iso = getattr(extracted_entities, 'deadline_iso', None) if extracted_entities else None
    is_exp = getattr(extracted_entities, 'is_expired', False) if extracted_entities else False

    if dl_iso:
        try:
            dl_date = datetime.fromisoformat(dl_iso).date()
            if dl_date < now_date or is_exp:
                deadline_adj = -30.0
                factors['deadline_adjustment'] = -30.0
                factors['deadline_status'] = f"Expired on {dl_iso} (-30 pts)"
            else:
                days_left = (dl_date - now_date).days
                if days_left <= 14:
                    deadline_adj = 5.0
                    factors['deadline_adjustment'] = 5.0
                    factors['deadline_status'] = f"Closing soon in {days_left}d (+5 urgency bonus)"
                else:
                    factors['deadline_adjustment'] = 0.0
                    factors['deadline_status'] = f"Active ({days_left}d remaining)"
        except Exception:
            pass
    elif is_exp:
        deadline_adj = -30.0
        factors['deadline_adjustment'] = -30.0
        factors['deadline_status'] = "Expired deadline (-30 pts)"

    raw_total = (
        factors['source_reliability'] +
        factors['information_completeness'] +
        factors['recency'] +
        factors['business_importance'] +
        deadline_adj
    )

    total_score = max(0, min(100, int(round(raw_total))))

    return {
        'total_score': total_score,
        'breakdown': factors,
        'rating': 'High' if total_score >= 75 else 'Medium' if total_score >= 50 else 'Low'
    }
