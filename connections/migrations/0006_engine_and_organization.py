from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_organization"),
        ("connections", "0005_semantic_layer_and_examples"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceconnection",
            name="engine",
            field=models.CharField(
                choices=[
                    ("postgres", "PostgreSQL"),
                    ("mysql", "MySQL"),
                    ("oracle", "Oracle"),
                    ("mssql", "Microsoft SQL Server"),
                ],
                default="postgres",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="workspaceconnection",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workspaces",
                to="chat.organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="workspaceconnection",
            constraint=models.UniqueConstraint(
                condition=models.Q(("organization__isnull", False)),
                fields=("organization", "kind"),
                name="unique_workspace_per_org_kind",
            ),
        ),
    ]
