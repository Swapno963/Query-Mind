"""QueryMind branding for Django’s staff admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.forms import CharField, TextInput


class StaffAdminAuthenticationForm(AuthenticationForm):
    username = CharField(
        label="Email or username",
        widget=TextInput(
            attrs={"autofocus": True, "autocomplete": "username", "autocapitalize": "none"}
        ),
    )


admin.site.site_header = "QueryMind staff"
admin.site.site_title = "QueryMind"
admin.site.index_title = "Platform"
admin.site.site_url = "/"
admin.site.empty_value_display = "—"
admin.site.login_form = StaffAdminAuthenticationForm
admin.site.enable_nav_sidebar = True

if admin.site.is_registered(User):
    admin.site.unregister(User)


@admin.register(User)
class StaffUserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)
    list_per_page = 50
