from django.contrib import admin

from .models import DatabaseSchema, WorkspaceConnection


@admin.register(DatabaseSchema)
class DatabaseSchemaAdmin(admin.ModelAdmin):
    list_display = ("id", "discovered_at")
    readonly_fields = ("discovered_at",)


@admin.register(WorkspaceConnection)
class WorkspaceConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "host", "db_name", "db_user", "is_readonly_role", "updated_at")
    readonly_fields = ("password_ciphertext", "schema_text", "updated_at", "created_at")
    exclude = ("password_ciphertext",)
