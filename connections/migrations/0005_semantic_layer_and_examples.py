from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("connections", "0004_workspace_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceconnection",
            name="semantic_layer",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="VerifiedQueryExample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("question", models.TextField()),
                ("sql", models.TextField()),
                ("linked_tables", models.JSONField(blank=True, default=list)),
                ("embedding", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="query_examples",
                        to="connections.workspaceconnection",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="verifiedqueryexample",
            index=models.Index(
                fields=["workspace", "created_at"],
                name="connections_workspa_7a1c2e_idx",
            ),
        ),
    ]
