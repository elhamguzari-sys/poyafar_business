import os
from django.db import models


class Backup(models.Model):
    """تاریخچه بکاپ‌های سیستم"""

    BACKUP_TYPES = [
        ('db', 'فقط دیتابیس'),
        ('full', 'کامل (دیتابیس + مدیا)'),
    ]

    TRIGGER_TYPES = [
        ('manual', 'دستی'),
        ('auto', 'خودکار'),
    ]

    name = models.CharField(max_length=255, verbose_name="نام فایل")
    file_path = models.CharField(max_length=500, verbose_name="مسیر فایل")
    file_size = models.BigIntegerField(default=0, verbose_name="حجم (بایت)")
    backup_type = models.CharField(
        max_length=20, choices=BACKUP_TYPES, default='full',
        verbose_name="نوع بکاپ"
    )
    trigger = models.CharField(
        max_length=20, choices=TRIGGER_TYPES, default='manual',
        verbose_name="نحوه ساخت"
    )
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ساخت")

    class Meta:
        verbose_name = "بکاپ"
        verbose_name_plural = "بکاپ‌ها"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.created_at.strftime('%Y/%m/%d %H:%M')}"

    @property
    def file_size_mb(self):
        if not self.file_size:
            return 0
        return round(self.file_size / (1024 * 1024), 2)

    @property
    def file_exists(self):
        return os.path.isfile(self.file_path)

    def delete(self, *args, **kwargs):
        if self.file_exists:
            try:
                os.remove(self.file_path)
            except Exception:
                pass
        super().delete(*args, **kwargs)


class AutoBackupSetting(models.Model):
    """تنظیمات بکاپ خودکار"""
    enabled = models.BooleanField(default=True, verbose_name="فعال")
    hour = models.IntegerField(default=10, verbose_name="ساعت")
    minute = models.IntegerField(default=0, verbose_name="دقیقه")
    include_media = models.BooleanField(default=True, verbose_name="شامل مدیا")
    keep_days = models.IntegerField(default=30, verbose_name="نگهداری (روز)")
    keep_count = models.IntegerField(default=20, verbose_name="حداقل تعداد نگهداری")
    last_run = models.DateTimeField(null=True, blank=True, verbose_name="آخرین اجرا")

    class Meta:
        verbose_name = "تنظیمات بکاپ خودکار"
        verbose_name_plural = "تنظیمات بکاپ خودکار"

    def __str__(self):
        return f"بکاپ خودکار ساعت {self.hour:02d}:{self.minute:02d}"

    @classmethod
    def get_settings(cls):
        """دریافت یا ساخت تنظیمات پیش‌فرض"""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj