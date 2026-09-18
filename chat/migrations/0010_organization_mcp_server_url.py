from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="mcp_server_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
    ]
