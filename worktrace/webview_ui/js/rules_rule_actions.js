// WorkTrace WebView frontend - created-rule backfill helper.
// Sole owner of App.backfillCreatedRule: applies one newly created
// folder / keyword rule to eligible history via the bridge. The unified
// create panel calls this helper when "应用到历史记录" is checked.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function backfillCreatedRule(ruleType, ruleId) {
        if (ruleType !== "folder" && ruleType !== "keyword") {
            return Promise.resolve(false);
        }
        if (!(parseInt(ruleId, 10) > 0)) {
            return Promise.resolve(false);
        }
        App.rulesBackfillingRuleKey = ruleType + ":" + parseInt(ruleId, 10);
        return App.callBridge("backfill_project_rule", ruleType, parseInt(ruleId, 10)).then(function (result) {
            return !(result && result.ok === false);
        }).catch(function () {
            return false;
        }).then(function (ok) {
            App.rulesBackfillingRuleKey = null;
            return ok;
        });
    }
    App.backfillCreatedRule = backfillCreatedRule;

})();
