# apps/backup/scheduler.py

import threading
import time
from datetime import datetime, timedelta
from django.utils import timezone


_scheduler_started = False


def start_scheduler():
    """شروع Scheduler در یک Thread جداگانه"""
    global _scheduler_started
    if _scheduler_started:
        return

    _scheduler_started = True

    thread = threading.Thread(target=_scheduler_loop, daemon=True, name='AutoBackupScheduler')
    thread.start()
    print('✅ Scheduler بکاپ خودکار شروع شد — ساعت ۱۰:۰۰ هر روز')


def _scheduler_loop():
    """حلقه اصلی — هر دقیقه چک کن"""
    from apps.backup.utils import auto_backup_if_needed
    from apps.backup.models import AutoBackupSetting

    while True:
        try:
            now = timezone.localtime(timezone.now())
            settings_obj = AutoBackupSetting.get_settings()

            if not settings_obj.enabled:
                time.sleep(60)
                continue

            # چک ساعت و دقیقه
            target_hour = settings_obj.hour
            target_minute = settings_obj.minute

            if now.hour == target_hour and now.minute == target_minute:
                # جلوگیری از اجرای چندباره در همان دقیقه
                last_run = settings_obj.last_run
                if last_run:
                    last_run_local = timezone.localtime(last_run)
                    if (last_run_local.year == now.year and
                        last_run_local.month == now.month and
                        last_run_local.day == now.day and
                        last_run_local.hour == now.hour):
                        # قبلاً در این ساعت اجرا شده
                        time.sleep(60)
                        continue

                # اجرای بکاپ
                print(f'⏰ [Scheduler] زمان بکاپ خودکار — {now.strftime("%Y/%m/%d %H:%M")}')
                success, msg = auto_backup_if_needed()
                if success:
                    print(f'✅ [Scheduler] {msg}')
                else:
                    print(f'ℹ️ [Scheduler] {msg}')

                # کمی توقف برای جلوگیری از تکرار
                time.sleep(120)
            else:
                time.sleep(30)

        except Exception as e:
            print(f'⚠️ [Scheduler] خطا: {e}')
            time.sleep(60)