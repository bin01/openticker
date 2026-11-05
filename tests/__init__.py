"""Every test runs against a throwaway OPENTICKER_HOME, set here before any test module imports the app, so tests never
touch the person's real watchlist, positions, alerts or Tick conversations."""
import os
import tempfile

os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
