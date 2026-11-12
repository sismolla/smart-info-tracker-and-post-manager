import logging
import requests
from django.conf import settings
from intelligence.models import CollectedItem

logger = logging.getLogger(__name__)

class TelegramAlertDispatcher:
    """
    Dispatches instant push alert notifications to Telegram channels, executive groups,
    or individual decision-makers when high-priority intelligence is approved or discovered.
    """

    @classmethod
    def send_alert(cls, item: CollectedItem, force: bool = False) -> bool:
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        chat_id = getattr(settings, 'TELEGRAM_ALERT_CHAT_ID', '')
        min_score = getattr(settings, 'TELEGRAM_ALERT_MIN_SCORE', 75)

        if not bot_token or not chat_id:
            logger.debug("Telegram alert skipped: bot_token or chat_id not configured.")
            return False

        score = item.ai_analysis.relevance_score if hasattr(item, 'ai_analysis') and item.ai_analysis else 50
        if not force and score < min_score:
            logger.debug(f"Item #{item.id} score {score} below alert threshold {min_score}.")
            return False

        entities = getattr(item, 'entities', None)
        analysis = getattr(item, 'ai_analysis', None)

        org = entities.organization if entities and entities.organization else "Unspecified Org"
        ref = f"🏷️ *Ref:* `{entities.reference_number}`\n" if entities and entities.reference_number else ""
        
        financial_line = ""
        if entities:
            if entities.estimated_budget:
                financial_line += f"💰 *Budget:* {entities.estimated_budget}\n"
            if entities.bid_bond_amount:
                financial_line += f"🛡️ *Bid Bond:* {entities.bid_bond_amount}\n"
            if entities.salary_min:
                financial_line += f"💵 *Salary:* {entities.salary_min}\n"

        deadline_line = ""
        if entities and (entities.deadline_iso or entities.tender_deadline or entities.application_deadline):
            dl = entities.deadline_iso or entities.tender_deadline or entities.application_deadline
            deadline_line = f"⏰ *Deadline:* {dl}\n"

        summary = analysis.short_summary if analysis and analysis.short_summary else item.title

        msg = (
            f"🚨 *MARKET INTELLIGENCE ALERT*\n\n"
            f"📌 *{item.title}*\n"
            f"🏢 *Org:* {org}\n"
            f"{ref}"
            f"{financial_line}"
            f"{deadline_line}"
            f"📊 *Relevance:* {score}/100\n\n"
            f"📝 *Summary:* {summary}\n\n"
            f"🔗 [View Source Link]({item.canonical_url or 'https://marketintel.org'})\n"
            f"⚙️ *Source:* {item.source.name}"
        )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': msg,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False,
        }

        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200 and resp.json().get('ok'):
                logger.info(f"Sent Telegram push alert for Item #{item.id} to {chat_id}")
                return True
            else:
                logger.warning(f"Telegram alert failed: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Error dispatching Telegram alert: {e}")
            return False
