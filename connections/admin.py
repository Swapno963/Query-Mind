from django.contrib import admin

from .models import DatabaseSchema, VerifiedQueryExample, WorkspaceConnection


@admin.register(DatabaseSchema)
class DatabaseSchemaAdmin(admin.ModelAdmin):
    list_display = ("id", "discovered_at")
    readonly_fields = ("discovered_at",)


@admin.register(WorkspaceConnection)
class WorkspaceConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "host", "db_name", "db_user", "is_readonly_role", "updated_at")
    list_filter = ("kind", "is_readonly_role")
    readonly_fields = (
        "password_ciphertext",
        "schema_text",
        "semantic_layer",
        "updated_at",
        "created_at",
    )
    exclude = ("password_ciphertext",)


@admin.register(VerifiedQueryExample)
class VerifiedQueryExampleAdmin(admin.ModelAdmin):
    list_display = ("question_preview", "workspace", "created_at")
    search_fields = ("question", "sql")
    readonly_fields = ("created_at",)

    def question_preview(self, obj):
        return obj.question[:80]

    question_preview.short_description = "Question"
