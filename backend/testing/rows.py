"""Direct database helpers and request bodies for the API tests.

The tests share one SQLite file per run, so every test removes the rows
it creates (``delete_rows``); rows inserted directly use fixed UUIDs so
the per-column ``genid`` counters and the snapshot ids do not move."""

from db.database import get_db_direct
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User
from utils.kubernetes_utils import PodStatus

NOTEBOOKS = "/v1alpha1/notebooks"
MODELS = "/v1alpha1/models"

NOT_READY = PodStatus(False, "Pending")


def notebook_payload(name):
    return {
        "name": name,
        "type": "vscode",
        "framework": "python",
        "nvidia_gpu": False,
    }


def membership_of(sub):
    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == sub).one()
        org = (
            db.query(Organization)
            .filter(Organization.slug == DEFAULT_ORG_SLUG)
            .one()
        )
        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user.id, Membership.org_id == org.id)
            .one()
        )
        return user, membership
    finally:
        db.close()


def default_org_id():
    db = get_db_direct()
    try:
        return (
            db.query(Organization)
            .filter(Organization.slug == DEFAULT_ORG_SLUG)
            .one()
            .id
        )
    finally:
        db.close()


def user_id(sub):
    return membership_of(sub)[0].id


def add_row(row):
    db = get_db_direct()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def delete_rows(model, *ids):
    db = get_db_direct()
    try:
        db.query(model).filter(model.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()
