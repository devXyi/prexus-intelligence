import os
import sys
import tempfile

# Must be set BEFORE core.config is imported (it creates directories at import time).
os.environ.setdefault("METEORIUM_BASE", tempfile.mkdtemp(prefix="meteorium-test-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
