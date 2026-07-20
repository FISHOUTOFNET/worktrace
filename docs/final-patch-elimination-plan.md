# Final Patch-Elimination Owner Map

Starting baseline: `main` at `163148478a02d00ed84c7b46c1e7af021fb291c9`.

This document freezes the responsibility map before implementation. It is a
current-only pre-release convergence plan; no compatibility surface is part of
the target architecture.

| Responsibility | Sole owner / contract |
| --- | --- |
| Process, long-lived thread and worker lifecycle | `AppRuntime` |
| Platform capabilities | `RuntimePlatformAdapter` protocol with explicit Windows and fake implementations |
| Collector command state | `RuntimeCollectorControl` |
| Maintenance ordering, exclusion and restoration | `RuntimeMaintenanceCoordinator` |
| Database write exclusion | `ProcessDatabaseWriteGate` |
| Business transactions and generation effects | explicit `DomainUnitOfWork` command owner |
| Database replacement identity | database key plus durable `DATABASE_REPLACEMENT` generation |
| Backup and clear table membership/order | one static database content manifest |
| Projection write admission | persisted admission revision |
| Projection replay | explicit `ReplayBinding.REVISION` or `ReplayBinding.MEMBERS` |
| Python/Bridge/JavaScript settings status | one exact maintenance status DTO contract |
| Production composition | `worktrace.webview_main` and strict `ApplicationServices` |
| Test composition | explicit builders under `tests/support`, never replacement of production classes |

Implementation checkpoints use only the permanent Standard CI workflow:

1. runtime/platform lifecycle boundary;
2. maintenance, replacement, projection, transaction and composition boundary;
3. final semantic governance and documentation.

The branch remains unmerged and the pull request remains Draft until explicit
user confirmation.