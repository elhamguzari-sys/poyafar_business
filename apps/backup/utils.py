import os
import zipfile
import sqlite3
import shutil
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def get_backup_dir():
    """پوشه ذخیره بکاپ‌ها"""
    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def get_media_dir():
    """پوشه مدیا"""
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if media_root and os.path.isdir(media_root):
        return media_root
    fallback = os.path.join(settings.BASE_DIR, 'media')
    return fallback if os.path.isdir(fallback) else None


def get_db_path():
    """مسیر دیتابیس"""
    return settings.DATABASES['default']['NAME']


def format_size(bytes_val):
    """تبدیل حجم به فرمت خوانا"""
    if bytes_val < 1024:
        return f'{bytes_val} B'
    elif bytes_val < 1024 * 1024:
        return f'{round(bytes_val / 1024, 1)} KB'
    elif bytes_val < 1024 * 1024 * 1024:
        return f'{round(bytes_val / (1024 * 1024), 2)} MB'
    return f'{round(bytes_val / (1024 * 1024 * 1024), 2)} GB'


def safe_sqlite_backup(src_path, dest_path):
    """کپی امن دیتابیس SQLite (بدون قفل شدن)"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dest_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


# ═══════════════════════════════════════════════════════════
# ساخت بکاپ کامل (ZIP: دیتابیس + مدیا)
# ═══════════════════════════════════════════════════════════

def create_full_backup(prefix='poyafar', note='', include_media=True,
                        include_settings=False, trigger='manual'):
    """ساخت بکاپ کامل در یک فایل ZIP"""
    from .models import Backup

    backup_dir = get_backup_dir()
    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return False, f'دیتابیس پیدا نشد: {db_path}', None

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    zip_name = f'{prefix}_{ts}.zip'
    zip_path = os.path.join(backup_dir, zip_name)

    # پوشه موقت
    temp_dir = os.path.join(backup_dir, f'_temp_{ts}')
    os.makedirs(temp_dir, exist_ok=True)
    temp_db = os.path.join(temp_dir, 'db.sqlite3')

    try:
        # ─── ۱. بکاپ امن دیتابیس ───
        safe_sqlite_backup(db_path, temp_db)

        # ─── ۲. ساخت ZIP ───
        media_dir = get_media_dir()
        media_count = 0
        media_size = 0

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # دیتابیس
            zf.write(temp_db, 'database/db.sqlite3')

            # مدیا
            if include_media and media_dir:
                for root, dirs, files in os.walk(media_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for file in files:
                        if file.startswith('.'):
                            continue
                        filepath = os.path.join(root, file)
                        rel_path = os.path.relpath(filepath, media_dir)
                        arcname = os.path.join('media', rel_path)
                        try:
                            zf.write(filepath, arcname)
                            media_count += 1
                            media_size += os.path.getsize(filepath)
                        except Exception:
                            pass

            # تنظیمات (اختیاری)
            if include_settings:
                for candidate in [
                    os.path.join(settings.BASE_DIR, 'poyafar_business', 'settings.py'),
                    os.path.join(settings.BASE_DIR, 'poyafar', 'settings.py'),
                    os.path.join(settings.BASE_DIR, 'config', 'settings.py'),
                ]:
                    if os.path.isfile(candidate):
                        zf.write(candidate, 'config/settings.py')
                        break

            # README
            readme = _build_readme(
                media_count=media_count,
                media_size=media_size,
                include_media=include_media,
                trigger=trigger,
            )
            zf.writestr('README.txt', readme)

        # ─── ۳. حذف موقت ───
        shutil.rmtree(temp_dir, ignore_errors=True)

        # ─── ۴. ثبت در دیتابیس ───
        zip_size = os.path.getsize(zip_path)

        final_note = note or 'بکاپ کامل'
        if media_count > 0:
            final_note += f' — {media_count} فایل مدیا'
        if trigger == 'auto':
            final_note = '⏰ بکاپ خودکار روزانه — ' + final_note

        backup = Backup.objects.create(
            name=zip_name,
            file_path=zip_path,
            file_size=zip_size,
            backup_type='full',
            trigger=trigger,
            note=final_note,
        )

        return True, f'بکاپ کامل ساخته شد: {zip_name} ({format_size(zip_size)})', backup

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        return False, f'خطا در ساخت بکاپ: {str(e)}', None


# ═══════════════════════════════════════════════════════════
# بکاپ فقط دیتابیس
# ═══════════════════════════════════════════════════════════

def create_db_backup(prefix='poyafar', note='', trigger='manual'):
    """بکاپ فقط دیتابیس"""
    from .models import Backup

    backup_dir = get_backup_dir()
    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return False, 'دیتابیس پیدا نشد', None

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'{prefix}_db_{ts}.sqlite3'
    dest = os.path.join(backup_dir, filename)

    try:
        safe_sqlite_backup(db_path, dest)
        size = os.path.getsize(dest)

        backup = Backup.objects.create(
            name=filename,
            file_path=dest,
            file_size=size,
            backup_type='db',
            trigger=trigger,
            note=note or 'بکاپ فقط دیتابیس',
        )
        return True, f'بکاپ دیتابیس: {filename} ({format_size(size)})', backup

    except Exception as e:
        return False, f'خطا: {str(e)}', None


# ═══════════════════════════════════════════════════════════
# بازیابی
# ═══════════════════════════════════════════════════════════

def restore_from_zip(backup_obj, restore_media=False):
    """بازیابی از فایل ZIP"""
    if not os.path.isfile(backup_obj.file_path):
        return False, 'فایل بکاپ پیدا نشد.'

    backup_dir = get_backup_dir()
    db_path = get_db_path()

    try:
        # ۱. بکاپ ایمنی
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        safety_name = f'safety_before_restore_{ts}.sqlite3'
        safety_path = os.path.join(backup_dir, safety_name)
        if os.path.isfile(db_path):
            shutil.copy2(db_path, safety_path)

        # ۲. استخراج
        extract_dir = os.path.join(backup_dir, f'_restore_{ts}')
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(backup_obj.file_path, 'r') as zf:
            zf.extractall(extract_dir)

        # ۳. بازیابی دیتابیس
        extracted_db = os.path.join(extract_dir, 'database', 'db.sqlite3')
        if not os.path.isfile(extracted_db):
            shutil.rmtree(extract_dir, ignore_errors=True)
            return False, 'فایل دیتابیس در ZIP پیدا نشد.'

        shutil.copy2(extracted_db, db_path)

        # ۴. بازیابی مدیا (اختیاری)
        media_msg = ''
        if restore_media:
            extracted_media = os.path.join(extract_dir, 'media')
            if os.path.isdir(extracted_media):
                media_dir = get_media_dir()
                if media_dir:
                    count = 0
                    for root, dirs, files in os.walk(extracted_media):
                        for file in files:
                            src = os.path.join(root, file)
                            rel = os.path.relpath(src, extracted_media)
                            dst = os.path.join(media_dir, rel)
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            shutil.copy2(src, dst)
                            count += 1
                    media_msg = f' — {count} فایل مدیا بازیابی شد'

        shutil.rmtree(extract_dir, ignore_errors=True)
        return True, f'بازیابی موفق. بکاپ ایمنی: {safety_name}{media_msg}'

    except Exception as e:
        return False, f'خطا در بازیابی: {str(e)}'


def restore_from_sqlite(backup_obj):
    """بازیابی از فایل sqlite3"""
    if not os.path.isfile(backup_obj.file_path):
        return False, 'فایل بکاپ پیدا نشد.'

    try:
        db_path = get_db_path()
        backup_dir = get_backup_dir()
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        safety_name = f'safety_before_restore_{ts}.sqlite3'
        safety_path = os.path.join(backup_dir, safety_name)

        if os.path.isfile(db_path):
            shutil.copy2(db_path, safety_path)

        shutil.copy2(backup_obj.file_path, db_path)
        return True, f'بازیابی موفق. بکاپ ایمنی: {safety_name}'

    except Exception as e:
        return False, f'خطا: {str(e)}'


# ═══════════════════════════════════════════════════════════
# پاکسازی خودکار
# ═══════════════════════════════════════════════════════════

def cleanup_old_backups(keep_days=30, keep_count=20):
    """حذف بکاپ‌های قدیمی"""
    from .models import Backup

    cutoff = timezone.now() - timedelta(days=keep_days)

    old = Backup.objects.filter(created_at__lt=cutoff).order_by('-created_at')[keep_count:]

    deleted = 0
    for b in old:
        b.delete()
        deleted += 1
    return deleted


# ═══════════════════════════════════════════════════════════
# بکاپ خودکار — چک و اجرا
# ═══════════════════════════════════════════════════════════

def auto_backup_if_needed():
    """اگر امروز بکاپ خودکار نگرفته‌ایم، بگیر"""
    from .models import Backup, AutoBackupSetting

    settings_obj = AutoBackupSetting.get_settings()
    if not settings_obj.enabled:
        return False, 'بکاپ خودکار غیرفعال است'

    today = timezone.now().date()

    # چک امروز
    already_done = Backup.objects.filter(
        created_at__date=today,
        trigger='auto'
    ).exists()

    if already_done:
        return False, 'امروز قبلاً بکاپ گرفته شده'

    # بکاپ جدید
    success, msg, _ = create_full_backup(
        prefix='poyafar_auto',
        note='بکاپ خودکار روزانه',
        include_media=settings_obj.include_media,
        trigger='auto',
    )

    if success:
        # آپدیت last_run
        settings_obj.last_run = timezone.now()
        settings_obj.save(update_fields=['last_run'])

        # پاکسازی خودکار
        cleanup_old_backups(
            keep_days=settings_obj.keep_days,
            keep_count=settings_obj.keep_count,
        )

    return success, msg


# ═══════════════════════════════════════════════════════════
# README Builder
# ═══════════════════════════════════════════════════════════

def _build_readme(media_count, media_size, include_media, trigger='manual'):
    return f"""════════════════════════════════════════════════════════════
   بکاپ کامل سیستم پویافر (Poyafar Business)
════════════════════════════════════════════════════════════

📅 تاریخ بکاپ: {datetime.now().strftime('%Y/%m/%d - %H:%M:%S')}
🐍 نسخه جنگو: {__import__('django').get_version()}
💾 نوع دیتابیس: SQLite
📦 شامل مدیا: {'بله' if include_media else 'خیر'} ({media_count} فایل، {format_size(media_size)})
🔔 نحوه ساخت: {'خودکار' if trigger == 'auto' else 'دستی'}


────────────────────────────────────────────────────────────
📁 محتویات این فایل ZIP:
────────────────────────────────────────────────────────────

  database/
    └── db.sqlite3          ← دیتابیس کامل

  media/                    ← عکس‌ها و فایل‌ها
    ├── products/
    ├── employees/
    ├── expenses/
    └── transaction_image/

  config/                   ← (اگر باشد)
    └── settings.py


────────────────────────────────────────────────────────────
🔧 راهنمای بازیابی:
────────────────────────────────────────────────────────────

  روش ۱ — از داخل برنامه:
    ۱. به صفحه /backup/ بروید
    ۲. روی دکمه «بازیابی» کلیک کنید

  روش ۲ — دستی:
    ۱. فایل ZIP را استخراج کنید
    ۲. db.sqlite3 را به ریشه پروژه کپی کنید
    ۳. پوشه media را به ریشه پروژه کپی کنید
    ۴. سرور را ری‌استارت کنید


────────────────────────────────────────────────────────────
🏢 شرکت نرم‌افزاری پویافر
📧 poyafar@yahoo.com | 📞 +93794483138
📍 کابل، افغانستان
────────────────────────────────────────────────────────────
"""