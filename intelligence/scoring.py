from datetime import datetime
from django.utils import timezone
from typing import Dict, Any

def calculate_relevance_score(item, extracted_entities=None) -> Dict[str, Any]:
    """
    Computes an explainable, multi-factor business relevance score (0 to 100).
    Factors:
      - Source Reliability (Max 25 pts)
      - Information Completeness (Max 25 pts)
      - Recency / Timeliness (Max 25 pts)
      - Business & Commercial Importance (Max 25 pts)
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

    # 3. Recency & Timeliness (0 - 25)
    pub_date = item.published_at or item.collected_at or timezone.now()
    age_hours = (timezone.now() - pub_date).total_seconds() / 3600.0
    
    if age_hours <= 12:
        recency_score = 25.0
    elif age_hours <= 24:
        recency_score = 22.0
    elif age_hours <= 72:
        recency_score = 18.0
    elif age_hours <= 168: # 1 week
        recency_score = 12.0
    else:
        recency_score = 5.0
    factors['recency'] = round(recency_score, 1)

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

    total_score = int(sum([
        factors['source_reliability'],
        factors['information_completeness'],
        factors['recency'],
        factors['business_importance'],
    ]))

    total_score = max(0, min(100, total_score))

    return {
        'total_score': total_score,
        'breakdown': factors,
        'rating': 'High' if total_score >= 75 else 'Medium' if total_score >= 50 else 'Low'
    }
