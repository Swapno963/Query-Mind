from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from connections.models import WorkspaceConnection
from connections.services.crypto import decrypt_secret

from .api_keys import generate_api_key
from .models import ApiAccessRequest, ApiKey, Conversation, Message
from .organizations import ensure_organization_for_user, organization_for
from .product import apply_product_mode


def set_org_product(user, mode="both", llm="local"):
    org = organization_for(user) or ensure_organization_for_user(user)
    org.product_mode = mode
    org.llm_backend = llm
    org.save(update_fields=["product_mode", "llm_backend"])
    return org


class AuthIsolationTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.alice = User.objects.create_user(
            username="alice@example.com",
            email="alice@example.com",
            password=self.password,
            first_name="Alice",
        )
        self.bob = User.objects.create_user(
            username="bob@example.com",
            email="bob@example.com",
            password=self.password,
            first_name="Bob",
        )
        self.client = Client()
        self.csrf_client = Client(enforce_csrf_checks=True)

    def test_register_creates_user(self):
        response = self.client.post(
            reverse("register"),
            {
                "name": "Cara",
                "email": "cara@example.com",
                "password": self.password,
                "password_confirm": self.password,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="cara@example.com").exists())
        from chat.models import OrganizationMembership

        cara = User.objects.get(username="cara@example.com")
        membership = OrganizationMembership.objects.get(user=cara)
        self.assertEqual(membership.role, OrganizationMembership.ROLE_ADMIN)

    def test_login_rejects_bad_password(self):
        response = self.client.post(
            reverse("login"),
            {"email": "alice@example.com", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 400)

    def test_ask_requires_login(self):
        response = self.client.get(reverse("ask"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_conversations_are_scoped_to_owner(self):
        alice_chat = Conversation.objects.create(user=self.alice, title="Alice Q")
        bob_chat = Conversation.objects.create(user=self.bob, title="Bob Q")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("ask"))
        html = response.content.decode()
        self.assertIn("Alice Q", html)
        self.assertNotIn("Bob Q", html)
        hidden = self.client.get(reverse("chat", args=[bob_chat.id]))
        self.assertEqual(hidden.status_code, 404)
        visible = self.client.get(reverse("chat", args=[alice_chat.id]))
        self.assertEqual(visible.status_code, 200)

    def test_user_can_have_many_conversations(self):
        Conversation.objects.create(user=self.alice, title="One")
        Conversation.objects.create(user=self.alice, title="Two")
        self.assertEqual(Conversation.objects.filter(user=self.alice).count(), 2)

    def test_csrf_required_on_chat_post(self):
        chat = Conversation.objects.create(user=self.alice, title="CSRF")
        self.csrf_client.force_login(self.alice)
        response = self.csrf_client.post(
            reverse("chat", args=[chat.id]),
            {"message": "hello"},
        )
        self.assertEqual(response.status_code, 403)

    def test_api_requires_auth(self):
        response = self.client.post("/api/v1/chat/", {"message": "hello"}, content_type="application/json")
        self.assertIn(response.status_code, {401, 403})
        discover = self.client.get("/api/discover/")
        self.assertIn(discover.status_code, {401, 403})


class OnboardingGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="CorrectHorseBattery9",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_onboarding_does_not_invent_tables(self):
        response = self.client.post(
            reverse("onboarding"),
            {
                "industry": "Retail / e-commerce",
                "allowed_tables": ["customers", "orders"],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WorkspaceConnection.objects.filter(user=self.user).exists())

    def test_ask_without_allow_list_redirects_to_onboarding(self):
        response = self.client.post(reverse("ask"), {"message": "How many orders?"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding"))

    def test_workspace_password_is_not_stored_plain(self):
        workspace = WorkspaceConnection.objects.create(
            user=self.user,
            host="127.0.0.1",
            port=5432,
            db_name="shop",
            db_user="reader",
            password_ciphertext="pending",
            allowed_tables=["orders"],
            discovered_tables=["orders"],
        )
        workspace.set_password("secret-db-password")
        workspace.save()
        workspace.refresh_from_db()
        self.assertNotEqual(workspace.password_ciphertext, "secret-db-password")
        self.assertEqual(decrypt_secret(workspace.password_ciphertext), "secret-db-password")


class QueryMindAPITests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.user = User.objects.create_user(
            username="api@example.com",
            email="api@example.com",
            password=self.password,
        )
        self.session = APIClient()
        self.session.force_login(self.user)
        self.api = APIClient()
        from chat.organizations import ensure_organization_for_user

        ensure_organization_for_user(self.user)
        set_org_product(self.user, mode="api", llm="")

    def _approve_and_mint(self):
        ApiAccessRequest.objects.create(
            user=self.user,
            status=ApiAccessRequest.STATUS_APPROVED,
        )
        raw, prefix, hashed = generate_api_key()
        ApiKey.objects.create(user=self.user, prefix=prefix, key_hash=hashed)
        return raw

    def _auth(self, raw):
        self.api.credentials(HTTP_X_API_KEY=raw)

    def _ready_workspace(self):
        return WorkspaceConnection.objects.create(
            user=self.user,
            kind=WorkspaceConnection.KIND_API,
            discovered_tables=["orders"],
            discovered_columns={"orders": ["id", "status"]},
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id", "status"]},
            schema_text="TABLE: orders\nColumns:\n- id INTEGER\n- status TEXT",
        )

    def test_missing_key_is_rejected(self):
        response = self.api.post("/api/v1/messages/", {"content": "How many?"}, format="json")
        self.assertIn(response.status_code, {401, 403})
        self.assertEqual(response.data["type"], "error")

    def test_unapproved_user_cannot_mint_key(self):
        response = self.session.post("/api/v1/keys/")
        self.assertEqual(response.status_code, 403)

    def test_pending_key_cannot_call_integrator_routes(self):
        ApiAccessRequest.objects.create(
            user=self.user,
            status=ApiAccessRequest.STATUS_PENDING,
        )
        raw, prefix, hashed = generate_api_key()
        ApiKey.objects.create(user=self.user, prefix=prefix, key_hash=hashed)
        self._auth(raw)
        response = self.api.get("/api/v1/workspace/")
        self.assertIn(response.status_code, {401, 403})

    def test_session_user_can_request_and_mint_after_approval(self):
        created = self.session.post(
            "/api/v1/access-requests/",
            {"note": "please"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        req = ApiAccessRequest.objects.get(user=self.user)
        req.status = ApiAccessRequest.STATUS_APPROVED
        req.save(update_fields=["status"])
        minted = self.session.post("/api/v1/keys/")
        self.assertEqual(minted.status_code, 201)
        self.assertTrue(minted.json()["key"].startswith("qm_live_"))

    def test_discover_persists_catalog_and_ignores_invented_allow_list(self):
        raw = self._approve_and_mint()
        self._auth(raw)
        instructions = self.api.get("/api/v1/discover/instructions/")
        self.assertEqual(instructions.status_code, 200)
        self.assertIn("information_schema.columns", instructions.json()["sql"])
        ingest = self.api.post(
            "/api/v1/discover/",
            {
                "rows": [
                    {"table_name": "orders", "column_name": "id"},
                    {"table_name": "orders", "column_name": "status"},
                    {"table_name": "products", "column_name": "name"},
                ]
            },
            format="json",
        )
        self.assertEqual(ingest.status_code, 200)
        access = self.api.put(
            "/api/v1/access/",
            {
                "allowed_tables": ["orders", "secrets"],
                "allowed_columns": {
                    "orders": ["id", "ssn"],
                    "secrets": ["token"],
                },
            },
            format="json",
        )
        self.assertEqual(access.status_code, 200)
        body = access.json()
        self.assertEqual(body["allowed_tables"], ["orders"])
        self.assertEqual(body["allowed_columns"], {"orders": ["id"]})
        workspace = WorkspaceConnection.objects.get(
            user=self.user, kind=WorkspaceConnection.KIND_API
        )
        self.assertEqual(workspace.discovered_tables, ["orders", "products"])
        self.assertEqual(workspace.discovered_columns["orders"], ["id", "status"])

    def test_messages_return_sql_without_tenant_db_and_results_store_answer(self):
        self._ready_workspace()
        raw = self._approve_and_mint()
        self._auth(raw)
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {
            "sql": "SELECT COUNT(*) AS n FROM orders",
            "validation_result": {"valid": True, "kind": "ok"},
        }
        with patch("chat.api.views.build_api_query_graph", return_value=fake_graph):
            asked = self.api.post(
                "/api/v1/messages/",
                {"content": "How many unpaid orders?"},
                format="json",
            )
        self.assertEqual(asked.status_code, 200)
        payload = asked.json()
        self.assertEqual(payload["stop_reason"], "sql")
        self.assertEqual(payload["content"][0]["sql"], "SELECT COUNT(*) AS n FROM orders")
        self.assertTrue(payload["content"][0]["executable"])
        user_message = Message.objects.get(id=payload["user_message_id"])
        self.assertTrue(user_message.is_user)
        with patch(
            "chat.api.views.ChatService.process_Result",
            return_value={"answer": "There are 12 unpaid orders."},
        ) as formatter:
            saved = self.api.post(
                "/api/v1/messages/results/",
                {"user_message_id": user_message.id, "rows": [{"n": 12}]},
                format="json",
            )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["stop_reason"], "end_turn")
        formatter.assert_called_once()
        assistant = Message.objects.filter(
            conversation_id=user_message.conversation_id,
            is_user=False,
        ).get()
        self.assertEqual(assistant.content, "There are 12 unpaid orders.")
        self.assertFalse(
            WorkspaceConnection.objects.get(
                user=self.user, kind=WorkspaceConnection.KIND_API
            ).get_password()
        )


class WorkspaceProductTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.user = User.objects.create_user(
            username="both@example.com",
            email="both@example.com",
            password=self.password,
        )
        self.client = Client()
        self.client.force_login(self.user)
        org = ensure_organization_for_user(self.user, product_mode="both")
        apply_product_mode(org, "both")

    def test_register_api_skips_chat_onboarding(self):
        guest = Client()
        response = guest.post(
            reverse("register"),
            {
                "name": "Dev",
                "email": "dev@example.com",
                "password": self.password,
                "password_confirm": self.password,
                "product": "api",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding") + "?track=api")

    def test_api_catalog_does_not_make_chat_ready(self):
        WorkspaceConnection.objects.create(
            user=self.user,
            kind=WorkspaceConnection.KIND_API,
            discovered_tables=["orders"],
            discovered_columns={"orders": ["id"]},
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        response = self.client.post(reverse("ask"), {"message": "How many orders?"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding"))

    def test_chat_and_api_catalogs_stay_separate(self):
        WorkspaceConnection.objects.create(
            user=self.user,
            kind=WorkspaceConnection.KIND_API,
            discovered_tables=["orders"],
            discovered_columns={"orders": ["id"]},
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        WorkspaceConnection.objects.create(
            user=self.user,
            kind=WorkspaceConnection.KIND_CHAT,
            host="127.0.0.1",
            db_name="shop",
            discovered_tables=["staff"],
            discovered_columns={"staff": ["email"]},
            allowed_tables=["staff"],
            allowed_columns={"staff": ["email"]},
        )
        self.assertEqual(
            WorkspaceConnection.objects.get(
                user=self.user, kind=WorkspaceConnection.KIND_API
            ).discovered_tables,
            ["orders"],
        )
        self.assertEqual(
            WorkspaceConnection.objects.get(
                user=self.user, kind=WorkspaceConnection.KIND_CHAT
            ).discovered_tables,
            ["staff"],
        )

    def test_developers_page_requests_access_without_minting(self):
        page = self.client.get(reverse("developers"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "x-api-key")
        asked = self.client.post(reverse("developers"), {"action": "request"})
        self.assertEqual(asked.status_code, 302)
        self.assertTrue(
            ApiAccessRequest.objects.filter(
                user=self.user, status=ApiAccessRequest.STATUS_PENDING
            ).exists()
        )
        denied = self.client.post(reverse("developers"), {"action": "create_key"})
        self.assertEqual(denied.status_code, 302)
        self.assertFalse(ApiKey.objects.filter(user=self.user).exists())

    def test_developers_page_has_in_page_toc(self):
        page = self.client.get(reverse("developers"))
        html = page.content.decode()
        self.assertIn('href="#request-access"', html)
        self.assertIn('href="#create-key"', html)
        self.assertIn("On this page", html)
        self.assertIn("Example response", html)

    def test_api_messages_are_not_shown_in_chat_history(self):
        api_workspace = WorkspaceConnection.objects.create(
            user=self.user,
            kind=WorkspaceConnection.KIND_API,
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        Conversation.objects.create(
            user=self.user,
            workspace=api_workspace,
            title="API unpaid orders",
        )
        html = self.client.get(reverse("ask")).content.decode()
        self.assertNotIn("API unpaid orders", html)


class DevelopersKeyRevealTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.user = User.objects.create_user(
            username="keys@example.com",
            email="keys@example.com",
            password=self.password,
        )
        self.client = Client()
        self.client.force_login(self.user)
        org = ensure_organization_for_user(self.user, product_mode="both")
        apply_product_mode(org, "both")
        ApiAccessRequest.objects.create(
            user=self.user,
            status=ApiAccessRequest.STATUS_APPROVED,
        )

    def _mint(self):
        response = self.client.post(reverse("developers"), {"action": "create_key"})
        self.assertEqual(response.status_code, 302)
        key = ApiKey.objects.get(user=self.user)
        raw = self.client.session["pending_api_key"]["raw"]
        return key, raw

    def test_created_key_is_masked_on_get(self):
        key, raw = self._mint()
        page = self.client.get(reverse("developers"))
        html = page.content.decode()
        self.assertNotIn(raw, html)
        self.assertIn(f"{key.prefix}••••", html)
        self.assertContains(page, "Copy secret")

    def test_reveal_rejects_wrong_password(self):
        key, raw = self._mint()
        self.client.post(
            reverse("developers"),
            {
                "action": "reveal_key",
                "key_id": key.id,
                "password": "wrong-password",
            },
        )
        page = self.client.get(reverse("developers"))
        self.assertNotIn(raw, page.content.decode())
        self.assertIn("pending_api_key", self.client.session)

    def test_reveal_shows_secret_once(self):
        key, raw = self._mint()
        self.client.post(
            reverse("developers"),
            {
                "action": "reveal_key",
                "key_id": key.id,
                "password": self.password,
            },
        )
        first = self.client.get(reverse("developers"))
        self.assertContains(first, raw)
        second = self.client.get(reverse("developers"))
        self.assertNotIn(raw, second.content.decode())
        self.assertContains(second, "Secret is no longer stored. Create a new key.")


def reload_urlconf():
    from importlib import import_module, reload

    from django.conf import settings
    from django.urls import clear_url_caches

    clear_url_caches()
    reload(import_module(settings.ROOT_URLCONF))


class AppModeRoutingTests(TestCase):
    def tearDown(self):
        reload_urlconf()
        super().tearDown()

    @override_settings(
        APP_MODE="api",
        CHAT_ENABLED=False,
        API_ENABLED=True,
        LOGIN_REDIRECT_URL="developers",
    )
    def test_api_mode_hides_chat_routes(self):
        reload_urlconf()
        self.assertEqual(self.client.get("/ask/").status_code, 404)
        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["mode"], "api")
        self.assertEqual(self.client.get("/developers/").status_code, 302)

    @override_settings(
        APP_MODE="chat",
        CHAT_ENABLED=True,
        API_ENABLED=False,
        LOGIN_REDIRECT_URL="ask",
    )
    def test_chat_mode_hides_api_routes(self):
        reload_urlconf()
        self.assertEqual(self.client.get("/ask/").status_code, 302)
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/chat/").status_code, 404)
        self.assertEqual(self.client.get("/developers/").status_code, 404)

    @override_settings(
        APP_MODE="api",
        CHAT_ENABLED=False,
        API_ENABLED=True,
        LOGIN_REDIRECT_URL="developers",
    )
    def test_api_mode_register_ignores_chat_product(self):
        reload_urlconf()
        response = Client().post(
            reverse("register"),
            {
                "name": "Ada",
                "email": "ada-api-mode@example.com",
                "password": "CorrectHorseBattery9",
                "password_confirm": "CorrectHorseBattery9",
                "product": "chat",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding") + "?track=api")


class OrganizationAccessTests(TestCase):
    def setUp(self):
        from chat.organizations import create_member, ensure_organization_for_user

        self.password = "CorrectHorseBattery9"
        self.admin = User.objects.create_user(
            username="owner@shop.com",
            email="owner@shop.com",
            password=self.password,
            first_name="Owner",
        )
        org = ensure_organization_for_user(self.admin, name="Shop Co")
        org.product_mode = "both"
        org.llm_backend = "local"
        org.save(update_fields=["product_mode", "llm_backend"])
        self.member = create_member(
            admin=self.admin,
            email="analyst@shop.com",
            name="Analyst",
            password=self.password,
        )
        self.other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password=self.password,
        )
        ensure_organization_for_user(self.other, name="Other Org")
        self.client = Client()

    def test_member_cannot_open_team_or_onboarding(self):
        self.client.force_login(self.member)
        team = self.client.get(reverse("team"))
        self.assertEqual(team.status_code, 302)
        onboard = self.client.get(reverse("onboarding"))
        self.assertEqual(onboard.status_code, 302)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 302)

    def test_admin_dashboard_shows_overview_and_actions(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Administrator dashboard", html)
        self.assertIn("Shop Co", html)
        self.assertIn("Actions you can take", html)
        self.assertIn("Create and manage users", html)
        self.assertIn("Connect or change the database", html)
        self.assertIn("Configure the MCP server", html)

    def test_admin_login_redirects_to_setup_when_incomplete(self):
        response = self.client.post(
            reverse("login"),
            {"email": "owner@shop.com", "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding"))

    def test_member_login_does_not_open_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"email": "analyst@shop.com", "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse("dashboard"))

    def test_admin_can_approve_and_deny_api_from_dashboard(self):
        pending = ApiAccessRequest.objects.create(
            user=self.member,
            status=ApiAccessRequest.STATUS_PENDING,
        )
        self.client.force_login(self.admin)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "analyst@shop.com")
        approve = self.client.post(
            reverse("dashboard"),
            {"action": "approve_api", "request_id": pending.id},
        )
        self.assertEqual(approve.status_code, 302)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ApiAccessRequest.STATUS_APPROVED)

        other_request = ApiAccessRequest.objects.create(
            user=self.other,
            status=ApiAccessRequest.STATUS_PENDING,
        )
        denied = self.client.post(
            reverse("dashboard"),
            {"action": "deny_api", "request_id": other_request.id},
        )
        self.assertEqual(denied.status_code, 302)
        other_request.refresh_from_db()
        self.assertEqual(other_request.status, ApiAccessRequest.STATUS_PENDING)

    def test_admin_dashboard_lists_member_question_titles(self):
        Conversation.objects.create(user=self.member, title="Weekly stock check")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Weekly stock check")

    def test_admin_creates_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("team"),
            {
                "action": "create",
                "name": "Support",
                "email": "support@shop.com",
                "password": self.password,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="support@shop.com").exists())

    def test_conversations_stay_private_across_org_members(self):
        hidden = Conversation.objects.create(user=self.admin, title="Admin private")
        self.client.force_login(self.member)
        response = self.client.get(reverse("chat", args=[hidden.id]))
        self.assertEqual(response.status_code, 404)

    def test_deactivated_member_cannot_login(self):
        from chat.organizations import set_member_active

        set_member_active(admin=self.admin, user=self.member, is_active=False)
        response = self.client.post(
            reverse("login"),
            {"email": "analyst@shop.com", "password": self.password},
        )
        self.assertEqual(response.status_code, 403)

    def test_member_api_key_rejected_after_deactivate(self):
        from chat.api_keys import generate_api_key, lookup_api_key
        from chat.organizations import set_member_active

        ApiAccessRequest.objects.create(
            user=self.member,
            status=ApiAccessRequest.STATUS_APPROVED,
        )
        raw, prefix, hashed = generate_api_key()
        ApiKey.objects.create(user=self.member, prefix=prefix, key_hash=hashed)
        self.assertIsNotNone(lookup_api_key(raw))
        set_member_active(admin=self.admin, user=self.member, is_active=False)
        self.assertIsNone(lookup_api_key(raw))

    def test_shared_workspace_is_visible_to_member(self):
        from chat.organizations import organization_for
        from chat.ui import KIND_CHAT, workspace_for

        org = organization_for(self.admin)
        WorkspaceConnection.objects.create(
            user=self.admin,
            organization=org,
            kind=KIND_CHAT,
            host="127.0.0.1",
            db_name="shop",
            db_user="reader",
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        self.assertEqual(workspace_for(self.member, KIND_CHAT).db_name, "shop")
        other_ws = workspace_for(self.other, KIND_CHAT)
        self.assertIsNone(other_ws)


class OrgProductSetupTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.admin = User.objects.create_user(
            username="owner@products.com",
            email="owner@products.com",
            password=self.password,
            first_name="Owner",
        )
        self.org = ensure_organization_for_user(
            self.admin, name="Products Co", product_mode="chat"
        )
        self.org.llm_backend = "local"
        self.org.save(update_fields=["llm_backend"])
        self.client = Client()
        self.client.force_login(self.admin)

    def _ready_chat(self):
        return WorkspaceConnection.objects.create(
            user=self.admin,
            organization=self.org,
            kind=WorkspaceConnection.KIND_CHAT,
            host="127.0.0.1",
            db_name="shop",
            db_user="reader",
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )

    def test_register_both_stores_product_and_starts_chat_setup(self):
        guest = Client()
        response = guest.post(
            reverse("register"),
            {
                "name": "Both",
                "email": "both-setup@example.com",
                "password": self.password,
                "password_confirm": self.password,
                "product": "both",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding") + "?track=chat")
        user = User.objects.get(username="both-setup@example.com")
        org = organization_for(user)
        self.assertEqual(org.product_mode, "both")

    def test_chat_only_org_cannot_open_developers(self):
        page = self.client.get(reverse("developers"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("ask"))

    def test_api_only_org_cannot_open_ask(self):
        apply_product_mode(self.org, "api")
        page = self.client.get(reverse("ask"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("developers"))

    def test_admin_can_move_chat_to_both_without_wiping_chat(self):
        chat = self._ready_chat()
        response = self.client.post(
            reverse("dashboard"),
            {"action": "save_product", "product": "both", "llm_backend": "local"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("track=api", response.url)
        self.org.refresh_from_db()
        self.assertEqual(self.org.product_mode, "both")
        chat.refresh_from_db()
        self.assertEqual(chat.db_name, "shop")
        self.assertEqual(chat.allowed_tables, ["orders"])

    def test_member_cannot_change_products(self):
        from chat.organizations import create_member

        member = create_member(
            admin=self.admin,
            email="member@products.com",
            name="Member",
            password=self.password,
        )
        guest = Client()
        guest.force_login(member)
        response = guest.post(
            reverse("dashboard"),
            {"action": "save_product", "product": "both"},
        )
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.product_mode, "chat")

    @patch("chat.views_stream.build_online_graph")
    @patch("chat.views_stream.build_on_premise_graph")
    def test_stream_uses_local_graph_for_local_backend(self, local_graph, online_graph):
        self._ready_chat()
        conversation = Conversation.objects.create(user=self.admin, title="Q")
        message = Message.objects.create(
            conversation=conversation, content="How many orders?", is_user=True
        )
        local_graph.return_value.stream.return_value = iter([])
        online_graph.return_value.stream.return_value = iter([])
        response = self.client.get(
            reverse("stream_chat", args=[conversation.id]),
            {"message_id": message.id},
        )
        self.assertEqual(response.status_code, 200)
        list(response.streaming_content)
        local_graph.assert_called_once()
        online_graph.assert_not_called()

    @patch("chat.views_stream.build_online_graph")
    @patch("chat.views_stream.build_on_premise_graph")
    def test_stream_uses_online_graph_for_online_backend(self, local_graph, online_graph):
        self.org.llm_backend = "online"
        self.org.save(update_fields=["llm_backend"])
        self._ready_chat()
        conversation = Conversation.objects.create(user=self.admin, title="Q")
        message = Message.objects.create(
            conversation=conversation, content="How many orders?", is_user=True
        )
        local_graph.return_value.stream.return_value = iter([])
        online_graph.return_value.stream.return_value = iter([])
        response = self.client.get(
            reverse("stream_chat", args=[conversation.id]),
            {"message_id": message.id},
        )
        self.assertEqual(response.status_code, 200)
        list(response.streaming_content)
        online_graph.assert_called_once()
        local_graph.assert_not_called()


