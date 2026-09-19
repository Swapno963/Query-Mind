from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from chat.api_keys import generate_api_key
from chat.models import ApiAccessRequest, ApiKey, Conversation, Organization, OrganizationMembership
from chat.organizations import ensure_organization_for_user
from chat.product import apply_llm_backend, apply_product_mode
from chat.services import ConversationService

PASSWORD = "DemoPass#2026"
ORG_NAME = "ServeEasy"
ORG_EMAIL = "serveeasy@querymind.local"
PLATFORM_EMAIL = "admin@querymind.local"
DEFAULT_MCP_URL = "http://127.0.0.1:8001/mcp"


class Command(BaseCommand):
    help = "Seed a Query Mind organization, ServeEasy API key, and sample chat history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previously seeded ServeEasy org users first.",
        )
        parser.add_argument(
            "--mcp-url",
            default=DEFAULT_MCP_URL,
            help="ServeEasy MCP URL stored on the org (local default: http://127.0.0.1:8001/mcp; production: http://easyserve.clustorflow.com/mcp).",
        )
        parser.add_argument(
            "--new-key",
            action="store_true",
            help="Mint a new API key even if one already exists.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()
        with transaction.atomic():
            self._platform_admin()
            org_user = self._org_admin()
            org = self._organization(org_user, options["mcp_url"])
            self._approve_api(org_user)
            raw_key = self._api_key(org_user, options["new_key"])
            self._sample_history(org_user, org)
        self._print_summary(org, org_user, raw_key)

    def _reset(self):
        emails = {ORG_EMAIL, PLATFORM_EMAIL}
        users = list(User.objects.filter(email__in=emails) | User.objects.filter(username__in=emails))
        org = Organization.objects.filter(name=ORG_NAME).first()
        if org:
            Conversation.objects.filter(organization=org).delete()
            OrganizationMembership.objects.filter(organization=org).delete()
            org.delete()
        for user in users:
            ApiKey.objects.filter(user=user).delete()
            ApiAccessRequest.objects.filter(user=user).delete()
            Conversation.objects.filter(user=user).delete()
            if not user.is_superuser or user.email == PLATFORM_EMAIL or user.username == PLATFORM_EMAIL:
                user.delete()
        self.stdout.write("Removed previous Query Mind demo data.")

    def _platform_admin(self):
        user = User.objects.filter(email__iexact=PLATFORM_EMAIL).first()
        if user is None:
            user = User.objects.filter(username__iexact=PLATFORM_EMAIL).first()
        if user is None:
            user = User.objects.create_superuser(
                username=PLATFORM_EMAIL,
                email=PLATFORM_EMAIL,
                password=PASSWORD,
            )
            self.stdout.write(self.style.SUCCESS("Created platform admin."))
            return user
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.email = PLATFORM_EMAIL
        user.set_password(PASSWORD)
        user.save()
        return user

    def _org_admin(self):
        user = User.objects.filter(email__iexact=ORG_EMAIL).first()
        if user is None:
            user = User.objects.filter(username__iexact=ORG_EMAIL).first()
        if user is None:
            user = User.objects.create_user(
                username=ORG_EMAIL,
                email=ORG_EMAIL,
                password=PASSWORD,
                first_name="ServeEasy",
            )
            self.stdout.write(self.style.SUCCESS("Created ServeEasy org admin."))
            return user
        user.is_active = True
        user.email = ORG_EMAIL
        user.set_password(PASSWORD)
        user.save()
        return user

    def _organization(self, user, mcp_url):
        org = ensure_organization_for_user(
            user,
            name=ORG_NAME,
            product_mode="mcp" if settings.API_ENABLED else "",
            llm_backend=Organization.LLM_ONLINE,
        )
        org.name = ORG_NAME
        org.mcp_server_url = (mcp_url or "").strip()
        org.save(update_fields=["name", "mcp_server_url"])
        if settings.API_ENABLED:
            mode = "mcp"
            apply_product_mode(org, mode)
        apply_llm_backend(org, Organization.LLM_ONLINE)
        membership = OrganizationMembership.objects.filter(user=user, organization=org).first()
        if membership:
            membership.role = OrganizationMembership.ROLE_ADMIN
            membership.is_active = True
            membership.save(update_fields=["role", "is_active"])
        return org

    def _approve_api(self, user):
        access = ApiAccessRequest.objects.filter(user=user).order_by("-created_at").first()
        if access:
            access.status = ApiAccessRequest.STATUS_APPROVED
            access.kind = ApiAccessRequest.KIND_MCP
            access.note = access.note or "Seeded ServeEasy integration key."
            access.save(update_fields=["status", "kind", "note", "updated_at"])
            return
        ApiAccessRequest.objects.create(
            user=user,
            kind=ApiAccessRequest.KIND_MCP,
            status=ApiAccessRequest.STATUS_APPROVED,
            note="Seeded ServeEasy integration key.",
        )

    def _api_key(self, user, force_new):
        existing = ApiKey.objects.filter(user=user, revoked_at__isnull=True).first()
        if existing and not force_new:
            return None
        raw, prefix, hashed = generate_api_key()
        ApiKey.objects.create(user=user, prefix=prefix, key_hash=hashed)
        return raw

    def _sample_history(self, user, org):
        if Conversation.objects.filter(user=user).exists():
            return
        conversation = Conversation.objects.create(
            user=user,
            organization=org,
            title="Today's pending orders",
        )
        ConversationService.add_user_message(conversation, "Show today's pending orders.")
        ConversationService.add_ai_message(
            conversation,
            "There are 2 pending orders: table 1 (Chicken Biryani) and table 2 (Beef Tehari x2).",
        )

    def _print_summary(self, org, org_user, raw_key):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Query Mind demo login (password DemoPass#2026)"))
        self.stdout.write(f"  Platform admin  {PLATFORM_EMAIL}")
        self.stdout.write(f"  Org admin       {ORG_EMAIL}")
        self.stdout.write(f"  Organization    {org.name}")
        self.stdout.write(f"  LLM             {org.llm_backend or 'online'}")
        self.stdout.write(f"  MCP URL         {org.mcp_server_url}")
        if raw_key:
            self.stdout.write(self.style.WARNING("  QUERYMIND_API_KEY (shown once)"))
            self.stdout.write(f"  {raw_key}")
            self.stdout.write("  Put this in ServeEasy Django .env as QUERYMIND_API_KEY.")
        else:
            key = ApiKey.objects.filter(user=org_user, revoked_at__isnull=True).first()
            prefix = key.prefix if key else "(none)"
            self.stdout.write(f"  Existing API key prefix {prefix}. Pass --new-key to mint another.")
