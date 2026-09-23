"""Point the app at a throwaway data directory before it is ever imported.

app.config builds its Settings at import time and creates directories as a
side effect, and app.db.database builds its engine from that. Setting these
here -- before any test module imports the app -- means individual tests do
not have to reload modules, which was re-declaring the ORM tables on an
already-populated MetaData.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="tikrec-tests-")

os.environ.setdefault("DATA_DIR", _TMP)
os.environ.setdefault("RECORDINGS_DIR", os.path.join(_TMP, "recordings"))
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(_TMP, "test.db").replace("\\", "/")
)
os.environ.setdefault("APP_PASSWORD", "test-password")
