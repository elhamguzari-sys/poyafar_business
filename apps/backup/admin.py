from django.contrib import admin
from .models import Backup, AutoBackupSetting


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ('name', 'backup_type', 'trigger', 'file_size_mb', 'created_at')
    list_filter = ('backup_type', 'trigger', 'created_at')
    search_fields = ('name', 'note')
    readonly_fields = ('name', 'file_path', 'file_size', 'created_at')
    ordering = ('-created_at',)


@admin.register(AutoBackupSetting)
class AutoBackupSettingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'enabled', 'include_media', 'last_run')