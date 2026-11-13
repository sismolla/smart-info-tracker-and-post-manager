import os
import re
import json
import logging
import threading
from typing import Dict, Any, Optional, List
from django.conf import settings
from .language import detect_language
from .scoring import calculate_relevance_score
from .models import CollectedItem, AIAnalysis, ExtractedEntity, Category, Tag, AIDailyUsageTracker

logger = logging.getLogger(__name__)


class GeminiKeyRotator:
    """
    Thread-safe circular API key rotator.
    Reads GEMINI_API_KEY from settings as a comma-separated list.
    On quota/rate-limit error, marks the current key as exhausted and
    advances to the next one. Cycles back to the first key after the last.
    If all keys are exhausted, signals fallback to heuristic mode.
    """
    _lock = threading.Lock()
    _keys: List[str] = []
    _current_index: int = 0
    _exhausted: set = set()
    _initialized: bool = False

    @classmethod
    def _load_keys(cls):
        raw = getattr(settings, 'GEMINI_API_KEY', '') or ''
        # Support both comma-separated and single key
        keys = [k.strip() for k in raw.split(',') if k.strip()]
        cls._keys = keys
        cls._exhausted = set()
        cls._current_index = 0
        cls._initialized = True
        if keys:
            logger.info(f"GeminiKeyRotator: Loaded {len(keys)} API key(s).")
        else:
            logger.warning("GeminiKeyRotator: No GEMINI_API_KEY configured.")

    @classmethod
    def get_current_key(cls) -> Optional[str]:
        with cls._lock:
            if not cls._initialized:
                cls._load_keys()
            if not cls._keys:
                return None
            # Find next non-exhausted key starting from current index
            total = len(cls._keys)
            for _ in range(total):
                key = cls._keys[cls._current_index % total]
                if key not in cls._exhausted:
                    return key
                cls._current_index = (cls._current_index + 1) % total
            return None  # All keys exhausted

    @classmethod
    def mark_current_exhausted(cls):
        """Call this when the current key hits a quota/rate-limit error."""
        with cls._lock:
            if not cls._keys:
                return
            current_key = cls._keys[cls._current_index % len(cls._keys)]
            cls._exhausted.add(current_key)
            old_index = cls._current_index
            cls._current_index = (cls._current_index + 1) % len(cls._keys)
            remaining = len(cls._keys) - len(cls._exhausted)
            logger.warning(
                f"GeminiKeyRotator: Key #{old_index + 1} exhausted/failed. "
                f"Rotating to key #{cls._current_index + 1}. "
                f"{remaining}/{len(cls._keys)} key(s) remaining."
            )

    @classmethod
    def reset_all(cls):
        """Resets all exhausted flags — call at start of a new day."""
        with cls._lock:
            if not cls._initialized:
                cls._load_keys()
            cls._exhausted = set()
            cls._current_index = 0
            logger.info("GeminiKeyRotator: All keys reset for new cycle.")

    @classmethod
    def all_exhausted(cls) -> bool:
        with cls._lock:
            if not cls._initialized:
                cls._load_keys()
            if not cls._keys:
                return True
            return len(cls._exhausted) >= len(cls._keys)

    @classmethod
    def status(cls) -> dict:
        with cls._lock:
            if not cls._initialized:
                cls._load_keys()
            return {
                'total_keys': len(cls._keys),
                'exhausted_keys': len(cls._exhausted),
                'active_keys': len(cls._keys) - len(cls._exhausted),
                'current_index': cls._current_index,
            }

SYSTEM_PROMPT = """
You are an expert Market Intelligence and Business Information Extraction Engine.
Analyze the provided announcement/post/article and extract structured business intelligence.

Respond ONLY with valid JSON in this exact structure:
{
  "title": "Clean, concise headline (max 150 chars)",
  "short_summary": "1-2 sentence executive summary",
  "detailed_summary": "3-5 sentence detailed summary of key details",
  "business_implications": "Actionable business implications or strategic relevance",
  "primary_category": "One of: Business News, Healthcare News, Pharmaceutical Information, Medical Equipment, Job Opportunities, Tenders and Procurement, Business Opportunities, Product Announcements, Supplier Announcements, Company Updates, Government Announcements, Market Trends, Events and Conferences, Other",
  "suggested_tags": ["tag1", "tag2"],
  "language": "en or am",
  "amharic_summary": "Amharic translation of the summary if applicable, otherwise empty",
  "entities": {
    "organization": "Company, ministry, bank, or government agency name, or null",
    "reference_number": "Exact Bid Reference No, Tender ID, or Job Code (e.g. EPSA/MOH/NCB/2026/042), or null",
    "contact_person": "Contact person name, or null",
    "phone_number": "Clean phone number or null",
    "email": "Email address, or null",
    "location": "City, region, or country, or null",
    "product_or_service": "Main product, service, or procurement items, or null",
    "opportunity_type": "Tender, Job, Partnership, Investment, or null",
    "keywords": ["keyword1", "keyword2"]
  },
  "financials": {
    "estimated_budget": "Total estimated project or contract budget amount (e.g. 14,500,000 ETB), or null",
    "bid_bond_amount": "Bid security, CPO, or guarantee amount required (e.g. 100,000 ETB), or null",
    "document_fee": "Non-refundable tender document purchase fee (e.g. 200 ETB), or null",
    "salary_min": "Minimum salary or null",
    "salary_max": "Maximum salary or null",
    "currency": "ETB, USD, EUR, etc. or null"
  },
  "dates": {
    "deadline_iso": "YYYY-MM-DD or null (converted to standard Gregorian calendar date)",
    "deadline_original": "Original deadline text as written (e.g. ታህሳስ 10 ቀን 2018 ዓ.ም), or null"
  },
  "scoring": {
    "relevance_score": 0 to 100 integer,
    "commercial_significance": "High, Medium, or Low"
  }
}

CRITICAL RULES:
1. FINANCIAL DISAMBIGUATION: Strictly distinguish between Document Purchase Fees (e.g. 200 ETB to buy bid docs), Bid Bond / CPO Security, and Total Estimated Contract Budgets. Never confuse a document fee with the project budget!
2. CALENDAR CONVERSION: If an Ethiopian calendar date is mentioned (e.g. ዓ.ም), convert it to the corresponding standard Gregorian ISO date in deadline_iso and retain the original string in deadline_original.
3. PRESERVE NULLS: Do NOT invent missing details. Preserve unknown or absent values strictly as null.
"""

class AIEngine:
    """
    Modular AI Intelligence Engine powered by Google Gemini API with Structured Schema Parsing.
    Uses circular multi-key rotation: when one key hits quota/rate-limits, automatically
    advances to the next key in the pool, cycling back to the first after the last.
    Falls back to semantic heuristic only when ALL keys are exhausted.
    """

    FALLBACK_MODELS = ['gemini-2.5-flash', 'gemini-3.5-flash', 'gemini-flash-latest']

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        self.candidate_models = []
        for m in [self.model_name] + self.FALLBACK_MODELS:
            if m and m not in self.candidate_models:
                self.candidate_models.append(m)

    def _execute_api_call(self, api_key: str, model: str, prompt: str) -> Optional[dict]:
        """Tries executing the generate_content call using google.genai, then legacy google.generativeai."""
        # 1. Try modern google.genai
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            if response and response.text and response.text.strip():
                cleaned = response.text.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                    cleaned = re.sub(r'\s*```$', '', cleaned)
                return json.loads(cleaned)
        except Exception as e_genai:
            err_str = str(e_genai).lower()
            if any(kw in err_str for kw in ['quota', 'rate', '429', 'exceeded', 'resource_exhausted', 'billing']):
                raise e_genai
            logger.debug(f"google.genai json call with {model} failed: {e_genai}")

        # 2. Try legacy google.generativeai
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            client = legacy_genai.GenerativeModel(model)
            response = client.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            if response and response.text and response.text.strip():
                cleaned = response.text.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                    cleaned = re.sub(r'\s*```$', '', cleaned)
                return json.loads(cleaned)
        except Exception as e_legacy:
            err_str = str(e_legacy).lower()
            if any(kw in err_str for kw in ['quota', 'rate', '429', 'exceeded', 'resource_exhausted', 'billing']):
                raise e_legacy
            logger.debug(f"google.generativeai json call with {model} failed: {e_legacy}")

        return None

    def _call_gemini(self, prompt: str) -> Optional[dict]:
        """
        Attempts the Gemini API call with circular key rotation.
        Tries each key in the pool once per call. On quota/rate error,
        marks the key exhausted and rotates to the next.
        Returns parsed JSON dict on success, or None if all keys fail.
        """
        if GeminiKeyRotator.all_exhausted():
            logger.warning("All Gemini API keys exhausted. Using heuristic fallback.")
            return None

        total_keys = len(GeminiKeyRotator._keys) or 1
        for attempt in range(total_keys):
            api_key = GeminiKeyRotator.get_current_key()
            if not api_key:
                break

            for model_to_use in self.candidate_models:
                try:
                    result = self._execute_api_call(api_key, model_to_use, prompt)
                    if result:
                        logger.debug(f"Gemini call succeeded on key #{GeminiKeyRotator._current_index + 1} with model {model_to_use}")
                        return result
                except Exception as e:
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in [
                        'quota', 'rate', 'limit', 'exceeded', '429', 'resource_exhausted',
                        'billing', 'invalid_api_key', 'api_key'
                    ]):
                        logger.warning(
                            f"Key #{GeminiKeyRotator._current_index + 1} hit quota/rate error: {e}. Rotating key."
                        )
                        GeminiKeyRotator.mark_current_exhausted()
                        break  # Break candidate model loop to rotate key
                    elif any(kw in err_str for kw in ['not found', '404', 'unsupported', 'invalid_argument']):
                        logger.info(f"Model '{model_to_use}' unsupported for schema parsing ({e}). Trying next model.")
                        continue
                    else:
                        logger.warning(f"Gemini error on model {model_to_use}: {e}.")
                        continue

        return None  # All keys tried and failed

    def analyze_item(self, item: CollectedItem) -> AIAnalysis:
        """
        Runs complete AI classification, structured financial extraction,
        date disambiguation, and relevance scoring on the collected item.
        """
        if not item.id:
            item.save()

        raw_text = f"Title: {item.title}\n\nContent:\n{item.original_content}\n\nSource: {item.source.name if item.source else 'Unknown'}"

        extracted_data = None
        token_usage = {'prompt_tokens': 0, 'completion_tokens': 0}
        used_gemini = False

        # 1. Attempt Gemini (with circular key rotation) — protected by daily budget breaker
        if not GeminiKeyRotator.all_exhausted():
            if not AIDailyUsageTracker.can_call_ai():
                logger.warning(
                    f"Daily AI spend cap reached. Routing item #{item.id} to heuristic fallback."
                )
            else:
                prompt = f"{SYSTEM_PROMPT}\n\nINPUT DATA:\n{raw_text}"
                extracted_data = self._call_gemini(prompt)
                if extracted_data:
                    used_gemini = True
                    p_tokens = len(prompt.split())
                    c_tokens = len(json.dumps(extracted_data).split())
                    token_usage['prompt_tokens'] = p_tokens
                    token_usage['completion_tokens'] = c_tokens
                    AIDailyUsageTracker.record_usage(p_tokens, c_tokens)

        # 2. Fallback to Semantic Heuristic Parser
        if not extracted_data:
            extracted_data = self._semantic_heuristic_analysis(item)

        # 3. Save or Update Extracted Entities with Structured Financials
        entity_info = extracted_data.get('entities', {})
        financial_info = extracted_data.get('financials', {})
        dates_info = extracted_data.get('dates', {})

        # Compute legacy price string for backwards compatibility
        primary_price = (
            financial_info.get('estimated_budget') or
            financial_info.get('salary_min') or
            financial_info.get('bid_bond_amount') or
            financial_info.get('document_fee')
        )

        entities, _ = ExtractedEntity.objects.update_or_create(
            item=item,
            defaults={
                'organization': entity_info.get('organization'),
                'reference_number': entity_info.get('reference_number'),
                'contact_person': entity_info.get('contact_person'),
                'phone_number': entity_info.get('phone_number'),
                'email': entity_info.get('email'),
                'location': entity_info.get('location'),
                'product_or_service': entity_info.get('product_or_service'),
                'opportunity_type': entity_info.get('opportunity_type'),
                'keywords': entity_info.get('keywords', []),
                # Structured Financials
                'estimated_budget': financial_info.get('estimated_budget') or None,
                'bid_bond_amount': financial_info.get('bid_bond_amount') or None,
                'document_fee': financial_info.get('document_fee') or None,
                'salary_min': financial_info.get('salary_min') or None,
                'salary_max': financial_info.get('salary_max') or None,
                'currency': financial_info.get('currency') or 'ETB',
                'price': primary_price,
                # Structured Dates
                'deadline_iso': dates_info.get('deadline_iso'),
                'deadline_original': dates_info.get('deadline_original'),
                'tender_deadline': dates_info.get('deadline_iso') or dates_info.get('deadline_original'),
                'application_deadline': dates_info.get('deadline_iso') or dates_info.get('deadline_original'),
            }
        )

        # 4. Compute Relevance Score
        scoring_from_ai = extracted_data.get('scoring', {})
        if isinstance(scoring_from_ai, dict) and 'relevance_score' in scoring_from_ai and scoring_from_ai['relevance_score'] is not None:
            relevance_score = int(scoring_from_ai['relevance_score'])
            relevance_explanation = scoring_from_ai.get('explanation', {
                'commercial_significance': 25,
                'recency_and_deadlines': 25,
                'organization_authority': 25,
                'clarity_and_completeness': 25,
            })
        else:
            scoring_result = calculate_relevance_score(item, extracted_entities=entities)
            relevance_score = scoring_result['total_score']
            relevance_explanation = scoring_result['breakdown']

        # 5. Save or Update AIAnalysis
        analysis, _ = AIAnalysis.objects.update_or_create(
            item=item,
            defaults={
                'provider': f'gemini/{self.model_name}' if used_gemini else 'semantic_heuristic_fallback',
                'model_name': self.model_name,
                'short_summary': extracted_data.get('short_summary', item.title),
                'detailed_summary': extracted_data.get('detailed_summary', item.original_content[:500]),
                'business_implications': extracted_data.get('business_implications', ''),
                'suggested_categories': [extracted_data.get('primary_category', 'Business News')],
                'suggested_tags': extracted_data.get('suggested_tags', []),
                'detected_language': extracted_data.get('language', detect_language(item.original_content)),
                'amharic_summary': extracted_data.get('amharic_summary', ''),
                'relevance_score': relevance_score,
                'relevance_explanation': relevance_explanation,
                'token_usage': token_usage,
            }
        )

        # 6. Assign Category & Tags
        cat_name = extracted_data.get('primary_category', 'Business News')
        category, _ = Category.objects.get_or_create(
            name=cat_name,
            defaults={'slug': re.sub(r'[^\w-]', '', cat_name.lower().replace(' ', '-'))}
        )
        item.categories.set([category])

        new_tags = []
        for tag_str in extracted_data.get('suggested_tags', []):
            clean_tag = tag_str.strip().lstrip('#').lower()
            if clean_tag:
                tag, _ = Tag.objects.get_or_create(name=clean_tag, defaults={'slug': clean_tag})
                new_tags.append(tag)
        item.tags.set(new_tags)  # replaces old tags on re-analyze instead of accumulating

        # Update item status
        item.status = 'ai_processed'
        item.save(update_fields=['status'])

        return analysis

    def _semantic_heuristic_analysis(self, item: CollectedItem) -> Dict[str, Any]:
        """
        Context-aware semantic token parser for offline reliability.
        Intelligently disambiguates Document Fees from Bid Bonds and Budgets.
        """
        content = item.original_content
        text_lower = (item.title + " " + content).lower()
        lang = detect_language(content)

        # 1. Category Classification
        category = "Business News"
        if any(w in text_lower for w in ['tender', 'procurement', 'bid', 'ጨረታ', 'rfp', 'invitation']):
            category = "Tenders and Procurement"
        elif any(w in text_lower for w in ['job', 'vacancy', 'hiring', 'recruitment', 'ስራ', 'cv', 'qualifications']):
            category = "Job Opportunities"
        elif any(w in text_lower for w in ['pharma', 'medicine', 'drug', 'fda', 'medication']):
            category = "Pharmaceutical Information"
        elif any(w in text_lower for w in ['medical equipment', 'diagnostic', 'mri', 'ultrasound', 'ventilator']):
            category = "Medical Equipment"
        elif any(w in text_lower for w in ['health', 'hospital', 'patient', 'doctor', 'clinic', 'ህክምና']):
            category = "Healthcare News"
        elif any(w in text_lower for w in ['launch', 'product', 'feature', 'version', 'released']):
            category = "Product Announcements"
        elif any(w in text_lower for w in ['trend', 'forecast', 'market analysis', 'growth', 'report']):
            category = "Market Trends"
        elif any(w in text_lower for w in ['conference', 'summit', 'expo', 'workshop', 'event']):
            category = "Events and Conferences"

        # 2. Reference Number Parsing (e.g. Bid Ref No, Tender No, Job Code)
        ref_no = None
        ref_match = re.search(
            r'(?:(?:bid|tender|ref)\s*(?:reference\s*no\.?|ref\s*no\.?|reference|ref|no\.?)|የጨረታ\s*ቁጥር)\s*[:#]?\s*([A-Za-z0-9/\-_.]+)',
            content,
            re.IGNORECASE
        )
        if ref_match:
            ref_no = ref_match.group(1).strip()

        # 3. Contextual Financial Disambiguation
        doc_fee = None
        bid_bond = None
        estimated_budget = None
        salary_min = None
        salary_max = None
        currency = "ETB"

        if "usd" in text_lower or "$" in content:
            currency = "USD"
        elif "eur" in text_lower or "€" in content:
            currency = "EUR"

        # Find document fee (typically 100-1000 ETB with keywords fee / non-refundable / ለመግዛት)
        fee_match = re.search(
            r'(?:fee|non-refundable|ሰነድ\s*ለመግዛት|የሰነድ\s*ዋጋ)\s*(?:of)?\s*(?:ETB|Birr|\$)?\s*([\d,]+(?:\.\d{2})?)\s*(?:ETB|Birr)?',
            content,
            re.IGNORECASE
        )
        if fee_match:
            doc_fee = f"{fee_match.group(1)} {currency}"

        # Find bid bond / security / CPO
        bond_match = re.search(
            r'(?:bid\s*(?:bond|security)|cpo|ዋስትና)\s*(?:of)?\s*(?:ETB|Birr|\$)?\s*([\d,]+(?:\.\d{2})?)\s*(?:ETB|Birr)?',
            content,
            re.IGNORECASE
        )
        if bond_match:
            bid_bond = f"{bond_match.group(1)} {currency}"

        # Find total budget or contract estimate
        budget_match = re.search(
            r'(?:budget|estimated\s*(?:at|cost)|capital|contract\s*value|total\s*(?:cost|amount))\s*(?:of)?\s*[:]?\s*(?:ETB|Birr|\$|USD)?\s*([\d,]+(?:\.\d{2})?)\s*(?:ETB|Birr|USD)?',
            content,
            re.IGNORECASE
        )
        if budget_match:
            estimated_budget = f"{budget_match.group(1)} {currency}"

        # Find salary
        salary_match = re.search(
            r'(?:salary|ደመወዝ|gross|net)\s*[:]?\s*(?:ETB|Birr|\$)?\s*([\d,]+(?:\.\d{2})?)\s*(?:[-to]\s*([\d,]+(?:\.\d{2})?))?',
            content,
            re.IGNORECASE
        )
        if salary_match:
            salary_min = f"{salary_match.group(1)} {currency}"
            if salary_match.group(2):
                salary_max = f"{salary_match.group(2)} {currency}"

        # General price fallback if nothing matched
        if not estimated_budget and not doc_fee and not bid_bond and not salary_min:
            general_money = re.search(r'(?:ETB|Birr|USD|\$)\s*([\d,]+(?:\.\d{2})?)|\b([\d,]+(?:\.\d{2})?)\s*(?:ETB|Birr|USD)', content, re.IGNORECASE)
            if general_money:
                val = general_money.group(1) or general_money.group(2)
                if category == "Job Opportunities":
                    salary_min = f"{val} {currency}"
                elif category == "Tenders and Procurement":
                    estimated_budget = f"{val} {currency}"
                else:
                    estimated_budget = f"{val} {currency}"

        # 4. Organization Extraction
        org = None
        org_match = re.search(r'(?:Organization|Company|Employer|Agency|Ministry|Bank|Authority|ድርጅት):\s*([^\n,]+)', content, re.IGNORECASE)
        if org_match:
            raw_org = org_match.group(1).strip()
            parts = re.split(r'(?<!\bSt)(?<!\bCo)(?<!\bDr)(?<!\bInc)(?<!\bLtd)\.\s+', raw_org)
            org = parts[0].strip()
        elif 'efda' in text_lower or 'food and drug authority' in text_lower:
            org = "Ethiopian Food and Drug Authority (EFDA)"
        elif 'ministry of health' in text_lower or 'moh' in text_lower:
            org = "Ministry of Health (MOH)"
        elif 'public health institute' in text_lower or 'ephi' in text_lower:
            org = "Ethiopian Public Health Institute (EPHI)"
        elif 'public procurement' in text_lower or 'ppa' in text_lower:
            org = "Public Procurement and Property Authority (PPA)"
        elif item.author and item.author != 'Unknown':
            org = item.author

        # 5. Deadlines & Calendar Extraction
        deadline_original = None
        deadline_iso = None
        dl_match = re.search(r'(?:deadline|closing date|due date|መዝጊያ ቀን)\s*[:]?\s*([^\n,]+)', content, re.IGNORECASE)
        if dl_match:
            deadline_original = dl_match.group(1).strip()
            # If standard Gregorian YYYY-MM-DD or MM/DD/YYYY is in the text, parse to ISO
            iso_match = re.search(r'\b(202[4-9]-\d{2}-\d{2})\b', deadline_original)
            if iso_match:
                deadline_iso = iso_match.group(1)

        # 6. Phone Numbers and Clean Links (Regex is appropriate here)
        phones = re.findall(r'(?:\+251[\s.-]?|0)[79]\d{1,2}(?:[\s.-]?\d{2,3}){2,3}|\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', content)
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', content)

        # 7. Summaries
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        short_summary = lines[0][:150] if lines else item.title
        detailed_summary = " ".join(lines[:4])[:500] if lines else item.title

        return {
            "title": item.title,
            "short_summary": short_summary,
            "detailed_summary": detailed_summary,
            "business_implications": f"Identified as {category}. Relevant for enterprise market monitoring and business development.",
            "primary_category": category,
            "suggested_tags": [category.lower().replace(' ', '-'), "market-intelligence"],
            "language": lang,
            "amharic_summary": short_summary if lang == 'am' else "",
            "entities": {
                "organization": org,
                "reference_number": ref_no,
                "contact_person": None,
                "phone_number": phones[0] if phones else None,
                "email": emails[0] if emails else None,
                "location": "Addis Ababa" if "addis ababa" in text_lower or "አዲስ አበባ" in content else None,
                "product_or_service": None,
                "opportunity_type": category if category in ["Job Opportunities", "Tenders and Procurement"] else None,
                "keywords": [w for w in ['bid', 'procurement', 'job', 'health', 'pharma'] if w in text_lower]
            },
            "financials": {
                "estimated_budget": estimated_budget,
                "bid_bond_amount": bid_bond,
                "document_fee": doc_fee,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "currency": currency,
            },
            "dates": {
                "deadline_iso": deadline_iso,
                "deadline_original": deadline_original,
            },
            "scoring": {
                "relevance_score": 80 if ref_no or estimated_budget or bid_bond else 60,
                "commercial_significance": "High" if estimated_budget or bid_bond else "Medium"
            }
        }
