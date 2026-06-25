"""Optional WebView UI spike package.

Phase 0B: minimal shell + bridge. The default entry point remains
``python -m worktrace.main`` (Tkinter UI). The WebView entry point
``python -m worktrace.webview_main`` starts an optional spike shell.

Boundary rules (enforced by tests/test_ui_backend_boundary.py):

- Modules in this package may import ``worktrace.api`` and nothing else from the
  backend. They must not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.security``, or ``worktrace.runtime``.
- ``bridge`` is the only data path between JS and Python. It must not return
  tracebacks and must not log window titles, paths, notes, or copied text.
- Frontend resources (HTML/CSS/JS) must be local files with no ``http://``,
  ``https://``, CDN, or Google Fonts references, and must not use
  ``localStorage``/``sessionStorage`` for sensitive data.
"""

