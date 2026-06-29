"""WebView UI package (Phase 1: default and only shipping UI).

As of Phase 1, the WebView shell started by ``worktrace.webview_main`` is the
default and only shipping UI for WorkTrace. The default entry point
``python -m worktrace.main`` starts the WebView UI; the packaged
``WorkTrace.exe`` defaults to the WebView UI as well. Phase 6F deleted the
legacy ``worktrace.ui`` (Tkinter / CustomTkinter) package; there is no
Tkinter fallback.

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

