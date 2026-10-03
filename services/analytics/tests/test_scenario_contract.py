"""DOS-QA-011 Scenario Template Contract Test.

Verifies that GET /v1/scenarios/templates returns sections as a list of strings
matching the frontend TypeScript ScenarioTemplate definition.
"""

from __future__ import annotations

import pytest


def test_scenario_templates_contract_shape(client):
    res = client.get("/v1/scenarios/templates")
    assert res.status_code == 200
    templates = res.json()
    assert isinstance(templates, list)
    assert len(templates) >= 1

    for tpl in templates:
        assert isinstance(tpl.get("template_id"), str)
        assert isinstance(tpl.get("name"), str)
        assert isinstance(tpl.get("description"), str)
        sections = tpl.get("sections")
        assert isinstance(sections, list)
        for section in sections:
            assert isinstance(section, str), f"Section item {section!r} must be a string, not an object"
