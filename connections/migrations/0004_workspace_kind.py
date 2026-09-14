from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("connections", "0003_workspace_allowed_columns"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="workspaceconnection",
            name="unique_workspace_connection_per_user",
        ),
        migrations.AlterField(
            model_name="workspaceconnection",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workspaces",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="workspaceconnection",
            name="kind",
            field=models.CharField(
                choices=[("chat", "Chat"), ("api", "API")],
                default="chat",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="workspaceconnection",
            constraint=models.UniqueConstraint(
                fields=("user", "kind"),
                name="unique_workspace_per_user_kind",
            ),
        ),
    ]
