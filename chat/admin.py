from django.contrib import admin
from django.db.models import Count
from django.utils import timezone

from .models import (
    ApiAccessRequest,
    ApiKey,
    Conversation,
    Message,
    Organization,
    OrganizationMembership,
)


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "organization",
        "workspace",
        "get_message_count",
        "updated_at",
    )
    list_filter = ("created_at", "updated_at")
    search_fields = ("title", "user__email", "user__username", "organization__name")
    autocomplete_fields = ("user", "workspace", "organization")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)
    list_select_related = ("user", "organization", "workspace")
    date_hierarchy = "updated_at"

    def get_message_count(self, obj):
        return obj.messages__count

    get_message_count.short_description = "Messages"
    get_message_count.admin_order_field = "messages__count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(messages__count=Count("messages"))


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation_title", "sender", "content_preview", "timestamp")
    list_filter = ("is_user", "timestamp")
    search_fields = ("content", "conversation__title", "conversation__user__email")
    autocomplete_fields = ("conversation",)
    readonly_fields = ("timestamp",)
    ordering = ("-timestamp",)
    list_select_related = ("conversation", "conversation__user")
    date_hierarchy = "timestamp"
    fieldsets = (
        (None, {"fields": ("conversation", "is_user", "content")}),
        ("Timestamps", {"fields": ("timestamp",), "classes": ("collapse",)}),
    )

    def conversation_title(self, obj):
        return obj.conversation.title

    conversation_title.short_description = "Conversation"
    conversation_title.admin_order_field = "conversation__title"

    def sender(self, obj):
        return "User" if obj.is_user else "QueryMind"

    sender.short_description = "Sender"
    sender.admin_order_field = "is_user"

    def content_preview(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content

    content_preview.short_description = "Content"


@admin.action(description="Approve selected requests")
def approve_api_requests(modeladmin, request, queryset):
    queryset.exclude(status=ApiAccessRequest.STATUS_APPROVED).update(
        status=ApiAccessRequest.STATUS_APPROVED,
        updated_at=timezone.now(),
    )


@admin.action(description="Deny selected requests")
def deny_api_requests(modeladmin, request, queryset):
    queryset.exclude(status=ApiAccessRequest.STATUS_DENIED).update(
        status=ApiAccessRequest.STATUS_DENIED,
        updated_at=timezone.now(),
    )


@admin.register(ApiAccessRequest)
class ApiAccessRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "status", "created_at", "updated_at")
    list_filter = ("status", "kind")
    search_fields = ("user__username", "user__email", "note")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    actions = (approve_api_requests, deny_api_requests)
    list_select_related = ("user",)
    date_hierarchy = "created_at"


@admin.action(description="Revoke selected API keys")
def revoke_api_keys(modeladmin, request, queryset):
    queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("prefix", "user", "is_active", "revoked_at", "created_at")
    list_filter = ("revoked_at",)
    search_fields = ("prefix", "user__username", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("prefix", "key_hash", "created_at")
    actions = (revoke_api_keys,)
    list_select_related = ("user",)
    date_hierarchy = "created_at"

    def is_active(self, obj):
        return obj.revoked_at is None

    is_active.boolean = True
    is_active.short_description = "Active"

    def has_add_permission(self, request):
        return False


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product_mode",
        "llm_backend",
        "created_by",
        "mcp_server_url",
        "created_at",
    )
    list_filter = ("product_mode", "llm_backend")
    search_fields = ("name", "mcp_server_url", "created_by__email")
    autocomplete_fields = ("created_by",)
    readonly_fields = ("created_at", "mcp_token_configured")
    inlines = (OrganizationMembershipInline,)
    list_select_related = ("created_by",)
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("name", "created_by", "created_at")}),
        (
            "Products",
            {
                "fields": (
                    "product_mode",
                    "llm_backend",
                    "mcp_server_url",
                    "mcp_token_configured",
                )
            },
        ),
    )

    @admin.display(boolean=True, description="MCP token stored")
    def mcp_token_configured(self, obj):
        return obj.has_mcp_access_token()


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "user__username", "organization__name")
    autocomplete_fields = ("user", "organization")
    readonly_fields = ("created_at",)
    list_select_related = ("user", "organization")
