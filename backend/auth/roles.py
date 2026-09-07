"""Membership roles, shared by auth and the API routers."""

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"
# Roles that may create and change resources.
WRITER_ROLES = (ROLE_ADMIN, ROLE_MEMBER)
