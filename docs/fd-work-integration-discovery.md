# FD Work integration discovery

This document records the non-sensitive browser contract observed on
2026-07-31 and conservatively rechecked through 2026-08-03. It intentionally contains no credentials,
cookies, tokens, personal data, client names, matter names or matter numbers,
or real time-entry content.

## Scope and safety

- Target URL:
  `https://work.fangdalaw.com/Works/WorkHourList?picker=day`.
- Discovery used a separate browser tab and did not save, submit, edit, or
  delete any real time entry.
- A synthetic, non-matching matter search was used to observe the empty-result
  contract. No real matter identifier is recorded here.
- Credentials were not read, filled, copied, or stored.

## Authentication and navigation

- Business host: `work.fangdalaw.com`.
- Login host: `work.fangdalaw.com`.
- No other top-level authentication host was observed or required. The
  navigation allowlist can therefore remain the exact singleton host
  `work.fangdalaw.com`; it must not allow all `*.fangdalaw.com`.
- An expired business-page session navigated in the same tab to:
  `/login?returnUrl=%2FWorks%2FWorkHourList%3Fpicker%3Dday`.
- The login page contains:
  - one `text` input labelled `邮箱/手机号/用户名`;
  - one `password` input labelled `密码`;
  - an optional `记住账号` checkbox;
  - a language selector whose observed default was `中文`;
  - one native `登录` button.
- No SSO button, QR-code login, CAPTCHA, MFA control, or authentication iframe
  was present in the observed login page.
- The login flow stays in the existing window. No authentication popup or
  second top-level window was opened.
- The `returnUrl` contract points back to the requested Work Hour List route.
  An already-authenticated visit ended at that exact route.
- Historical same-host navigation also showed `/loginToken` followed by
  `/Login`; neither route introduced another authentication host.
- Login, authentication errors, MFA/verification if later introduced,
  unauthorized pages, and unknown pages must remain fully visible. The
  integration must not inject its adapter or compact styles on those pages.
- The application has explicit `/permission` and `/404` route contracts.
  Fresh-browser rendering of those routes was affected by a dynamic-module
  load failure during discovery, so their final visual copy is not treated as
  stable. They are classified as `UNAUTHORIZED` and `ERROR` from their exact
  paths and always remain in full-page mode.

## Work Hour List and entry form

- The new-entry form is already present on the Work Hour List route as
  `form#basic`; opening a separate modal or navigating to a different page is
  not required.
- The form is React/Ant Design controlled UI. Native input or textarea value
  setters plus bubbling `input` and `change` events, followed by the field's
  real blur/validation event, are required. Every write must be read back and
  verified.
- The document response had no `Content-Security-Policy` or
  `Content-Security-Policy-Report-Only` response header, and no CSP meta tag.
  Host-side script evaluation used by pywebview is therefore not blocked by an
  observed page CSP.

### Four writable fields

| WorkTrace value | Observed FD Work control contract |
| --- | --- |
| Project name / exact matter number | `form#basic input#basic_caseId[role="combobox"][type="search"]` |
| Report date | the `form#basic` form item whose visible label is `日期`, containing `input[placeholder="请选择日期"]` |
| One-decimal duration | `form#basic input#basic_hoursWorked[role="spinbutton"]` |
| Saved user description | `form#basic textarea#basic_narrative` |

The duration control advertises `step="0.1"`, `aria-valuemin="0"` and the
actual observed maximum `aria-valuemax="23.9"`.

### Native matter picker and exact fill

- The matter input owns a popup through `aria-controls`.
- The popup has `role="listbox"`.
- Selectable results are plain descendants with `role="option"` and
  `aria-selected`.
- A synthetic non-match settled to the stable empty text `暂无数据`.
- Project creation does not query or render these options in WorkTrace. The
  explicit picker leaves the native input and popup under user control. Its
  confirmation button stays disabled until a committed Ant Select selection
  item is present; search-input text alone is not a selection.
- Timeline filling uses the complete visible option text after only edge
  trimming and Unicode-space normalization. It requires exactly one exact
  result, clicks that option once, then reads the committed selection item back.
- No stable, non-sensitive option key was confirmed. Project selection therefore
  uses the complete normalized visible label only. A result that cannot be
  proven as a committed native option fails closed; no inferred mapping is stored.
- Browser control could observe the result DOM but timed out while attempting a
  non-destructive real-option selection. Therefore the customer auto-link after
  a real matter selection remains a mandatory Windows acceptance item and is
  not claimed as browser-verified here.

### Native actions and ignored fields

- Native form actions are `提交`, `保存`, and `关闭`.
- WorkTrace must never click `提交` or `保存`.
- Observed field contracts:
  - `计时人员`: required, already selected by default, and its search input is
    disabled;
  - `客户`: required and initially empty before matter selection;
  - `暂代昵称`: optional and initially empty;
  - `书写语言`: optional in the observed form and initially empty.
- Compact mode may be installed only after the four WorkTrace fields verify and
  every ignored required field is satisfied by an existing default or FD Work's
  own matter-selection linkage. If `客户` or another ignored required field is
  still empty, the full page must stay visible and WorkTrace must not fill it.

## Session and window observations

- The 2026-08-01 recheck confirmed that the exact business URL remains valid and
  that an unauthenticated visit redirects on the same host to a login route with
  the business route as `returnUrl`.
- An already-authenticated browser tab was present at the exact business URL,
  but read-only dynamic DOM inspection timed out before the option-key and empty
  result contracts could be re-observed. No fresh claim of a stable option key
  is made; the 2026-07-31 non-sensitive selector/listbox/empty-state observation
  remains the implementation baseline and native picker behavior remains a
  Windows acceptance item.
- The shipping controller owns one hidden, unfocused window with a narrow
  `FDWorkHelperBridge`. The bridge exposes only picker confirm/cancel and has no
  application-service or binding access. Authorized startup uses a bounded passive
  session probe. Explicit auth, picker and fill operations may show, restore and
  focus the helper; passive probes and Project Rules field events may not.
- URL is only the first page-state hint. DOM probes distinguish credential login,
  login confirmation and work shell states. `/LoginToken` does
  not require account or password inputs. A loaded/navigation signal is primary;
  a short, deadline-bound fallback handles a missing signal. There is no 35-cycle
  one-second readiness loop and no automatic reload loop.
- A recognized work shell installs adapter contract v5 once for that navigation
  generation. The adapter source is cached by the Python adapter instance; picker
  and fill send only small action scripts. Navigation, disable, close and shutdown
  invalidate stale probes and operation callbacks. Durable bindings created under
  v4 remain valid because binding identity does not include adapter version.
- Windows shipping startup forces the `edgechromium` renderer and verifies the
  initialized renderer. A different renderer is reported as
  `renderer_unavailable` and FD Work fails closed.
- pywebview uses a persistent WorkTrace-only profile at
  `%LOCALAPPDATA%/WorkTrace/webview-profile` with `private_mode=False`, so the
  FD Work session can survive a WorkTrace restart. WorkTrace never reads cookies
  from that profile and the profile is outside database backup, encryption,
  synchronization and export ownership.
- The authenticated Work Hour List remained usable in the original browser tab
  while an isolated tab independently reached the login page. The shipping
  controller must nevertheless rely on one reused pywebview window and verify
  same-process hide/show session retention during Windows acceptance.
- A user close destroys the auxiliary window without calling window APIs from the
  closing callback. A later operation recreates one window. Disabling FD Work
  destroys it but permits a later re-enable; process shutdown permanently
  terminates the capability.
- Session state and interaction ownership are distinct. The only owners are
  `none`, `user_auth`, `user_picker`, `automation_fill` and `user_review`; picker
  and fill cannot overlap. Picker mode removes fill compact mode, keeps only the
  native matter form item plus a WorkTrace confirm/cancel toolbar, and never types,
  focuses, clicks, blurs, sends Escape, opens or closes the popup. Confirm and cancel
  hide the helper and restore WorkTrace only while their nonce/generations remain
  current.
- Adapter v5 `awaitStableWorkShell` is observational: it requires a visible
  document, non-zero viewport, interactive matter input, no blocking overlay and
  stable geometry across two animation frames under one operation deadline. It has
  no input or popup side effects. Timeline fill then prepares the matter combobox
  once, performs unique exact selection, fills and verifies the remaining fields,
  removes its blocking layer on every outcome, and leaves success visible in
  `user_review`. It never submits or saves real time.
- Durable project-binding validity depends on project identity, creation time and
  normalized-name hash, not the adapter contract version. Adapter upgrades do not
  require users to rebind unchanged projects.
- Picker selection proofs are random, one-use process-memory tokens with a
  five-minute TTL and a 128-entry cap. They bind the complete label, picker request,
  operation nonce and navigation generation and never enter the database, browser
  storage, backup, export, or logs.
- No real test time entry was saved or submitted during discovery.
- The isolated login-page observation did not enter credentials, read input
  values, click the native login action, or inspect cookies or tokens.

## Items reserved for Windows acceptance

- Successful manual login and the final live return URL inside the shipping
  auxiliary pywebview window.
- Whether any environment-specific CAPTCHA, MFA, or policy page appears after
  credential submission.
- Real matter selection, exact selected-text readback, and customer linkage.
- Ignored-field native validation after matter selection.
- Source and installed EXE hide/show session retention, compact-mode visual
  fidelity, native validation presentation, and full process shutdown.
- Opening a new-project Drawer ten times without helper appearance; focus retention
  while editing; exactly-once picker foreground; three user-controlled native search
  queries; confirm/cancel/window-close/login-close recovery; twenty helper
  close/recreate cycles; and privacy-before-login behavior remain mandatory source
  and installed-build Windows acceptance until recorded against the exact build SHA.
