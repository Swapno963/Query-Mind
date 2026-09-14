from django.conf import settings
from django.db import models
from django.db.models import Q


class ConversationManager(models.Manager):
    """Custom manager for Conversation model"""

    def recent(self, limit=5):
        return self.get_queryset().order_by("-updated_at")[:limit]

    def with_messages(self):
        return self.get_queryset().prefetch_related("messages")

    def for_user(self, user, kind=None):
        queryset = self.get_queryset().filter(user=user)
        if kind:
            queryset = queryset.filter(
                Q(workspace__kind=kind) | Q(workspace__isnull=True)
            )
        return queryset

    def create_with_message(self, message_content, user=None):
        title = (
            message_content[:50] + "..."
            if len(message_content) > 50
            else message_content
        )
        conversation = self.create(title=title, user=user)
        conversation.messages.create(content=message_content, is_user=True)
        return conversation


class Conversation(models.Model):
    title = models.CharField(
        max_length=200,
        default="New Chat",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        "connections.WorkspaceConnection",
        on_delete=models.SET_NULL,
        related_name="conversations",
        null=True,
        blank=True,
    )

    tenant_id = models.BigIntegerField(
        null=True,
        blank=True,
        default=None,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationManager()

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["-updated_at"]),
            models.Index(fields=["user"]),
            models.Index(fields=["tenant_id"]),
        ]

    def __str__(self):
        return self.title

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def last_message(self):
        return self.messages.last()

    def get_context_messages(self, limit=10):
        return list(self.messages.all()[:limit])


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    content = models.TextField()
    is_user = models.BooleanField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{'User' if self.is_user else 'AI'}: {self.content[:50]}..."

    @property
    def role(self):
        return "user" if self.is_user else "assistant"

    @property
    def truncated_content(self):
        return self.content[:100] + "..." if len(self.content) > 100 else self.content


class ApiAccessRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_access_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} ({self.status})"


class ApiKey(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    prefix = models.CharField(max_length=24, unique=True)
    key_hash = models.CharField(max_length=64)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix} ({self.user})"

    @property
    def is_active(self):
        return self.revoked_at is None
