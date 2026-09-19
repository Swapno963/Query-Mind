from unittest.mock import MagicMock, patch
import json

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


def set_org_product(user, mode="chat", llm="local"):
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
        from chat.organizations import organization_for

        cara = User.objects.get(username="cara@example.com")
        membership = OrganizationMembership.objects.get(user=cara)
        self.assertEqual(membership.role, OrganizationMembership.ROLE_ADMIN)
        self.assertEqual(organization_for(cara).product_mode, "")
        self.assertEqual(response.url, reverse("onboarding") + "?change=products")

    def test_login_rejects_bad_password(self):
        response = self.client.post(
            reverse("login"),
            {"email": "alice@example.com", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 400)

    def test_createsuperuser_can_login_with_email(self):
        User.objects.create_superuser(
            username="xyz",
            email="a@b.com",
            password=self.password,
        )
        response = self.client.post(
            reverse("login"),
            {"email": "a@b.com", "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))
        from chat.models import OrganizationMembership

        self.assertFalse(
            OrganizationMembership.objects.filter(user__email="a@b.com").exists()
        )

    def test_platform_admin_cannot_mint_org_api_key(self):
        admin = User.objects.create_superuser(
            username="xyz",
            email="a@b.com",
            password=self.password,
        )
        self.client.force_login(admin)
        before = ApiKey.objects.count()
        response = self.client.post(reverse("developers"), {"action": "create_key"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ApiKey.objects.count(), before)

    def test_platform_admin_cannot_save_mcp_url_without_org(self):
        admin = User.objects.create_superuser(
            username="boss",
            email="boss@example.com",
            password=self.password,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("team"),
            {"action": "save_mcp", "mcp_server_url": "http://127.0.0.1:8001/mcp"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))

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

    def test_messages_use_org_local_and_online_llm(self):
        self._ready_workspace()
        raw = self._approve_and_mint()
        self._auth(raw)
        org = organization_for(self.user)
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {
            "sql": "SELECT 1",
            "validation_result": {"valid": True, "kind": "ok"},
        }
        for backend in ("local", "online"):
            org.llm_backend = backend
            org.save(update_fields=["llm_backend"])
            fake_graph.reset_mock()
            with patch("chat.api.views.build_api_query_graph", return_value=fake_graph):
                asked = self.api.post(
                    "/api/v1/messages/",
                    {"content": "How many unpaid orders?"},
                    format="json",
                )
            self.assertEqual(asked.status_code, 200)
            state = fake_graph.invoke.call_args[0][0]
            self.assertEqual(state.llm_backend, backend)

    def test_chat_endpoint_forwards_mcp_authorization(self):
        self._ready_workspace()
        raw = self._approve_and_mint()
        self._auth(raw)
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {
            "sql": "SELECT 1",
            "validation_result": {"valid": True, "kind": "ok"},
        }
        with patch("chat.api.views.build_api_query_graph", return_value=fake_graph):
            asked = self.api.post(
                "/api/v1/chat/",
                {"message": "How many unpaid orders?"},
                format="json",
                HTTP_X_MCP_AUTHORIZATION="Bearer restaurant-jwt",
            )
        self.assertEqual(asked.status_code, 200)
        state = fake_graph.invoke.call_args[0][0]
        self.assertEqual(
            state.mcp_headers.get("Authorization"),
            "Bearer restaurant-jwt",
        )

    def test_chat_endpoint_uses_org_mcp_token_without_header(self):
        self._ready_workspace()
        raw = self._approve_and_mint()
        self._auth(raw)
        org = organization_for(self.user)
        org.set_mcp_access_token("stored-jwt")
        org.save(update_fields=["mcp_auth_ciphertext"])
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {
            "sql": "SELECT 1",
            "validation_result": {"valid": True, "kind": "ok"},
        }
        with patch("chat.api.views.build_api_query_graph", return_value=fake_graph):
            asked = self.api.post(
                "/api/v1/chat/",
                {"message": "How many unpaid orders?"},
                format="json",
            )
        self.assertEqual(asked.status_code, 200)
        state = fake_graph.invoke.call_args[0][0]
        self.assertEqual(state.mcp_headers.get("Authorization"), "Bearer stored-jwt")

    def test_chat_endpoint_header_overrides_org_mcp_token(self):
        self._ready_workspace()
        raw = self._approve_and_mint()
        self._auth(raw)
        org = organization_for(self.user)
        org.set_mcp_access_token("stored-jwt")
        org.save(update_fields=["mcp_auth_ciphertext"])
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {
            "sql": "SELECT 1",
            "validation_result": {"valid": True, "kind": "ok"},
        }
        with patch("chat.api.views.build_api_query_graph", return_value=fake_graph):
            asked = self.api.post(
                "/api/v1/chat/",
                {"message": "How many unpaid orders?"},
                format="json",
                HTTP_X_MCP_AUTHORIZATION="Bearer restaurant-jwt",
            )
        self.assertEqual(asked.status_code, 200)
        state = fake_graph.invoke.call_args[0][0]
        self.assertEqual(state.mcp_headers.get("Authorization"), "Bearer restaurant-jwt")


class RuntimeEnvTests(TestCase):
    def test_production_refuses_insecure_secret(self):
        from django.core.exceptions import ImproperlyConfigured

        from DjangoForAI.runtime_env import resolve_secret_and_debug

        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_and_debug({"APP_ENV": "production"})
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_and_debug(
                {
                    "APP_ENV": "production",
                    "DJANGO_SECRET_KEY": "django-insecure-x",
                    "DJANGO_DEBUG": "true",
                }
            )

    def test_dev_allows_insecure_default(self):
        from DjangoForAI.runtime_env import resolve_secret_and_debug

        secret, debug = resolve_secret_and_debug({})
        self.assertTrue(debug)
        self.assertTrue(secret.startswith("django-insecure-"))

    def test_explicit_debug_false_requires_real_secret(self):
        from django.core.exceptions import ImproperlyConfigured

        from DjangoForAI.runtime_env import resolve_secret_and_debug

        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_and_debug({"DEBUG": "false"})
        secret, debug = resolve_secret_and_debug(
            {"DJANGO_SECRET_KEY": "production-secret-key-value", "DEBUG": "false"}
        )
        self.assertFalse(debug)
        self.assertEqual(secret, "production-secret-key-value")


class LocalLlmFallbackTests(TestCase):
    def test_local_backend_does_not_fall_back_to_gemini(self):
        import os

        from chat.api.chat_service import ChatService, LLMUnavailable

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}):
            with patch.object(
                ChatService,
                "ask_on_premise_ai",
                side_effect=LLMUnavailable("down"),
            ):
                with patch.object(ChatService, "ask_ai") as ask_ai:
                    with self.assertRaises(LLMUnavailable):
                        ChatService.ask_for_backend("hello", backend="local")
                    ask_ai.assert_not_called()


class WorkspaceProductTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery9"
        self.user = User.objects.create_user(
            username="api@example.com",
            email="api@example.com",
            password=self.password,
        )
        self.client = Client()
        self.client.force_login(self.user)
        org = ensure_organization_for_user(self.user, product_mode="api")
        apply_product_mode(org, "api")

    def test_register_api_then_chooses_api_setup(self):
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
        self.assertEqual(response.url, reverse("onboarding") + "?change=products")
        chosen = guest.post(
            reverse("onboarding"),
            {"action": "save_product", "product": "api", "change": "products"},
        )
        self.assertEqual(chosen.status_code, 302)
        self.assertEqual(chosen.url, reverse("onboarding") + "?track=api")

    def test_api_catalog_does_not_make_chat_ready(self):
        apply_product_mode(organization_for(self.user), "chat")
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
        self.assertIn("On this page", html)
        self.assertIn("Example response", html)
        self.assertContains(page, "Request API key")
        self.assertNotIn('href="/developers/mcp/"', html)

    def test_mcp_docs_page_has_in_page_toc(self):
        apply_product_mode(organization_for(self.user), "mcp")
        page = self.client.get(reverse("mcp_docs"))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("On this page", html)
        self.assertIn('href="#request-access"', html)
        self.assertIn('href="#overview"', html)
        self.assertIn('href="#auth"', html)
        self.assertIn('href="#list"', html)
        self.assertIn("X-MCP-Authorization", html)
        self.assertIn("permission_denied", html)
        self.assertContains(page, "Request MCP key")
        self.assertContains(page, "list_orders")
        self.assertNotIn('href="/developers/"', html)

    def test_api_messages_are_not_shown_in_chat_history(self):
        apply_product_mode(organization_for(self.user), "chat")
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
        org = ensure_organization_for_user(self.user, product_mode="api")
        apply_product_mode(org, "api")
        ApiAccessRequest.objects.create(
            user=self.user,
            kind=ApiAccessRequest.KIND_API,
            status=ApiAccessRequest.STATUS_APPROVED,
        )

    def test_approved_state_shows_copy_button(self):
        page = self.client.get(reverse("developers"))
        html = page.content.decode()
        self.assertContains(page, "Copy the key")
        self.assertNotIn("Create API key", html)
        self.assertNotIn("Copy secret", html)

    def test_copy_rejects_wrong_password(self):
        response = self.client.post(
            reverse("developers"),
            {"action": "copy_key", "password": "wrong-password"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(ApiKey.objects.filter(user=self.user).exists())

    def test_copy_with_password_returns_key_once(self):
        response = self.client.post(
            reverse("developers"),
            {"action": "copy_key", "password": self.password},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        raw = payload["key"]
        self.assertTrue(raw.startswith("qm_live_"))
        self.assertTrue(ApiKey.objects.filter(user=self.user).exists())
        page = self.client.get(reverse("developers"))
        self.assertNotIn(raw, page.content.decode())
        self.assertContains(page, "••••")


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
        self.assertEqual(self.client.get("/developers/mcp/").status_code, 302)

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
        self.assertEqual(self.client.get("/developers/mcp/").status_code, 404)

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
        self.assertEqual(response.url, reverse("onboarding") + "?change=products")


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

    def test_platform_admin_approves_any_org_api_request(self):
        staff = User.objects.create_superuser(
            username="staff",
            email="staff@querymind.test",
            password=self.password,
        )
        other_request = ApiAccessRequest.objects.create(
            user=self.other,
            status=ApiAccessRequest.STATUS_PENDING,
        )
        self.client.force_login(staff)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Staff dashboard")
        self.assertContains(page, "other@example.com")
        approve = self.client.post(
            reverse("dashboard"),
            {"action": "approve_api", "request_id": other_request.id},
        )
        self.assertEqual(approve.status_code, 302)
        other_request.refresh_from_db()
        self.assertEqual(other_request.status, ApiAccessRequest.STATUS_APPROVED)

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

    def test_register_then_choose_mcp_on_setup(self):
        guest = Client()
        response = guest.post(
            reverse("register"),
            {
                "name": "MCP",
                "email": "mcp-setup@example.com",
                "password": self.password,
                "password_confirm": self.password,
                "product": "mcp",
                "mcp_server_url": "http://127.0.0.1:8001/mcp",
                "key_note": "ServeEasy staff chat",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding") + "?change=products")
        user = User.objects.get(username="mcp-setup@example.com")
        org = organization_for(user)
        self.assertEqual(org.product_mode, "")
        self.assertEqual(org.mcp_server_url, "")
        self.assertFalse(ApiAccessRequest.objects.filter(user=user).exists())
        chosen = guest.post(
            reverse("onboarding"),
            {
                "action": "save_product",
                "product": "mcp",
                "change": "products",
                "key_note": "ServeEasy staff chat",
            },
        )
        self.assertEqual(chosen.status_code, 302)
        self.assertEqual(chosen.url, reverse("onboarding") + "?track=mcp")
        org.refresh_from_db()
        self.assertEqual(org.product_mode, "mcp")
        req = ApiAccessRequest.objects.get(user=user)
        self.assertEqual(req.kind, ApiAccessRequest.KIND_MCP)
        self.assertEqual(req.status, ApiAccessRequest.STATUS_PENDING)

    def test_register_then_choose_chat_starts_database_setup(self):
        guest = Client()
        response = guest.post(
            reverse("register"),
            {
                "name": "Chat",
                "email": "chat-setup@example.com",
                "password": self.password,
                "password_confirm": self.password,
                "product": "chat",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding") + "?change=products")
        chosen = guest.post(
            reverse("onboarding"),
            {"action": "save_product", "product": "chat", "change": "products"},
        )
        self.assertEqual(chosen.status_code, 302)
        self.assertEqual(chosen.url, reverse("onboarding") + "?track=chat")
        self.assertFalse(
            ApiAccessRequest.objects.filter(
                user__username="chat-setup@example.com"
            ).exists()
        )

    def test_register_page_is_credentials_only(self):
        page = Client().get(reverse("register"))
        html = page.content.decode()
        self.assertIn('name="name"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertNotIn('name="product"', html)
        self.assertNotIn("mcp_server_url", html)
        self.assertNotIn('value="chat"', html)
        self.assertNotIn('value="mcp"', html)

    def test_chat_only_org_cannot_open_developers(self):
        page = self.client.get(reverse("developers"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("ask"))

    def test_chat_only_org_cannot_open_mcp_docs(self):
        page = self.client.get(reverse("mcp_docs"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("ask"))

    def test_api_only_org_cannot_open_ask(self):
        apply_product_mode(self.org, "api")
        page = self.client.get(reverse("ask"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("developers"))

    def test_api_only_org_cannot_open_mcp_docs(self):
        apply_product_mode(self.org, "api")
        page = self.client.get(reverse("mcp_docs"))
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.url, reverse("developers"))

    def test_admin_can_move_chat_to_mcp_without_wiping_chat(self):
        chat = self._ready_chat()
        response = self.client.post(
            reverse("dashboard"),
            {"action": "save_product", "product": "mcp", "llm_backend": "local"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("track=mcp", response.url)
        self.org.refresh_from_db()
        self.assertEqual(self.org.product_mode, "mcp")
        chat.refresh_from_db()
        self.assertEqual(chat.db_name, "shop")
        self.assertEqual(chat.allowed_tables, ["orders"])

    def test_admin_updates_column_access_from_data_page(self):
        workspace = self._ready_chat()
        workspace.discovered_tables = ["orders", "products"]
        workspace.discovered_columns = {
            "orders": ["id", "status", "total_amount"],
            "products": ["id", "name"],
        }
        workspace.schema_text = (
            "DATABASE: PostgreSQL\n\n"
            "TABLE: orders\n- id TEXT\n- status TEXT\n- total_amount TEXT\n\n"
            "TABLE: products\n- id TEXT\n- name TEXT\n"
        )
        workspace.save()
        page = self.client.get(reverse("data_access"))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('name="allowed_columns"', html)
        self.assertNotIn("Change access", html)
        saved = self.client.post(
            reverse("data_access"),
            {
                "action": "save_access",
                "allowed_tables": ["orders"],
                "allowed_columns": ["orders.id", "orders.status"],
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(saved.url, reverse("data_access"))
        workspace.refresh_from_db()
        self.assertEqual(workspace.allowed_tables, ["orders"])
        self.assertEqual(workspace.allowed_columns, {"orders": ["id", "status"]})
        self.assertNotIn("total_amount", workspace.schema_text)

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
        state = local_graph.return_value.stream.call_args[0][0]
        self.assertEqual(state.product_surface, "chat")
        self.assertEqual(state.mcp_headers, {})

    @patch("chat.views_stream.build_online_graph")
    @patch("chat.views_stream.build_on_premise_graph")
    def test_stream_forwards_mcp_authorization_header(self, local_graph, online_graph):
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
            HTTP_X_MCP_AUTHORIZATION="Bearer restaurant-jwt",
        )
        self.assertEqual(response.status_code, 200)
        list(response.streaming_content)
        state = local_graph.return_value.stream.call_args[0][0]
        self.assertEqual(state.mcp_headers.get("Authorization"), "Bearer restaurant-jwt")

    @patch("chat.views_stream.build_online_graph")
    @patch("chat.views_stream.build_on_premise_graph")
    def test_stream_uses_org_mcp_token_without_header(self, local_graph, online_graph):
        self._ready_chat()
        self.org.set_mcp_access_token("stored-jwt")
        self.org.save(update_fields=["mcp_auth_ciphertext"])
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
        state = local_graph.return_value.stream.call_args[0][0]
        self.assertEqual(state.mcp_headers.get("Authorization"), "Bearer stored-jwt")

    @patch("chat.views_stream.build_online_graph")
    @patch("chat.views_stream.build_on_premise_graph")
    def test_stream_header_overrides_org_mcp_token(self, local_graph, online_graph):
        self._ready_chat()
        self.org.set_mcp_access_token("stored-jwt")
        self.org.save(update_fields=["mcp_auth_ciphertext"])
        conversation = Conversation.objects.create(user=self.admin, title="Q")
        message = Message.objects.create(
            conversation=conversation, content="How many orders?", is_user=True
        )
        local_graph.return_value.stream.return_value = iter([])
        online_graph.return_value.stream.return_value = iter([])
        response = self.client.get(
            reverse("stream_chat", args=[conversation.id]),
            {"message_id": message.id},
            HTTP_X_MCP_AUTHORIZATION="Bearer restaurant-jwt",
        )
        self.assertEqual(response.status_code, 200)
        list(response.streaming_content)
        state = local_graph.return_value.stream.call_args[0][0]
        self.assertEqual(state.mcp_headers.get("Authorization"), "Bearer restaurant-jwt")

    def test_team_stores_encrypted_mcp_token_without_echoing_it(self):
        secret = "restaurant-jwt-secret"
        saved = self.client.post(
            reverse("team"),
            {
                "action": "save_mcp",
                "mcp_server_url": "http://127.0.0.1:8001/mcp",
                "mcp_access_token": secret,
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.get_mcp_access_token(), secret)
        self.assertNotEqual(self.org.mcp_auth_ciphertext, secret)
        page = self.client.get(reverse("team"))
        html = page.content.decode()
        self.assertNotIn(secret, html)
        self.assertNotIn(self.org.mcp_auth_ciphertext, html)
        kept = self.client.post(
            reverse("team"),
            {
                "action": "save_mcp",
                "mcp_server_url": "http://127.0.0.1:8001/mcp",
                "mcp_access_token": "",
            },
        )
        self.assertEqual(kept.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.get_mcp_access_token(), secret)
        cleared = self.client.post(
            reverse("team"),
            {
                "action": "save_mcp",
                "mcp_server_url": "http://127.0.0.1:8001/mcp",
                "clear_mcp_access_token": "1",
            },
        )
        self.assertEqual(cleared.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.get_mcp_access_token(), "")

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

    def test_switching_to_api_keeps_llm_backend(self):
        apply_product_mode(self.org, "api")
        self.org.refresh_from_db()
        self.assertEqual(self.org.product_mode, "api")
        self.assertEqual(self.org.llm_backend, "local")

    def test_api_onboarding_offers_local_and_online_llm(self):
        apply_product_mode(self.org, "api")
        page = self.client.get(reverse("onboarding") + "?track=api")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('name="llm_backend"', html)
        self.assertIn('value="local"', html)
        self.assertIn('value="online"', html)

    def test_admin_can_save_online_llm_for_api_only(self):
        response = self.client.post(
            reverse("dashboard"),
            {"action": "save_product", "product": "api", "llm_backend": "online"},
        )
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.product_mode, "api")
        self.assertEqual(self.org.llm_backend, "online")


class StaffAdminBrandingTests(TestCase):
    def test_login_is_querymind_branded(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("QueryMind staff", html)
        self.assertIn("Email or username", html)
        self.assertNotIn("Django administration", html)

    def test_index_shows_platform_copy_for_superuser(self):
        User.objects.create_superuser(
            "admin@querymind.local",
            "admin@querymind.local",
            "CorrectHorseBattery9",
        )
        self.client.login(
            username="admin@querymind.local",
            password="CorrectHorseBattery9",
        )
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("QueryMind staff", html)
        self.assertIn("Do not mint a superuser API key", html)
        self.assertIn("Organizations", html)

    def test_api_keys_cannot_be_created_in_admin(self):
        from django.contrib.admin.sites import site

        from chat.models import ApiKey

        request = MagicMock()
        request.user.is_superuser = True
        self.assertFalse(site._registry[ApiKey].has_add_permission(request))


class StreamEncodingTests(TestCase):
    def test_sse_serializes_decimal_rows(self):
        from decimal import Decimal

        from chat.views_stream import _sse

        event = _sse("rows", rows=[{"average_price": Decimal("19.9900")}])
        payload = json.loads(event.removeprefix("data: ").strip())
        self.assertEqual(payload["type"], "rows")
        self.assertEqual(payload["rows"][0]["average_price"], "19.9900")

    def test_stream_sends_decimal_rows_instead_of_json_error(self):
        from decimal import Decimal

        password = "CorrectHorseBattery9"
        admin = User.objects.create_user(
            username="avg@example.com",
            email="avg@example.com",
            password=password,
        )
        org = ensure_organization_for_user(admin, name="Avg Co", product_mode="chat")
        org.llm_backend = "local"
        org.save(update_fields=["llm_backend"])
        WorkspaceConnection.objects.create(
            user=admin,
            organization=org,
            kind=WorkspaceConnection.KIND_CHAT,
            host="127.0.0.1",
            db_name="shop",
            db_user="reader",
            allowed_tables=["products"],
            allowed_columns={"products": ["price"]},
        )
        conversation = Conversation.objects.create(user=admin, title="Q")
        message = Message.objects.create(
            conversation=conversation, content="average product price", is_user=True
        )
        client = Client()
        client.force_login(admin)

        class FakeGraph:
            def stream(self, state, config=None):
                yield {
                    "sql_generator": {
                        "sql": "SELECT AVG(price) AS average_price FROM products"
                    }
                }
                yield {
                    "sql_executor": {
                        "execution_result": {
                            "success": True,
                            "rows": [{"average_price": Decimal("42.50")}],
                            "kind": "success",
                        },
                        "answer_kind": "success",
                    }
                }
                yield {
                    "result_formatter": {
                        "final_answer": "The average product price is 42.50.",
                        "answer_kind": "success",
                    }
                }

        with patch(
            "chat.views_stream.build_on_premise_graph", return_value=FakeGraph()
        ):
            response = client.get(
                reverse("stream_chat", args=[conversation.id]),
                {"message_id": message.id},
            )
            self.assertEqual(response.status_code, 200)
            body = b"".join(response.streaming_content).decode()
        self.assertNotIn("not JSON serializable", body)
        self.assertIn('"average_price": "42.50"', body)


