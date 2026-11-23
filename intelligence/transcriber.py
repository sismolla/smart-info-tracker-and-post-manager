"""
News Transcription & Translation Engine
========================================
One-click rewriting of raw scraped content into professional news articles,
with bidirectional English <-> Amharic translation.

Features:
- Configurable model with automatic fallback (gemini-3.5-transcribe -> gemini-2.0-flash -> gemini-1.5-flash)
- Thread-safe circular Gemini key rotation
- Professional news styling (headline, dateline, lead, core facts, call-to-action)
- Bidirectional conversion: English <-> Amharic
- One-click dual generation (Both languages ready for multi-channel broadcast)
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from .ai_client import GeminiKeyRotator

logger = logging.getLogger(__name__)

# --- High Quality Journalism Prompts ---

NEWS_EN_PROMPT = """You are a senior broadcast and print business journalist specializing in Ethiopian and African market news.
Transform the following raw collected announcement or social post into an authoritative, engaging, and professional English news article.

Formatting & Editorial Guidelines:
1. HEADLINE: Create a compelling, professional news headline on the very first line (do NOT prefix with "Headline:").
2. DATELINE: Start the first paragraph with "ADDIS ABABA — ".
3. STRUCTURE:
   - Lead paragraph: Who, what, when, and commercial significance.
   - Key Facts: Clearly highlight reference numbers, deadlines, budgets/fees, or eligibility in clean paragraphs or bullet points.
   - Context & Action: Explain who should care and next steps (where to get documents, apply, or register).
4. TONE: Objective, polished, high-standard economic journalism (Reuters / Bloomberg / Capital Ethiopia style).
5. FACTUAL INTEGRITY: Strictly preserve all names, numbers, figures, and dates. Do NOT hallucinate unmentioned facts.
6. LENGTH: 150-300 words.

RAW SOURCE CONTENT:
{content}
"""

NEWS_AM_PROMPT = """እርስዎ በኢትዮጵያ ንግድ፣ ኢኮኖሚ እና ገበያ መረጃ ላይ የተካኑ ከፍተኛ የዜና ጋዜጠኛ ነዎት።
የሚከተለውን ጥሬ ማስታወቂያ ወይም የሶሻል ሚዲያ መረጃ ወደ ከፍተኛ ደረጃ ሙያዊ የአማርኛ ዜና ጽሁፍ ቀይሩት።

የአጻጻፍ እና የይዘት መመሪያዎች:
1. ርዕስ: በመጀመሪያው መስመር ላይ ሳቢ እና ሙያዊ የዜና ርዕስ ያቅርቡ ("ርዕስ:" የሚል ቃል አይጻፉ)።
2. መነሻ: የመጀመሪያውን አንቀጽ "አዲስ አበባ — " በሚል ይጀምሩ።
3. መዋቅር:
   - ዋና መግቢያ: ጉዳዩ ምን እንደሆነ፣ የሚመለከተውን ተቋም እና ፋይዳውን በአጭሩ።
   - ዋና ዋና ዝርዝሮች: የጨረታ/ስራ መለያ ቁጥር (Ref No)፣ የማጠናቀቂያ ቀን፣ የበጀት ወይም የዋስትና መጠን እና ቅድመ-ሁኔታዎችን በግልጽ ያብራሩ።
   - ቀጣይ እርምጃዎች: ፍላጎት ያላቸው አካላት እንዴት ማመልከት ወይም ሰነድ መግዛት እንደሚችሉ።
4. የቋንቋ ጥራት: ጥርት ያለ፣ ይፋዊ እና የጋዜጠኝነት ደረጃውን የጠበቀ የአማርኛ ቋንቋ።
5. እውነታዎች: ሁሉንም ቁጥሮች፣ ቀናት እና የስም ዝርዝሮች በትክክል ይጠብቁ። የሌለ መረጃ አይጨምሩ።
6. ርዝመት: ከ150 እስከ 300 ቃላት።

የጥሬ መረጃ ምንጭ:
{content}
"""

TRANSLATE_TO_AM_PROMPT = """You are an expert bilingual English-to-Amharic translator specializing in business, legal tenders, and institutional announcements.
Translate the following English article into natural, fluent, and professional Amharic.

Guidelines:
- Maintain the original meaning, journalistic cadence, and structure.
- Accurately preserve all figures, currencies (ETB/USD), reference codes, dates, and organizational names.
- Output ONLY the translated Amharic text, with no introductory or meta comments.

ENGLISH TEXT:
{content}
"""

TRANSLATE_TO_EN_PROMPT = """You are an expert bilingual Amharic-to-English translator specializing in business, government procurement, and economic news.
Translate the following Amharic article into fluent, professional, and clear English.

Guidelines:
- Maintain the professional news tone and factual accuracy.
- Accurately translate Amharic organizational titles and terms while preserving specific reference numbers and dates.
- Output ONLY the translated English text, with no introductory or meta comments.

AMHARIC TEXT:
{content}
"""


class NewsTranscriber:
    """
    Rewrites raw intelligence items into professional news articles
    and translates between English and Amharic using Gemini.
    """

    PRIMARY_MODEL = getattr(settings, 'GEMINI_TRANSCRIBE_MODEL', 'gemini-3.5-transcribe')
    FALLBACK_MODELS = ['gemini-2.5-flash', 'gemini-3.5-flash', 'gemini-flash-latest']

    def __init__(self, model_name: Optional[str] = None):
        self.preferred_model = model_name or getattr(settings, 'GEMINI_TRANSCRIBE_MODEL', 'gemini-3.5-transcribe')
        # Build candidate list: preferred first, then fallbacks without duplicates
        self.candidate_models = []
        for m in [self.preferred_model] + self.FALLBACK_MODELS:
            if m and m not in self.candidate_models:
                self.candidate_models.append(m)

    def _generate_with_client(self, api_key: str, model: str, prompt: str) -> Optional[str]:
        """Tries generating content using google.genai client, then google.generativeai."""
        # 1. Try modern google.genai
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            if resp and resp.text and resp.text.strip():
                return resp.text.strip()
            logger.info(f"Model '{model}' returned empty text. Trying next candidate model.")
        except Exception as e_genai:
            err_str = str(e_genai).lower()
            if any(kw in err_str for kw in ['quota', 'rate', '429', 'exceeded', 'resource_exhausted', 'billing']):
                raise e_genai
            logger.debug(f"google.genai call with model {model} failed: {e_genai}")

        # 2. Try legacy google.generativeai as backup SDK
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            model_instance = legacy_genai.GenerativeModel(model)
            resp = model_instance.generate_content(prompt)
            if resp and resp.text and resp.text.strip():
                return resp.text.strip()
        except Exception as e_legacy:
            err_str = str(e_legacy).lower()
            if any(kw in err_str for kw in ['quota', 'rate', '429', 'exceeded', 'resource_exhausted', 'billing']):
                raise e_legacy
            logger.debug(f"google.generativeai call with model {model} failed: {e_legacy}")

        return None

    def _call(self, prompt: str) -> Tuple[Optional[str], str]:
        """
        Calls Gemini with circular key rotation and automatic model fallback.
        Returns: (generated_text, model_name_used)
        """
        if GeminiKeyRotator.all_exhausted():
            logger.warning("NewsTranscriber: All Gemini keys exhausted.")
            return None, "exhausted"

        total_keys = len(GeminiKeyRotator._keys) or 1

        for _ in range(total_keys):
            api_key = GeminiKeyRotator.get_current_key()
            if not api_key:
                break

            # Try candidate models in order (e.g. gemini-3.5-transcribe -> gemini-2.0-flash -> gemini-1.5-flash)
            for model_name in self.candidate_models:
                try:
                    text = self._generate_with_client(api_key, model_name, prompt)
                    if text:
                        return text, model_name
                except Exception as e:
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in ['quota', 'rate', '429', 'exceeded', 'resource_exhausted', 'billing']):
                        logger.warning(f"NewsTranscriber: Key hit quota ({e}). Rotating key.")
                        GeminiKeyRotator.mark_current_exhausted()
                        break  # Break model loop to rotate key
                    elif any(kw in err_str for kw in ['not found', '404', 'unsupported', 'invalid_argument']):
                        logger.info(f"NewsTranscriber: Model '{model_name}' not available for text generation ({e}). Trying next model.")
                        continue
                    else:
                        logger.error(f"NewsTranscriber error on model {model_name}: {e}")
                        continue

        return None, "none"

    # ------------------------------------------------------------------ #
    #  Public Action Methods                                             #
    # ------------------------------------------------------------------ #

    def rewrite_as_news_english(self, content: str) -> Tuple[Optional[str], str]:
        """Rewrites raw content into a professional English news article."""
        prompt = NEWS_EN_PROMPT.format(content=content[:4500])
        return self._call(prompt)

    def rewrite_as_news_amharic(self, content: str) -> Tuple[Optional[str], str]:
        """Rewrites raw content into a professional Amharic news article."""
        prompt = NEWS_AM_PROMPT.format(content=content[:4500])
        return self._call(prompt)

    def translate_to_amharic(self, english_text: str) -> Tuple[Optional[str], str]:
        """Translates English text to fluent Amharic."""
        prompt = TRANSLATE_TO_AM_PROMPT.format(content=english_text[:4500])
        return self._call(prompt)

    def translate_to_english(self, amharic_text: str) -> Tuple[Optional[str], str]:
        """Translates Amharic text to fluent English."""
        prompt = TRANSLATE_TO_EN_PROMPT.format(content=amharic_text[:4500])
        return self._call(prompt)

    def transcribe(self, content: str, mode: str = 'both', existing_en: str = '', existing_am: str = '') -> Dict[str, Any]:
        """
        Executes news generation or translation based on selected mode:
          - 'both': Generates both English & Amharic news versions
          - 'news_en': Creates/refreshes English news article
          - 'news_am': Creates/refreshes Amharic news article
          - 'translate_am': Translates existing/source text to Amharic
          - 'translate_en': Translates existing/source text to English

        Returns:
            dict: {
                'english': str,
                'amharic': str,
                'mode': str,
                'model_used': str,
                'success': bool
            }
        """
        result = {
            'english': existing_en,
            'amharic': existing_am,
            'mode': mode,
            'model_used': self.preferred_model,
            'success': False
        }

        if mode == 'both':
            # Submit EN and AM rewrites in parallel — they are independent Gemini calls
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_en = executor.submit(self.rewrite_as_news_english, content)
                future_am = executor.submit(self.rewrite_as_news_amharic, content)
                en_text, model_en = future_en.result()
                am_text, model_am = future_am.result()

            if en_text:
                result['english'] = en_text
                result['model_used'] = model_en
            else:
                result['model_used'] = model_am

            if am_text:
                result['amharic'] = am_text
            elif en_text:
                # Amharic generation failed — fall back to translating the English result
                am_fallback, _ = self.translate_to_amharic(en_text)
                result['amharic'] = am_fallback or ""

            result['success'] = bool(result['english'] or result['amharic'])

        elif mode == 'news_en':
            en_text, model_used = self.rewrite_as_news_english(content)
            result['english'] = en_text or existing_en
            result['model_used'] = model_used
            result['success'] = bool(en_text)

        elif mode == 'news_am':
            am_text, model_used = self.rewrite_as_news_amharic(content)
            result['amharic'] = am_text or existing_am
            result['model_used'] = model_used
            result['success'] = bool(am_text)

        elif mode == 'translate_am':
            source_for_am = existing_en or content
            am_text, model_used = self.translate_to_amharic(source_for_am)
            result['amharic'] = am_text or existing_am
            result['model_used'] = model_used
            result['success'] = bool(am_text)

        elif mode == 'translate_en':
            source_for_en = existing_am or content
            en_text, model_used = self.translate_to_english(source_for_en)
            result['english'] = en_text or existing_en
            result['model_used'] = model_used
            result['success'] = bool(en_text)

        return result
