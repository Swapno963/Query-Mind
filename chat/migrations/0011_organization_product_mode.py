from django.db import migrations, models


def seed_product_mode(apps, schema_editor):
    Organization = apps.get_model("chat", "Organization")
    WorkspaceConnection = apps.get_model("connections", "WorkspaceConnection")
    for org in Organization.objects.all():
        kinds = set(
            WorkspaceConnection.objects.filter(organization_id=org.pk).values_list(
                "kind", flat=True
            )
        )
        if "chat" in kinds and "api" in kinds:
            org.product_mode = "both"
        elif "chat" in kinds:
            org.product_mode = "chat"
        elif "api" in kinds:
            org.product_mode = "api"
        if "chat" in kinds and not org.llm_backend:
            org.llm_backend = "local"
        org.save(update_fields=["product_mode", "llm_backend"])


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_organization_mcp_server_url"),
        ("connections", "0006_engine_and_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="product_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("chat", "Chat"),
                    ("api", "API"),
                    ("both", "Chat and API"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="llm_backend",
            field=models.CharField(
                blank=True,
                choices=[("local", "Local"), ("online", "Online")],
                default="",
                max_length=16,
            ),
        ),
        migrations.RunPython(seed_product_mode, migrations.RunPython.noop),
    ]
