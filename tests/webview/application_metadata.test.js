const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/application_metadata.js"),
    "utf8"
);

function element() {
    return { textContent: "", hidden: false };
}

function harness(metadataResult) {
    const elements = {
        "application-version-label": element(),
        "settings-application-version": element(),
        "settings-application-creator": element(),
    };
    let calls = 0;
    const app = {
        bridge: {
            getApplicationMetadata() {
                calls += 1;
                return Promise.resolve(metadataResult);
            },
        },
    };
    const context = {
        window: { WorkTraceApp: app },
        document: {
            getElementById(id) {
                return elements[id] || null;
            },
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context, { filename: "application_metadata.js" });
    return {
        app: context.window.WorkTraceApp,
        elements,
        calls: () => calls,
    };
}

test("immutable application metadata loads once and renders all static targets", async () => {
    const view = harness({
        ok: true,
        application: {
            version: "0.0.1",
            release_channel: "beta",
            creator: "Sun Yi",
        },
    });

    const first = view.app.applicationMetadata.load();
    const second = view.app.applicationMetadata.load();
    assert.equal(await first, true);
    assert.equal(await second, true);
    assert.equal(view.calls(), 1);
    assert.equal(view.elements["application-version-label"].textContent, "v0.0.1 · 测试版");
    assert.equal(view.elements["settings-application-version"].textContent, "v0.0.1 · 测试版");
    assert.equal(view.elements["settings-application-creator"].textContent, "Created By Sun Yi");
    assert.equal(view.elements["settings-application-creator"].hidden, false);

    assert.equal(await view.app.applicationMetadata.load(), true);
    assert.equal(view.calls(), 1);
});

test("stable metadata omits release label and hides an absent creator", () => {
    const view = harness({ ok: false });
    const rendered = view.app.applicationMetadata.render({
        version: "1.2.3",
        release_channel: "stable",
        creator: "",
    });

    assert.equal(rendered, true);
    assert.equal(view.elements["application-version-label"].textContent, "v1.2.3");
    assert.equal(view.elements["settings-application-version"].textContent, "v1.2.3");
    assert.equal(view.elements["settings-application-creator"].textContent, "");
    assert.equal(view.elements["settings-application-creator"].hidden, true);
});
