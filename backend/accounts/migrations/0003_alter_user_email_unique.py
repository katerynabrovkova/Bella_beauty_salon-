# Hand-written: split out of 0002 (see the comment at the top of that file)
# because Postgres refuses ALTER TABLE ... ADD CONSTRAINT UNIQUE in the same
# transaction as a preceding DELETE on the same table. This runs as its own
# migration/transaction, after 0002's delete has fully committed.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_user_managers_remove_user_username_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254, unique=True),
        ),
    ]
