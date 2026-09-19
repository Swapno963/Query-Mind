from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from chat.management.commands.seed_example_data import ORG_EMAIL, ORG_NAME, PASSWORD, PLATFORM_EMAIL
from chat.models import ApiAccessRequest, ApiKey, Conversation, Organization
from chat.organizations import organization_for


class SeedExampleDataTests(TestCase):
    def test_seed_creates_org_admin_mcp_url_and_history(self):
        output = StringIO()
        call_command("seed_example_data", stdout=output)
        call_command("seed_example_data", stdout=StringIO())
        org = Organization.objects.get(name=ORG_NAME)
        admin = User.objects.get(email=ORG_EMAIL)
        self.assertEqual(organization_for(admin), org)
        self.assertEqual(org.mcp_server_url, "http://127.0.0.1:8001/mcp")
        self.assertEqual(org.llm_backend, "online")
        self.assertTrue(
            ApiAccessRequest.objects.filter(
                user=admin, status=ApiAccessRequest.STATUS_APPROVED
            ).exists()
        )
        self.assertEqual(ApiKey.objects.filter(user=admin, revoked_at__isnull=True).count(), 1)
        self.assertTrue(Conversation.objects.filter(user=admin).exists())
        self.assertTrue(User.objects.get(email=PLATFORM_EMAIL).is_superuser)
        self.assertTrue(admin.check_password(PASSWORD))
        self.assertIn("QUERYMIND_API_KEY", output.getvalue())

    def test_new_key_mints_another_secret(self):
        call_command("seed_example_data", stdout=StringIO())
        call_command("seed_example_data", new_key=True, stdout=StringIO())
        admin = User.objects.get(email=ORG_EMAIL)
        self.assertEqual(ApiKey.objects.filter(user=admin, revoked_at__isnull=True).count(), 2)
