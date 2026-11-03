"""The partner test package. Importing it installs the kit-tree fence BEFORE tmp_cleanup registers its exit handler (see _tree_guard.py):
atexit runs last in, first out, so tmp_cleanup removes this process's temp dirs first and the guard compares last."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _tree_guard  # noqa: E402,F401
import _roots  # noqa: E402

_roots.scrub_ambient()   # BUG-784: no test inherits the session's data root
