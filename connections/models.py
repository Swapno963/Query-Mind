from django.conf import settings
from django.db import models

from connections.services.crypto import decrypt_secret, encrypt_secret
from connections.services.engines import ENGINE_CHOICES, ENGINE_POSTGRES


class DatabaseSchema(models.Model):
    schema_data = models.JSONField()
    discovered_at = models.DateTimeField(auto_now=True)


class WorkspaceConnection(models.Model):
    """One catalog per product: live database (chat) or posted schema (API)."""

    KIND_CHAT = "chat"
    KIND_API = "api"
    KIND_CHOICES = [
        (KIND_CHAT, "Chat"),
        (KIND_API, "API"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    organization = models.ForeignKey(
        "chat.Organization",
        on_delete=models.CASCADE,
        related_name="workspaces",
        null=True,
        blank=True,
    )
    kind = models.CharField(
        max_length=16,
        choices=KIND_CHOICES,
        default=KIND_CHAT,
    )
    engine = models.CharField(
        max_length=16,
        choices=ENGINE_CHOICES,
        default=ENGINE_POSTGRES,
    )
    host = models.CharField(max_length=255, blank=True, default="")
    port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField(max_length=255, blank=True, default="")
    db_user = models.CharField(max_length=255, blank=True, default="")
    password_ciphertext = models.TextField(blank=True, default="")
    schema_text = models.TextField(blank=True, default="")
    discovered_tables = models.JSONField(default=list, blank=True)
    discovered_columns = models.JSONField(default=dict, blank=True)
    allowed_tables = models.JSONField(default=list, blank=True)
    allowed_columns = models.JSONField(default=dict, blank=True)
    industry = models.CharField(max_length=120, blank=True, default="")
    business = models.TextField(blank=True, default="")
    keeps = models.JSONField(default=list, blank=True)
    semantic_layer = models.JSONField(default=dict, blank=True)
    is_readonly_role = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"],
                name="unique_workspace_per_user_kind",
            ),
            models.UniqueConstraint(
                fields=["organization", "kind"],
                condition=models.Q(organization__isnull=False),
                name="unique_workspace_per_org_kind",
            ),
        ]
        verbose_name = "workspace connection"
        verbose_name_plural = "workspace connections"

    def __str__(self):
        label = self.db_name or self.kind
        return f"{label} ({self.kind}, {self.user})"

    def set_password(self, raw_password: str) -> None:
        self.password_ciphertext = encrypt_secret(raw_password)

    def get_password(self) -> str:
        if not self.password_ciphertext:
            return ""
        return decrypt_secret(self.password_ciphertext)

    @property
    def django_alias(self) -> str:
        return f"workspace_{self.pk}"


class VerifiedQueryExample(models.Model):
    """Successful question/SQL pairs used as few-shot examples."""

    workspace = models.ForeignKey(
        WorkspaceConnection,
        on_delete=models.CASCADE,
        related_name="query_examples",
        null=True,
        blank=True,
    )
    question = models.TextField()
    sql = models.TextField()
    linked_tables = models.JSONField(default=list, blank=True)
    embedding = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "created_at"]),
        ]
        verbose_name = "verified query example"
        verbose_name_plural = "verified query examples"

    def __str__(self):
        return self.question[:80]
