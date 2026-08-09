// WorkTrace Timeline deletion presentation owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.confirmTimelineDeletion = function (operation, options, trigger) {
        if (!App.openDeleteDialog) return App.runTimelineSessionOperation(operation, options);
        var activity = operation === "hideActivity";
        return App.openDeleteDialog({
            trigger: trigger,
            title: activity ? "删除活动" : "删除时间段",
            secondTitle: "确认删除",
            secondIntro: "此操作不可撤销。",
            warning: "此操作不可撤销。",
            confirmLabel: activity ? "删除活动" : "删除时间段",
            twoStep: true
        }).then(function (confirmed) {
            return confirmed ? App.runTimelineSessionOperation(operation, options) : null;
        });
    };
})();
