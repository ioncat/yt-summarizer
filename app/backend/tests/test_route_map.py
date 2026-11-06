"""NS-18 safety net (the method of NS-12): the routes and the OpenAPI schema of the app are recorded in route_snapshot.json.
A router split must leave paths, methods, endpoint names, the schema, and the order of every pair of routes that could match
the same request exactly as they were. To refresh the snapshot on purpose (a real API change), run the tests with
UPDATE_ROUTE_SNAPSHOT=1 and review the diff of route_snapshot.json."""
import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("route_snapshot.json")


def _current() -> dict:
    from main import app
    routes = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods is None:
            continue
        routes.append({"methods": sorted(methods), "path": r.path, "name": getattr(r, "name", "")})
    return {"routes": routes, "openapi": json.loads(json.dumps(app.openapi()))}


def _overlap(a: str, b: str) -> bool:
    """Could one request match both path templates? ({param} matches any one segment.)"""
    sa, sb = a.strip("/").split("/"), b.strip("/").split("/")
    return len(sa) == len(sb) and all(x == y or x.startswith("{") or y.startswith("{") for x, y in zip(sa, sb))


def _key(r: dict) -> str:
    return f'{",".join(r["methods"])} {r["path"]}'


if os.environ.get("UPDATE_ROUTE_SNAPSHOT") == "1":
    def test_update_the_snapshot():
        SNAPSHOT.write_text(json.dumps(_current(), indent=1, sort_keys=True), encoding="utf8")


def test_the_routes_are_the_recorded_ones():
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf8"))["routes"]
    current = _current()["routes"]
    assert len(current) >= 52
    assert sorted(map(_key, current)) == sorted(map(_key, recorded))                      # same paths and methods, none lost or added
    assert sorted((_key(r), r["name"]) for r in current) == sorted((_key(r), r["name"]) for r in recorded)   # same endpoints


def test_routes_that_could_match_the_same_request_keep_their_order():
    recorded = [r for r in json.loads(SNAPSHOT.read_text(encoding="utf8"))["routes"]]
    position = {_key(r): i for i, r in enumerate(_current()["routes"])}
    for i, a in enumerate(recorded):
        for b in recorded[i + 1:]:
            if set(a["methods"]) & set(b["methods"]) and _overlap(a["path"], b["path"]):
                assert position[_key(a)] < position[_key(b)], f"{_key(a)} must stay before {_key(b)}"


def test_the_openapi_schema_is_the_recorded_one():
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf8"))["openapi"]
    assert _current()["openapi"] == recorded
