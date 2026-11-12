import os
import re
import json
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from .language import detect_language
from .scoring import calculate_relevance_score
from .models import CollectedItem, AIAnalysis, ExtractedEntity, Category, Tag

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an expert Market Intelligence and Business Information Extraction Engine.
Analyze the provided announcement/post/article and extract structured intelligence.

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
    "organization": "Company or government agency name, or null",
    "contact_person": "Contact person name, or null",
    "phone_number": "Phone number, or null",
    "email": "Email address, or null",
    "location": "City, region, or country, or null",
    "product_or_service": "Main product, service, or opportunity, or null",
    "price": "Price or budget when explicitly stated, or null",
    "application_deadline": "Application deadline if job/grant, or null",
    "tender_deadline": "Tender submission deadline if bid/tender, or null",
    "opportunity_type": "Tender, Job, Partnership, Investment, or null",
    "keywords": ["keyword1", "keyword2"]
  }
}

STRICT RULE: Do NOT invent missing details. Preserve unknown or absent values as null.
"""

class AIEngine:
    """
    Modular AI Intelligence Engine powered by Google Gemini API,
    with an intelligent offline heuristic fallback for development and cPanel reliability.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', '')
        self.model_name = model_name or getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
        self._gemini_client = None

        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._gemini_client = genai.GenerativeModel(self.model_name)
            except Exception as e:
                logger.warning(f"Could not initialize Google Generative AI client: {e}")

    def analyze_item(self, item: CollectedItem) -> AIAnalysis:
        """
        Runs complete AI classification, entity extraction, summarization,
        and relevance scoring on the collected item.
        """
        raw_text = f"Title: {item.title}\n\nContent:\n{item.original_content}\n\nSource: {item.source.name if item.source else 'Unknown'}"
        
        extracted_data = None
        token_usage = {'prompt_tokens': 0, 'completion_tokens': 0}

        # 1. Attempt Gemini API analysis if client available
        if self._gemini_client:
            try:
                prompt = f"{SYSTEM_PROMPT}\n\nINPUT DATA:\n{raw_text}"
                response = self._gemini_client.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    cleaned_json = response.text.strip()
                    # Strip any markdown code fence if returned
                    if cleaned_json.startswith("```"):
                        cleaned_json = re.sub(r'^```(?:json)?\s*', '', cleaned_json)
                        cleaned_json = re.sub(r'\s*```$', '', cleaned_json)
                    extracted_data = json.loads(cleaned_json)
                    token_usage['prompt_tokens'] = len(prompt.split())
                    token_usage['completion_tokens'] = len(response.text.split())
            except Exception as e:
                logger.warning(f"Gemini API call failed for item #{item.id}: {e}. Engaging heuristic fallback.")

        # 2. Fallback to Heuristic Rule-Based Intelligence Engine
        if not extracted_data:
            extracted_data = self._heuristic_analysis(item)

        # 3. Save or Update Extracted Entities
        entity_info = extracted_data.get('entities', {})
        entities, _ = ExtractedEntity.objects.update_or_create(
            item=item,
            defaults={
                'organization': entity_info.get('organization'),
                'contact_person': entity_info.get('contact_person'),
                'phone_number': entity_info.get('phone_number'),
                'email': entity_info.get('email'),
                'location': entity_info.get('location'),
                'product_or_service': entity_info.get('product_or_service'),
                'price': entity_info.get('price'),
                'application_deadline': entity_info.get('application_deadline'),
                'tender_deadline': entity_info.get('tender_deadline'),
                'opportunity_type': entity_info.get('opportunity_type'),
                'keywords': entity_info.get('keywords', []),
            }
        )

        # 4. Compute Explainable Relevance Score
        scoring_result = calculate_relevance_score(item, extracted_entities=entities)

        # 5. Save or Update AIAnalysis
        analysis, _ = AIAnalysis.objects.update_or_create(
            item=item,
            defaults={
                'provider': 'gemini' if self._gemini_client else 'rule_based_fallback',
                'model_name': self.model_name,
                'short_summary': extracted_data.get('short_summary', item.title),
                'detailed_summary': extracted_data.get('detailed_summary', item.original_content[:500]),
                'business_implications': extracted_data.get('business_implications', ''),
                'suggested_categories': [extracted_data.get('primary_category', 'Business News')],
                'suggested_tags': extracted_data.get('suggested_tags', []),
                'detected_language': extracted_data.get('language', detect_language(item.original_content)),
                'amharic_summary': extracted_data.get('amharic_summary', ''),
                'relevance_score': scoring_result['total_score'],
                'relevance_explanation': scoring_result['breakdown'],
                'token_usage': token_usage,
            }
        )

        # 6. Assign Category & Tags
        cat_name = extracted_data.get('primary_category', 'Business News')
        category, _ = Category.objects.get_or_create(
            name=cat_name,
            defaults={'slug': re.sub(r'[^\w-]', '', cat_name.lower().replace(' ', '-'))}
        )
        item.categories.add(category)

        for tag_str in extracted_data.get('suggested_tags', []):
            clean_tag = tag_str.strip().lstrip('#').lower()
            if clean_tag:
                tag, _ = Tag.objects.get_or_create(name=clean_tag, defaults={'slug': clean_tag})
                item.tags.add(tag)

        # Update item status
        item.status = 'ai_processed'
        item.save(update_fields=['status'])

        return analysis

    def _heuristic_analysis(self, item: CollectedItem) -> Dict[str, Any]:
        """
        High-performance heuristic extraction using regex & pattern matching.
        Ensures zero-downtime and local testing without external API dependence.
        """
        content = item.original_content
        text_lower = (item.title + " " + content).lower()
        lang = detect_language(content)

        # Category Heuristic
        category = "Business News"
        if any(w in text_lower for w in ['tender', 'procurement', 'bid', 'ጨረታ', 'rfp', 'invitation']):
            category = "Tenders and Procurement"
        elif any(w in text_lower for w in ['job', 'vacancy', 'hiring', 'recruitment', 'ስራ', 'cv', 'qualifications']):
            category = "Job Opportunities"
        elif any(w in text_lower for w in ['pharma', 'medicine', 'drug', 'fda', 'medication']):
            category = "Pharmaceutical Information"
        elif any(w in text_lower for w in ['medical equipment', 'diagnostic', 'mri', 'ultrasound', 'ventilator', 'hospital device']):
            category = "Medical Equipment"
        elif any(w in text_lower for w in ['health', 'hospital', 'patient', 'doctor', 'clinic', 'ህክምና']):
            category = "Healthcare News"
        elif any(w in text_lower for w in ['launch', 'product', 'feature', 'version', 'released']):
            category = "Product Announcements"
        elif any(w in text_lower for w in ['trend', 'forecast', 'market analysis', 'growth', 'report']):
            category = "Market Trends"
        elif any(w in text_lower for w in ['conference', 'summit', 'expo', 'workshop', 'event', 'webinar']):
            category = "Events and Conferences"

        # Regex Extraction
        phones = re.findall(r'(?:\+251|0)[79]\d{8}|\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', content)
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', content)
        prices = re.findall(r'(?:ETB|Birr|USD|\$|EUR|€)\s*[\d,]+(?:\.\d{2})?|\b[\d,]+(?:\.\d{2})?\s*(?:ETB|Birr|USD|Dollars)', content, re.IGNORECASE)

        # Organization heuristic
        org = None
        org_match = re.search(r'(?:Organization|Company|Employer|Agency|Ministry|Bank|Authority|ድርጅት):\s*([^\n,]+)', content, re.IGNORECASE)
        if org_match:
            raw_org = org_match.group(1).strip()
            parts = re.split(r'(?<!\bSt)(?<!\bCo)(?<!\bDr)(?<!\bInc)(?<!\bLtd)\.\s+', raw_org)
            org = parts[0].strip()
        elif item.author and item.author != 'Unknown':
            org = item.author

        # Deadlines
        deadline = None
        dl_match = re.search(r'(?:deadline|closing date|due date|መዝጊያ ቀን):\s*([^\n,]+)', content, re.IGNORECASE)
        if dl_match:
            raw_dl = dl_match.group(1).strip()
            parts = re.split(r'\.\s+', raw_dl)
            deadline = parts[0].strip()
        if dl_match:
            deadline = dl_match.group(1).strip()

        # Summaries
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
                "contact_person": None,
                "phone_number": phones[0] if phones else None,
                "email": emails[0] if emails else None,
                "location": "Addis Ababa" if "addis ababa" in text_lower or "አዲስ አበባ" in content else None,
                "product_or_service": None,
                "price": prices[0] if prices else None,
                "application_deadline": deadline if category == "Job Opportunities" else None,
                "tender_deadline": deadline if category == "Tenders and Procurement" else None,
                "opportunity_type": category if category in ["Job Opportunities", "Tenders and Procurement"] else None,
                "keywords": [w for w in ['bid', 'procurement', 'job', 'health', 'pharma'] if w in text_lower]
            }
        }
