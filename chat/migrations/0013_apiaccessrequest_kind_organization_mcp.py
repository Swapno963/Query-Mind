from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0012_alter_apiaccessrequest_options_alter_apikey_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="apiaccessrequest",
            name="kind",
            field=models.CharField(
                choices=[("api", "API key"), ("mcp", "MCP key")],
                default="api",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="product_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("chat", "Chat"),
                    ("api", "API"),
                    ("mcp", "MCP"),
                    ("both", "Chat and API"),
                ],
                default="",
                max_length=16,
            ),
        ),
    ]
