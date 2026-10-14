from django.db import migrations
from django.db.migrations.recorder import MigrationRecorder

# Left by SimpleJWT's blacklist app, removed in 0003's release (decision 016). Their rows point at users, and with
# the app gone nothing deletes them first, so deleting such a user failed (Codex review of #46).
TABLES = ['token_blacklist_blacklistedtoken', 'token_blacklist_outstandingtoken']   # the first points at the second


def drop_blacklist_tables(apps, schema_editor):
    existing = set(schema_editor.connection.introspection.table_names())
    for table in TABLES:
        if table in existing:
            schema_editor.execute(f'DROP TABLE {schema_editor.quote_name(table)}')
    # Forget its migrations too: rolled back to the code that still has the app, `migrate` builds them again.
    MigrationRecorder(schema_editor.connection).migration_qs.filter(app='token_blacklist').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_loginsession'),
    ]

    # Backwards there's nothing to do: the old code's own `migrate` creates its tables, empty.
    operations = [
        migrations.RunPython(drop_blacklist_tables, migrations.RunPython.noop),
    ]
