import sys
import shutil
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from core.models import DatabaseLock
from connectors.models import InformationSource
from intelligence.models import CollectedItem

class Command(BaseCommand):
    help = "Performs an automated health check of system services, databases, and connectors."

    def handle(self, *args, **options):
        self.stdout.write("=== System Diagnostic Health Check ===")
        all_ok = True

        # 1. Database
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.stdout.write(self.style.SUCCESS("[OK] Database connection active."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Database connection failed: {e}"))
            all_ok = False

        # 2. Disk Space
        try:
            total, used, free = shutil.disk_usage(settings.BASE_DIR)
            free_gb = round(free / (1024**3), 2)
            if free_gb < 0.5:
                self.stdout.write(self.style.WARNING(f"[WARN] Low disk space: {free_gb} GB remaining."))
            else:
                self.stdout.write(self.style.SUCCESS(f"[OK] Disk space healthy: {free_gb} GB free."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Disk check error: {e}"))

        # 3. Connectors & Sources
        active_src_count = InformationSource.objects.filter(is_active=True).count()
        self.stdout.write(self.style.SUCCESS(f"[OK] Active information sources configured: {active_src_count}"))

        # 4. Ingestion Total
        item_count = CollectedItem.objects.count()
        self.stdout.write(self.style.SUCCESS(f"[OK] Total market intelligence records: {item_count}"))

        # 5. AI Configuration
        if getattr(settings, 'GEMINI_API_KEY', ''):
            self.stdout.write(self.style.SUCCESS("[OK] Google Gemini API Key configured."))
        else:
            self.stdout.write(self.style.WARNING("[NOTICE] GEMINI_API_KEY not set in .env; operating in rule-based heuristic mode."))

        if all_ok:
            self.stdout.write(self.style.SUCCESS("\nOverall Health: HEALTHY (Exit Code 0)"))
            sys.exit(0)
        else:
            self.stdout.write(self.style.ERROR("\nOverall Health: DEGRADED (Exit Code 1)"))
            sys.exit(1)
