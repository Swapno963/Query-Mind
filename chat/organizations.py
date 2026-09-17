from __future__ import annotations

from django.contrib.auth.models import User

from chat.models import Organization, OrganizationMembership


def ensure_organization_for_user(user: User, name: str = "") -> Organization:
    membership = (
        OrganizationMembership.objects.filter(user=user, is_active=True)
        .select_related("organization")
        .first()
    )
    if membership:
        return membership.organization
    org = Organization.objects.create(
        name=(name or user.get_full_name() or user.email or user.username)[:200],
        created_by=user,
    )
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=OrganizationMembership.ROLE_ADMIN,
        is_active=True,
    )
    return org


def active_membership(user) -> OrganizationMembership | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return (
        OrganizationMembership.objects.filter(user=user, is_active=True)
        .select_related("organization")
        .first()
    )


def organization_for(user) -> Organization | None:
    membership = active_membership(user)
    return membership.organization if membership else None


def is_org_admin(user) -> bool:
    membership = active_membership(user)
    return bool(
        membership and membership.role == OrganizationMembership.ROLE_ADMIN
    )


def is_org_member_active(user) -> bool:
    if not user or not user.is_active:
        return False
    membership = active_membership(user)
    return bool(membership)


def require_same_org(user, other_user) -> bool:
    left = organization_for(user)
    right = organization_for(other_user)
    return bool(left and right and left.pk == right.pk)


def create_member(*, admin, email: str, name: str, password: str) -> User:
    if not is_org_admin(admin):
        raise PermissionError("Only an organization administrator can create users.")
    org = organization_for(admin)
    if User.objects.filter(username=email).exists():
        raise ValueError("An account with that email already exists.")
    user = User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name=(name or "")[:150],
    )
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=OrganizationMembership.ROLE_MEMBER,
        is_active=True,
    )
    return user


def set_member_active(*, admin, user, is_active: bool) -> OrganizationMembership:
    if not is_org_admin(admin):
        raise PermissionError("Only an organization administrator can manage users.")
    membership = OrganizationMembership.objects.filter(
        organization=organization_for(admin),
        user=user,
    ).first()
    if membership is None:
        raise PermissionError("That user is not in your organization.")
    if membership.role == OrganizationMembership.ROLE_ADMIN and not is_active:
        raise PermissionError("The organization administrator cannot be deactivated.")
    membership.is_active = is_active
    membership.save(update_fields=["is_active"])
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    if not is_active:
        from django.utils import timezone

        from chat.models import ApiKey

        ApiKey.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    return membership
