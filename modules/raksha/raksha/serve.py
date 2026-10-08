"""uvicorn entrypoint:  uvicorn --factory raksha.serve:app   (configuration from RAKSHA_* env vars)."""
import os

from .api import Settings, create_app


def app():
    a = create_app(Settings.from_env())
    deps = os.environ.get("RAKSHA_DEPENDENCIES_FILE")
    if deps:
        a.state.load_dependencies(deps)
    return a
