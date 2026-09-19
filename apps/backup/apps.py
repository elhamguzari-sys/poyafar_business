from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.backup'
    verbose_name = 'پشتیبان‌گیری'

    def ready(self):
        # شروع scheduler وقتی اپ آماده شد
        import os
        if os.environ.get('RUN_MAIN') == 'true':
            try:
                from .scheduler import start_scheduler
                start_scheduler()
            except Exception as e:
                print(f'⚠️ خطا در شروع Scheduler: {e}')