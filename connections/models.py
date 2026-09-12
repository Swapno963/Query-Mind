from django.conf import settings
from django.db import models

from connections.services.crypto import decrypt_secret, encrypt_secret


class DatabaseSchema(models.Model):
    schema_data = models.JSONField()
    discovered_at = models.DateTimeField(auto_now=True)


class WorkspaceConnection(models.Model):
    """One PostgreSQL connection per user workspace."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_connection",
    )
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField(max_length=255)
    db_user = models.CharField(max_length=255)
    password_ciphertext = models.TextField()
    schema_text = models.TextField(blank=True, default="")
    discovered_tables = models.JSONField(default=list, blank=True)
    allowed_tables = models.JSONField(default=list, blank=True)
    industry = models.CharField(max_length=120, blank=True, default="")
    business = models.TextField(blank=True, default="")
    keeps = models.JSONField(default=list, blank=True)
    is_readonly_role = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                name="unique_workspace_connection_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.db_name}@{self.host} ({self.user})"

    def set_password(self, raw_password: str) -> None:
        self.password_ciphertext = encrypt_secret(raw_password)

    def get_password(self) -> str:
        return decrypt_secret(self.password_ciphertext)

    @property
    def django_alias(self) -> str:
        return f"workspace_{self.pk}"
