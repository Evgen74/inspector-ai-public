"""Repo-wide pytest defaults (AG-00).

Tests must not depend on the developer's admin overrides file (`.cache/matrix_overrides.json`, written by the API from
/admin/normative): the matrix seed is the baseline. Tests of the overrides loader set the variable themselves.
"""

from __future__ import annotations

import os

os.environ.setdefault("INSPECTOR_MATRIX_OVERRIDES", "off")
