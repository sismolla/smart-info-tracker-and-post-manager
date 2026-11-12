import re

AMHARIC_REGEX = re.compile(r'[\u1200-\u137F]')

def detect_language(text: str) -> str:
    """
    Detects if the text is primarily Amharic ('am'), English ('en'), or other.
    Checks Ethiopic script frequency.
    """
    if not text:
        return 'en'

    amharic_chars = len(AMHARIC_REGEX.findall(text))
    total_alpha = len(re.findall(r'\w', text))

    if total_alpha > 0 and (amharic_chars / total_alpha) > 0.15:
        return 'am'
    return 'en'
