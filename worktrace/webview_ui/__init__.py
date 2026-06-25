"""Optional WebView UI spike package.

Phase 0A placeholder. This package exists so the boundary tests in
``tests/test_ui_backend_boundary.py`` can enforce the WebView <-> backend
contract before any WebView page or bridge is implemented.

Boundary rules (enforced by tests):

- Modules in this package may import ``worktrace.api`` and nothing else from the
  backend. They must not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.security``, or ``worktrace.runtime``.
- ``bridge`` (when implemented) is the only data path between JS and Python. It
  must not return tracebacks and must not log window titles, paths, notes, or
  copied text.
- Frontend resources (HTML/CSS/JS) must be local files with no ``http://``,
  ``https://``, CDN, or Google Fonts references.

The default entry point remains ``python -m worktrace.main`` (Tkinter UI).
The WebView entry point (``python -m worktrace.webview_main``) is a future
Phase 0B deliverable and is not implemented here.
"""
