import django.db.models.deletion
from django.db import migrations, models


def attach_chat_workspaces(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    WorkspaceConnection = apps.get_model("connections", "WorkspaceConnection")
    for conversation in Conversation.objects.filter(workspace_id__isnull=True, user_id__isnull=False):
        workspace = WorkspaceConnection.objects.filter(
            user_id=conversation.user_id,
            kind="chat",
        ).first()
        if workspace:
            conversation.workspace_id = workspace.id
            conversation.save(update_fields=["workspace_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_api_access_and_keys"),
        ("connections", "0004_workspace_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="conversations",
                to="connections.workspaceconnection",
            ),
        ),
        migrations.RunPython(attach_chat_workspaces, migrations.RunPython.noop),
    ]
