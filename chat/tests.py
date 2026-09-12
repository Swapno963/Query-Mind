from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from connections.models import WorkspaceConnection
from connections.services.crypto import decrypt_secret

from .models import Conversation


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
