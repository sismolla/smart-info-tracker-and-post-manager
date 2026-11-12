import re
import hashlib
import logging
from typing import Tuple, Optional
from django.utils import timezone
from .models import CollectedItem, DuplicateGroup

logger = logging.getLogger(__name__)

def normalize_text_for_hash(text: str) -> str:
    """Removes punctuation, lowercases, and condenses whitespace for canonical hashing."""
    if not text:
        return ""
    cleaned = re.sub(r'[^\w\s]', '', text.lower())
    return " ".join(cleaned.split())

def compute_content_hash(text: str) -> str:
    norm = normalize_text_for_hash(text)
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()

def extract_quick_reference_number(text: str) -> Optional[str]:
    """Extracts Bid Reference Number or Tender Code for deterministic matching."""
    match = re.search(
        r'(?:(?:bid|tender|ref)\s*(?:reference\s*no\.?|ref\s*no\.?|reference|ref|no\.?)|የጨረታ\s*ቁጥር)\s*[:#]?\s*([A-Za-z0-9/\-_.]+)',
        text,
        re.IGNORECASE
    )
    return match.group(1).strip() if match else None

def get_word_shingles(text: str, n: int = 3) -> set:
    """Extracts word n-grams (shingles) for similarity comparison."""
    words = normalize_text_for_hash(text).split()
    if len(words) < n:
        return set(words)
    return set(" ".join(words[i:i+n]) for i in range(len(words) - n + 1))

def jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return intersection / union if union > 0 else 0.0

class DeduplicationEngine:
    """
    Multi-tier deduplication engine for market intelligence data:
      Tier 1: O(1) Exact SHA-256 hash match.
      Tier 2: Semantic Reference Number Match (100% deterministic cross-lingual matching e.g. Amharic vs English).
      Tier 3: Fuzzy Jaccard n-gram similarity against recent candidates.
    """

    SIMILARITY_THRESHOLD = 0.72

    @classmethod
    def check_and_cluster(cls, item: CollectedItem, time_window_days: int = 45) -> Tuple[bool, Optional[DuplicateGroup]]:
        """
        Evaluates whether an item is a duplicate.
        If duplicate, assigns item to DuplicateGroup, sets item.is_primary_duplicate = False,
        and marks status = 'duplicate'.
        Returns (is_duplicate: bool, group: DuplicateGroup).
        """
        content_hash = compute_content_hash(item.original_content)
        item.content_hash = content_hash
        since = timezone.now() - timezone.timedelta(days=time_window_days)

        # 1. Tier 1: Exact Hash Match
        exact_match = CollectedItem.objects.filter(
            content_hash=content_hash,
            collected_at__gte=since
        ).exclude(id=item.id).first()

        if exact_match:
            group = exact_match.duplicate_group
            if not group:
                group = DuplicateGroup.objects.create(
                    canonical_hash=content_hash,
                    primary_item=exact_match,
                    similarity_score=1.0
                )
                exact_match.duplicate_group = group
                exact_match.is_primary_duplicate = True
                exact_match.save(update_fields=['duplicate_group', 'is_primary_duplicate'])

            item.duplicate_group = group
            item.is_primary_duplicate = False
            item.status = 'duplicate'
            item.save(update_fields=['content_hash', 'duplicate_group', 'is_primary_duplicate', 'status'])
            logger.info(f"Item #{item.id} matched exact duplicate of #{exact_match.id}")
            return True, group

        # 2. Tier 2: Semantic Reference Number Match (e.g. EPSA/MOH/NCB/2026/042)
        # Guarantees cross-lingual matching (e.g. Amharic Telegram post vs English Web post)
        ref_no = None
        if hasattr(item, 'entities') and item.entities and item.entities.reference_number:
            ref_no = item.entities.reference_number
        else:
            ref_no = extract_quick_reference_number(item.original_content)

        if ref_no and len(ref_no) >= 5:
            ref_match = CollectedItem.objects.filter(
                entities__reference_number__iexact=ref_no,
                collected_at__gte=since
            ).exclude(id=item.id).first()

            if ref_match:
                group = ref_match.duplicate_group
                if not group:
                    group = DuplicateGroup.objects.create(
                        canonical_hash=content_hash,
                        primary_item=ref_match,
                        similarity_score=1.0
                    )
                    ref_match.duplicate_group = group
                    ref_match.save(update_fields=['duplicate_group'])

                item.duplicate_group = group
                item.is_primary_duplicate = False
                item.status = 'duplicate'
                item.save(update_fields=['content_hash', 'duplicate_group', 'is_primary_duplicate', 'status'])
                logger.info(f"Item #{item.id} matched cross-source duplicate via Reference Number '{ref_no}' with #{ref_match.id}")
                return True, group

        # 3. Tier 3: Fuzzy / Near-Duplicate Match
        item_shingles = get_word_shingles(item.original_content, n=3)
        if len(item_shingles) >= 5:
            candidates = CollectedItem.objects.filter(
                is_primary_duplicate=True,
                collected_at__gte=since
            ).exclude(id=item.id).only('id', 'original_content', 'duplicate_group')[:100]

            for cand in candidates:
                cand_shingles = get_word_shingles(cand.original_content, n=3)
                sim = jaccard_similarity(item_shingles, cand_shingles)
                if sim >= cls.SIMILARITY_THRESHOLD:
                    group = cand.duplicate_group
                    if not group:
                        group = DuplicateGroup.objects.create(
                            canonical_hash=content_hash,
                            primary_item=cand,
                            similarity_score=round(sim, 3)
                        )
                        cand.duplicate_group = group
                        cand.save(update_fields=['duplicate_group'])

                    item.duplicate_group = group
                    item.is_primary_duplicate = False
                    item.status = 'duplicate'
                    item.save(update_fields=['content_hash', 'duplicate_group', 'is_primary_duplicate', 'status'])
                    logger.info(f"Item #{item.id} matched near-duplicate of #{cand.id} (Similarity: {sim:.2f})")
                    return True, group

        item.is_primary_duplicate = True
        if item.status == 'ingested':
            item.status = 'dedup_checked'
        item.save(update_fields=['content_hash', 'is_primary_duplicate', 'status'])
        return False, None
