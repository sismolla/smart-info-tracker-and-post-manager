from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from intelligence.models import CollectedItem

class Command(BaseCommand):
    help = "Purges or auto-rejects existing collected items older than max_age_days (default: 3 days)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=3, help='Age threshold in days (default: 3)')
        parser.add_argument(
            '--action',
            type=str,
            choices=['reject', 'delete'],
            default='reject',
            help="'reject' sets status to rejected with notes; 'delete' completely removes from database."
        )

    def handle(self, *args, **options):
        days = options['days']
        action = options['action']
        cutoff = timezone.now() - timedelta(days=days)

        stale_qs = CollectedItem.objects.filter(published_at__lt=cutoff).exclude(status__in=['published', 'rejected'])
        total_stale = stale_qs.count()

        if total_stale == 0:
            self.stdout.write(self.style.SUCCESS(f"No active items found older than {days} days."))
            return

        self.stdout.write(f"Found {total_stale} item(s) published before {cutoff.strftime('%Y-%m-%d')} (> {days} days old).")

        if action == 'delete':
            count, _ = stale_qs.delete()
            self.stdout.write(self.style.SUCCESS(f"Successfully deleted {count} stale items."))
        else:
            updated = 0
            for item in stale_qs:
                age_days = (timezone.now() - item.published_at).total_seconds() / 86400.0
                item.status = 'rejected'
                item.editorial_notes = f"Auto-dropped: Article is {round(age_days, 1)} days old (published {item.published_at.strftime('%Y-%m-%d')}), exceeding {days}-day freshness limit."
                item.save(update_fields=['status', 'editorial_notes'])
                updated += 1
            self.stdout.write(self.style.SUCCESS(f"Successfully updated {updated} stale item(s) to 'rejected' status."))
