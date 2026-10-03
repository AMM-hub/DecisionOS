"""Structural Authorization Protection Meta-Test Suite.

Introspects all registered FastAPI routes in decisionos_analytics to guarantee
that every tenant-scoped endpoint mandates authenticated user + authorized tenant
via ctx() or require_tenant_context() before executing handler logic.
"""

from __future__ import annotations

import ast
import inspect
import tempfile
import textwrap
from pathlib import Path

from decisionos_analytics.api import create_app


def test_all_tenant_routes_enforce_authorization():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        app = create_app(Path(tmpdir))
        store = getattr(app.state, "store", None)

        unprotected_routes = []
        total_tenant_routes = 0

        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            path = getattr(route, "path", "")

            # Skip health check and OpenAPI docs endpoints
            if not endpoint or path in ("/v1/health", "/docs", "/redoc", "/openapi.json"):
                continue

            sig = inspect.signature(endpoint)
            params = sig.parameters

            # Check if route accepts tenant or user context headers
            accepts_tenant_ctx = "x_tenant" in params or "x_user" in params

            if accepts_tenant_ctx:
                total_tenant_routes += 1

                # Inspect AST of the endpoint function to verify ctx() or require_tenant_context is invoked
                try:
                    source = textwrap.dedent(inspect.getsource(endpoint))
                    tree = ast.parse(source)

                    calls_auth = False
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            # Check function name called
                            if (isinstance(node.func, ast.Name) and node.func.id in ("ctx", "require_tenant_context")) or (isinstance(node.func, ast.Attribute) and node.func.attr in ("ctx", "require_tenant_context")):
                                calls_auth = True
                                break

                    if not calls_auth:
                        unprotected_routes.append(f"{route.methods} {path}")

                except (SyntaxError, IndentationError, TypeError) as exc:
                    unprotected_routes.append(f"{path} (AST error: {exc})")

        if store and hasattr(store, "conn"):
            store.conn.close()

    assert total_tenant_routes >= 30, f"Expected at least 30 tenant-scoped routes, found {total_tenant_routes}"
    assert not unprotected_routes, (
        f"The following {len(unprotected_routes)} tenant-scoped route(s) accept tenant context headers "
        f"but fail to call mandatory authorization (ctx / require_tenant_context):\n"
        + "\n".join(unprotected_routes)
    )
