# apps/backup/middleware.py

from django.utils import timezone
from datetime import timedelta


class AutoBackupFallbackMiddleware:
    """
    اگر Scheduler از کار افتاده باشد، این middleware
    در اولین ورود روز، بکاپ می‌گیرد.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._last_check = None

    def __call__(self, request):
        if request.user.is_authenticated:
            now = timezone.now()
            # هر ۳۰ دقیقه یک بار چک کن
            if self._last_check is None or (now - self._last_check) > timedelta(minutes=30):
                self._last_check = now
                self._check_and_backup()

        return self.get_response(request)

    def _check_and_backup(self):
        try:
            from apps.backup.models import Backup, AutoBackupSetting
            from apps.backup.utils import auto_backup_if_needed

            settings_obj = AutoBackupSetting.get_settings()
            if not settings_obj.enabled:
                return

            # اگر امروز بکاپ خودکار نگرفته‌ایم، حالا بگیر
            today = timezone.now().date()
            already = Backup.objects.filter(
                created_at__date=today,
                trigger='auto'
            ).exists()

            if not already:
                auto_backup_if_needed()

        except Exception as e:
            print(f'⚠️ خطا در middleware بکاپ: {e}')