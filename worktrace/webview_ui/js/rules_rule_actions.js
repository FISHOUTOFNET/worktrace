// Applies a newly created folder or keyword rule to eligible history.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function backfillCreatedRule(ruleType, ruleId) {
        if (ruleType !== "folder" && ruleType !== "keyword") return Promise.resolve(false);
        var parsedId = parseInt(ruleId, 10);
        if (!(parsedId > 0)) return Promise.resolve(false);
        App.rulesBackfillingRuleKey = ruleType + ":" + parsedId;
        return App.bridge.backfillProjectRule(ruleType, parsedId).then(function (result) {
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
