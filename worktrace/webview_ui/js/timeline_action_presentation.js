// Timeline action presentation: stable operation columns and neutral unavailable deletes.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function syncSessionDeleteAffordance() {
        var button = document.getElementById("timeline-hide-session");
        if (!button) return;
        var available = button.disabled !== true;
        if (!available && button.hidden) button.hidden = false;
        button.setAttribute("aria-label", available ? "删除时间段" : "时间段不可删除");
        button.setAttribute("data-tooltip", available ? "删除时间段" : "不可删除");
    }

    function syncAdvancedActionLayout() {
        var actions = document.querySelector(".editor-actions");
        var advanced = document.getElementById("timeline-advanced-toggle");
        if (!actions || !advanced) return;
        actions.classList.toggle("advanced-actions-unavailable", advanced.hidden === true);
    }

    function syncEditorActionPresentation() {
        syncSessionDeleteAffordance();
        syncAdvancedActionLayout();
    }

    function makeDisabledActivityDelete(row) {
        if (!row || row.querySelector(".summary-hide-activity")) return;
        var button = document.createElement("button");
        button.type = "button";
        button.className = "summary-hide-activity compact-icon-button danger-icon-button";
        button.disabled = true;
        button.setAttribute("aria-label", "活动不可删除");
        button.setAttribute("data-tooltip", "不可删除");
        button.setAttribute("data-activity-delete-placeholder", "1");
        button.innerHTML = App.iconMarkup("trash");
        row.appendChild(button);
    }

    function syncActivityDeleteAffordances() {
        var list = document.getElementById("timeline-details-list");
        if (!list || typeof list.querySelectorAll !== "function") return;
        var rows = list.querySelectorAll(".summary-item");
        for (var i = 0; i < rows.length; i++) makeDisabledActivityDelete(rows[i]);
    }

    function initTimelineActionPresentation() {
        var actions = document.querySelector(".editor-actions");
        var details = document.getElementById("timeline-details-list");

        syncEditorActionPresentation();
        syncActivityDeleteAffordances();

        if (typeof MutationObserver !== "function") return;

        if (actions) {
            new MutationObserver(syncEditorActionPresentation).observe(actions, {
                subtree: true,
                attributes: true,
                attributeFilter: ["hidden", "disabled"]
            });
        }
        if (details) {
            new MutationObserver(syncActivityDeleteAffordances).observe(details, {
                childList: true
            });
        }
    }

    App.syncTimelineActionPresentation = syncEditorActionPresentation;
    App.syncActivityDeleteAffordances = syncActivityDeleteAffordances;

    initTimelineActionPresentation();
})();
