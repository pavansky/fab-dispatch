"""The release version, shown in the app's About panel, /api/meta and /api/health.

Bumped with each release tag; a test keeps it equal to pyproject.toml, frontend/package.json and the
newest CHANGELOG entry. COMMIT is the deployed git commit (Vercel sets VERCEL_GIT_COMMIT_SHA).
"""

import os

APP_VERSION = "2.7.2"
COMMIT = (os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT") or "local")[:7]
