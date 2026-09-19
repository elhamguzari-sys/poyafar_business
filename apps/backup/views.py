import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import FileResponse, Http404
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import Backup, AutoBackupSetting
from .utils import (
    create_full_backup,
    create_db_backup,
    restore_from_zip,
    restore_from_sqlite,
    auto_backup_if_needed,
)


def backup_list(request):
    """صفحه مدیریت بکاپ"""
    backups = Backup.objects.all()
    total_size = sum(b.file_size for b in backups)

    settings_obj = AutoBackupSetting.get_settings()

    context = {
        'backups': backups,
        'total_count': backups.count(),
        'full_count': backups.filter(backup_type='full').count(),
        'db_count': backups.filter(backup_type='db').count(),
        'auto_count': backups.filter(trigger='auto').count(),
        'total_size_mb': round(total_size / (1024 * 1024), 2),
        'auto_settings': settings_obj,
        'page_title': 'پشتیبان‌گیری',
    }
    return render(request, 'backup/backup_list.html', context)


@require_POST
def backup_create_full(request):
    """ساخت بکاپ کامل"""
    prefix = request.POST.get('prefix', 'poyafar').strip() or 'poyafar'
    note = request.POST.get('note', '').strip()
    include_media = request.POST.get('include_media') == 'on'
    include_settings = request.POST.get('include_settings') == 'on'

    success, msg, _ = create_full_backup(
        prefix=prefix,
        note=note,
        include_media=include_media,
        include_settings=include_settings,
        trigger='manual',
    )

    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect('backup_list')


@require_POST
def backup_create_db(request):
    """ساخت بکاپ فقط دیتابیس"""
    prefix = request.POST.get('prefix', 'poyafar').strip() or 'poyafar'
    note = request.POST.get('note', '').strip()

    success, msg, _ = create_db_backup(prefix=prefix, note=note, trigger='manual')

    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect('backup_list')


def backup_download(request, backup_id):
    """دانلود فایل بکاپ"""
    backup = get_object_or_404(Backup, id=backup_id)

    if not os.path.isfile(backup.file_path):
        raise Http404('فایل بکاپ پیدا نشد.')

    return FileResponse(
        open(backup.file_path, 'rb'),
        as_attachment=True,
        filename=backup.name,
    )


@require_POST
def backup_delete(request, backup_id):
    """حذف بکاپ"""
    backup = get_object_or_404(Backup, id=backup_id)
    name = backup.name
    backup.delete()
    messages.success(request, f'بکاپ "{name}" حذف شد.')
    return redirect('backup_list')


@require_POST
def backup_restore(request, backup_id):
    """بازیابی از بکاپ"""
    backup = get_object_or_404(Backup, id=backup_id)

    if not backup.file_exists:
        messages.error(request, 'فایل بکاپ پیدا نشد.')
        return redirect('backup_list')

    restore_media = request.POST.get('restore_media') == 'on'

    if backup.name.endswith('.zip'):
        success, msg = restore_from_zip(backup, restore_media=restore_media)
    elif backup.name.endswith('.sqlite3'):
        success, msg = restore_from_sqlite(backup)
    else:
        messages.error(request, 'فرمت فایل پشتیبانی نمی‌شود.')
        return redirect('backup_list')

    if success:
        messages.success(request, msg + ' — لطفاً سرور را ری‌استارت کنید.')
    else:
        messages.error(request, msg)

    return redirect('backup_list')


@require_POST
def backup_run_now(request):
    """اجرای فوری بکاپ خودکار (تست)"""
    success, msg = auto_backup_if_needed()

    if success:
        messages.success(request, f'✅ بکاپ خودکار اجرا شد: {msg}')
    else:
        messages.info(request, f'ℹ️ {msg}')

    return redirect('backup_list')


@require_POST
def update_auto_settings(request):
    """به‌روزرسانی تنظیمات بکاپ خودکار"""
    settings_obj = AutoBackupSetting.get_settings()

    try:
        settings_obj.enabled = request.POST.get('enabled') == 'on'
        settings_obj.hour = int(request.POST.get('hour', 10))
        settings_obj.minute = int(request.POST.get('minute', 0))
        settings_obj.include_media = request.POST.get('include_media') == 'on'
        settings_obj.keep_days = int(request.POST.get('keep_days', 30))
        settings_obj.keep_count = int(request.POST.get('keep_count', 20))
        settings_obj.save()

        messages.success(request, '✅ تنظیمات بکاپ خودکار به‌روزرسانی شد.')
    except Exception as e:
        messages.error(request, f'خطا: {str(e)}')

    return redirect('backup_list')