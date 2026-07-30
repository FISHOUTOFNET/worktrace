# FD Work integration discovery

This document records the non-sensitive browser contract observed on
2026-07-31 before implementation. It intentionally contains no credentials,
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

### Matter search

- The matter input owns a popup through `aria-controls`.
- The popup has `role="listbox"`.
- Selectable results are plain descendants with `role="option"` and
  `aria-selected`.
- A synthetic non-match settled to the stable empty text `暂无数据`.
- Result matching must use the complete visible option text after only edge
  trimming and normalization of Unicode space variants. The integration must
  require exactly one exact result, click that exact option through the DOM,
  then read the selected display text and compare it again.
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

- The authenticated Work Hour List remained usable in the original browser tab
  while an isolated tab independently reached the login page. The shipping
  controller must nevertheless rely on one reused pywebview window and verify
  same-process hide/show session retention during Windows acceptance.
- Closing the auxiliary window must hide it; only WorkTrace application exit
  may destroy it.
- No real test time entry was saved or submitted during discovery.

## Items reserved for Windows acceptance

- Successful manual login and the final live return URL inside the shipping
  auxiliary pywebview window.
- Whether any environment-specific CAPTCHA, MFA, or policy page appears after
  credential submission.
- Real matter selection, exact selected-text readback, and customer linkage.
- Ignored-field native validation after matter selection.
- Source and installed EXE hide/show session retention, compact-mode visual
  fidelity, native validation presentation, and full process shutdown.
