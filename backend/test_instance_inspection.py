"""The shared instance HTTP layer (api/instance_inspection.py) and the
shared stale-status poll (utils/instance_status.py refresh_stale)."""

from types import SimpleNamespace
from unittest import mock

from core import create_app
from db.database import get_db_direct
from models.notebook import Notebook
from models.vectordb_instance import DBVectorDBInstance
from utils.instance_status import refresh_stale, stale_status_clause

INSPECTION_ROUTES = {
    # (prefix, restart route registered)
    "/v1alpha1/inferenceInstance": True,
    "/v1alpha1/vectordb_instances": True,
    "/v1alpha1/notebooks": False,
}


def _walk(routes):
    """Every APIRoute under app.routes; an included router shows up
    there as one entry that wraps the router it was included from."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _walk(included.routes)
        elif hasattr(route, "methods"):
            yield route


def _routes():
    return {
        (route.path, method): route
        for route in _walk(create_app().routes)
        for method in route.methods
    }


def test_the_three_kinds_register_the_expected_routes():
    routes = _routes()
    names = set()
    for prefix, restart in INSPECTION_ROUTES.items():
        for suffix in ("/logs", "/events"):
            route = routes[(f"{prefix}/{{id}}{suffix}", "GET")]
            names.add(route.name)
        restart_route = routes.get((f"{prefix}/{{id}}/restart", "POST"))
        assert (restart_route is not None) is restart, prefix
        if restart_route is not None:
            names.add(restart_route.name)
    # One operation id per route: the names carry the kind.
    assert names == {
        "get_inference_instance_logs",
        "get_inference_instance_events",
        "restart_inference_instance",
        "get_vector_database_instance_logs",
        "get_vector_database_instance_events",
        "restart_vector_database_instance",
        "get_notebook_logs",
        "get_notebook_events",
    }
    # The openapi document accepts them (duplicate operation ids would
    # be reported there).
    paths = create_app().openapi()["paths"]
    assert "/v1alpha1/notebooks/{id}/logs" in paths
    assert "/v1alpha1/notebooks/{id}/restart" not in paths


def _rows(*rows):
    db = get_db_direct()
    for row in rows:
        db.add(row)
    db.commit()
    return db, [row.id for row in rows]


def _delete(db, model, ids):
    for row_id in ids:
        row = db.get(model, row_id)
        if row is not None:
            db.delete(row)
    db.commit()
    db.close()


def test_refresh_stale_builds_one_controller_and_isolates_row_errors():
    """One make_controller() per tick, none without rows; a row whose
    check raises is logged and the next row still refreshed."""
    db, ids = _rows(
        DBVectorDBInstance(vectordb_id=None, status="Pending"),
        DBVectorDBInstance(vectordb_id=None, status="Failed"),
        DBVectorDBInstance(vectordb_id=None, status="Running"),
        DBVectorDBInstance(vectordb_id=None, status="Stopped"),
        DBVectorDBInstance(vectordb_id=None, status=None),
    )
    make_controller = mock.Mock(return_value=SimpleNamespace(name="ctrl"))
    seen = []

    def check(row, session, controller):
        assert session is db
        assert controller is make_controller.return_value
        seen.append(row.id)
        if row.status == "Failed":
            raise RuntimeError("boom")

    try:
        with mock.patch("utils.instance_status.logger") as logger:
            count = refresh_stale(
                db, DBVectorDBInstance, check, make_controller
            )
        # Pending, Failed and NULL are stale; Running and Stopped are not.
        assert count == 3
        assert set(seen) == {ids[0], ids[1], ids[4]}
        make_controller.assert_called_once_with()
        logger.exception.assert_called_once()
        assert logger.exception.call_args.args[1] == ids[1]
    finally:
        _delete(db, DBVectorDBInstance, ids)


def test_refresh_stale_without_rows_builds_no_controller():
    db = get_db_direct()
    make_controller = mock.Mock()
    try:
        stale = db.query(Notebook).filter(stale_status_clause(Notebook)).all()
        assert stale == []
        assert refresh_stale(db, Notebook, mock.Mock(), make_controller) == 0
        make_controller.assert_not_called()
    finally:
        db.close()


def test_refresh_stale_applies_the_given_query_options():
    """should-fix 2 (PR 25 review): a `check` that reads a relationship
    (e.g. the inference poller reading `instance.model.category`) must
    be able to join it -- without `options`, every stale row issues its
    own lazy-load SELECT every tick."""
    db = mock.MagicMock()
    chain = db.query.return_value.filter.return_value
    chain.options.return_value.all.return_value = []
    option = mock.Mock()

    count = refresh_stale(
        db, Notebook, mock.Mock(), mock.Mock(), options=[option]
    )

    assert count == 0
    chain.options.assert_called_once_with(option)
    chain.options.return_value.all.assert_called_once_with()


def test_refresh_stale_statuses_joins_the_inference_instance_model():
    """The inference poller reads `instance.model.category`
    (_engine_chart_for), so _refresh_stale_statuses must pass that
    relationship through to refresh_stale as a joinedload."""
    import api.inference_status as inference_status
    from models.inference_instance import DBInferenceInstance

    with mock.patch.object(
        inference_status, "refresh_stale", return_value=0
    ) as refresh_stale_mock:
        inference_status._refresh_stale_statuses(mock.Mock())

    refresh_stale_mock.assert_called_once()
    _, kwargs = refresh_stale_mock.call_args
    (option,) = kwargs["options"]
    assert option.path.path[0].class_ is DBInferenceInstance
    assert option.path.path[1].key == "model"


def test_refresh_stale_status_skips_the_whole_engine_once_unreachable():
    """should-fix 3 (PR 25 review): with lazy construction, get_controller()
    no longer raises for a missing kubeconfig or an unreachable cluster,
    so the per-engine skip must come from controller.ensure_ready()
    instead -- one warning for the whole tick, not a traceback per row,
    and the _UNAVAILABLE cache must actually get used."""
    import api.inference_status as inference_status

    engine = SimpleNamespace(name="ollama")
    chart = SimpleNamespace()
    unreachable = mock.Mock()
    unreachable.ensure_ready.side_effect = RuntimeError("no kubeconfig")

    with (
        mock.patch.object(
            inference_status,
            "_engine_chart_for",
            return_value=(engine, chart),
        ),
        mock.patch.object(
            inference_status, "get_controller", return_value=unreachable
        ) as get_controller_mock,
        mock.patch.object(
            inference_status, "_refresh_status"
        ) as refresh_status_mock,
        mock.patch.object(inference_status, "logger") as logger,
    ):
        controllers: dict = {}
        row_a = SimpleNamespace(id="a")
        row_b = SimpleNamespace(id="b")
        inference_status._refresh_stale_status(row_a, mock.Mock(), controllers)
        inference_status._refresh_stale_status(row_b, mock.Mock(), controllers)

    # One controller build and one ensure_ready() attempt for the tick,
    # not one per row.
    get_controller_mock.assert_called_once_with("ollama")
    unreachable.ensure_ready.assert_called_once()
    assert controllers["ollama"] is inference_status._UNAVAILABLE
    logger.warning.assert_called_once()
    refresh_status_mock.assert_not_called()
