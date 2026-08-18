"""Public-repo test defaults; production identities still come from config."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def configured_test_identity():
    roles = {
        "owner": {"actor": "project_owner", "member": "Project Owner"},
        "operator": {"actor": "automation_operator", "member": "Automation Operator"},
        "reviewer": {"actor": "quality_reviewer", "member": "Quality Reviewer"},
    }
    candidates = []
    for module in tuple(sys.modules.values()):
        scan_mod = getattr(module, "scan_mod", None)
        if scan_mod is not None and hasattr(scan_mod, "ALL_MEMBERS"):
            candidates.append(scan_mod)
    unique_candidates = list({id(scan_mod): scan_mod for scan_mod in candidates}.values())
    runtime_dicts = ('_ai_runs', '_sessions', '_login_attempts', '_quiz_tokens')
    for scan_mod in unique_candidates:
        for name in runtime_dicts:
            state = getattr(scan_mod, name, None)
            if isinstance(state, dict):
                state.clear()
        scan_mod.ALL_MEMBERS = ["Project Owner"]
        scan_mod.LOGIN_MEMBERS = ["Project Owner"]
        scan_mod.CURRENT_MEMBER = "Project Owner"
        if hasattr(scan_mod, "ROLE_CONFIG"):
            scan_mod.ROLE_CONFIG = roles
    yield
    for scan_mod in unique_candidates:
        for name in runtime_dicts:
            state = getattr(scan_mod, name, None)
            if isinstance(state, dict):
                state.clear()
