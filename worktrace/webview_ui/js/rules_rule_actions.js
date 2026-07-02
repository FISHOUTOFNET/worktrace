// WorkTrace WebView frontend - retained single-rule history apply helper.

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
