from django.contrib import admin

from .models import DatabaseSchema, VerifiedQueryExample, WorkspaceConnection


@admin.register(DatabaseSchema)
class DatabaseSchemaAdmin(admin.ModelAdmin):
    list_display = ("id", "discovered_at")
    readonly_fields = ("discovered_at",)
    search_fields = ("id",)


@admin.register(WorkspaceConnection)
class WorkspaceConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "kind",
        "engine",
        "host",
        "db_name",
        "db_user",
        "is_readonly_role",
        "updated_at",
    )
    list_filter = ("kind", "engine", "is_readonly_role")
    search_fields = (
        "user__email",
        "user__username",
        "organization__name",
        "host",
        "db_name",
        "db_user",
    )
    autocomplete_fields = ("user", "organization")
    readonly_fields = (
        "schema_text",
        "semantic_layer",
        "updated_at",
        "created_at",
    )
    exclude = ("password_ciphertext",)
    list_select_related = ("user", "organization")
    date_hierarchy = "updated_at"
    fieldsets = (
        (None, {"fields": ("user", "organization", "kind")}),
        (
            "Database",
            {
                "fields": (
                    "engine",
                    "host",
                    "port",
                    "db_name",
                    "db_user",
                    "is_readonly_role",
                )
            },
        ),
        (
            "Catalog",
            {
                "classes": ("collapse",),
                "fields": (
                    "industry",
                    "business",
                    "discovered_tables",
                    "discovered_columns",
                    "allowed_tables",
                    "allowed_columns",
                    "keeps",
                    "schema_text",
                    "semantic_layer",
                ),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(VerifiedQueryExample)
class VerifiedQueryExampleAdmin(admin.ModelAdmin):
    list_display = ("question_preview", "workspace", "created_at")
    search_fields = ("question", "sql", "workspace__db_name", "workspace__user__email")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("created_at",)
    list_select_related = ("workspace", "workspace__user")
    date_hierarchy = "created_at"

    def question_preview(self, obj):
        return obj.question[:80]

    question_preview.short_description = "Question"
