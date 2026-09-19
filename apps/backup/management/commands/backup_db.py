from django.core.management.base import BaseCommand
from apps.backup.utils import create_full_backup, cleanup_old_backups


class Command(BaseCommand):
    help = 'ساخت بکاپ از خط فرمان'

    def add_arguments(self, parser):
        parser.add_argument('--prefix', type=str, default='poyafar_cmd')
        parser.add_argument('--no-media', action='store_true')
        parser.add_argument('--keep-days', type=int, default=30)

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('🔄 در حال ساخت بکاپ...'))

        success, msg, _ = create_full_backup(
            prefix=options['prefix'],
            note='بکاپ از خط فرمان',
            include_media=not options['no_media'],
            trigger='manual',
        )

        if success:
            self.stdout.write(self.style.SUCCESS(f'✅ {msg}'))
            deleted = cleanup_old_backups(keep_days=options['keep_days'])
            if deleted:
                self.stdout.write(self.style.WARNING(f'🗑️ {deleted} بکاپ قدیمی حذف شد'))
        else:
            self.stdout.write(self.style.ERROR(f'❌ {msg}'))