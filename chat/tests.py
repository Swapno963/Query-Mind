from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from connections.models import WorkspaceConnection
from connections.services.crypto import decrypt_secret

from .api_keys import generate_api_key
from .models import ApiAccessRequest, ApiKey, Conversation, Message


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
        self.assertEqual(response.url, reverse("developers"))

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
        self.assertEqual(response.url, reverse("developers"))

