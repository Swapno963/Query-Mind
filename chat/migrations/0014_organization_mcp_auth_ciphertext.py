from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0013_apiaccessrequest_kind_organization_mcp"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="mcp_auth_ciphertext",
            field=models.TextField(blank=True, default=""),
        ),
    ]
