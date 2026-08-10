import { existsSync, mkdtempSync, readFileSync, rmSync, watch } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "..");
const fixturePath = join(
  repositoryRoot,
  "tests",
  "fixtures",
  "fd_work",
  "anonymous_work_shell.html"
);

function environmentValue(name) {
  const match = Object.keys(process.env).find(
    (key) => key.toLowerCase() === name.toLowerCase()
  );
  return match ? process.env[match] : "";
}

function edgeExecutable() {
  const roots = [
    environmentValue("ProgramFiles(x86)"),
    environmentValue("ProgramFiles"),
    environmentValue("LocalAppData"),
  ].filter(Boolean);
  for (const root of roots) {
    const candidate = join(root, "Microsoft", "Edge", "Application", "msedge.exe");
    if (existsSync(candidate)) return candidate;
  }
  const located = spawnSync("where.exe", ["msedge.exe"], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (located.status === 0) {
    const candidate = String(located.stdout || "").split(/\r?\n/).find(Boolean);
    if (candidate && existsSync(candidate.trim())) return candidate.trim();
  }
  return "";
}

function fail(error, detail = "") {
  process.stdout.write(`${JSON.stringify({ ok: false, error, detail })}\n`);
  process.exitCode = 1;
}

function terminateProcessTree(processId) {
  if (!Number.isInteger(processId) || processId <= 0) return;
  spawnSync("taskkill.exe", ["/PID", String(processId), "/T", "/F"], {
    encoding: "utf8",
    windowsHide: true,
  });
}

const terminatedProfiles = new Set();

function ownedEdgeProcessIds(profile) {
  const command = [
    "$owned = Get-CimInstance Win32_Process -Filter \"Name = 'msedge.exe'\"",
    "| Where-Object { $_.CommandLine -like ('*' + $env:WORKTRACE_EDGE_PROFILE + '*') };",
    "$owned | ForEach-Object { $_.ProcessId }",
  ].join(" ");
  const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf8",
    windowsHide: true,
    env: { ...process.env, WORKTRACE_EDGE_PROFILE: profile },
  });
  return String(result.stdout || "")
    .split(/\r?\n/)
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isInteger(value) && value > 0);
}

function waitForProcessExit(processIds) {
  if (!processIds.length) return;
  const command = [
    `$ids = @(${processIds.join(",")});`,
    "$ids | ForEach-Object { Wait-Process -Id $_ -ErrorAction SilentlyContinue }",
  ].join(" ");
  spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf8",
    windowsHide: true,
  });
}

function terminateOwnedEdge(profile) {
  if (terminatedProfiles.has(profile)) return;
  terminatedProfiles.add(profile);
  const command = [
    "$owned = Get-CimInstance Win32_Process -Filter \"Name = 'msedge.exe'\"",
    "| Where-Object { $_.CommandLine -like ('*' + $env:WORKTRACE_EDGE_PROFILE + '*') }",
    "| ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue };",
    "$stopped = $owned | Stop-Process -Force -PassThru -ErrorAction SilentlyContinue;",
    "$stopped | Wait-Process -ErrorAction SilentlyContinue",
  ].join(" ");
  spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf8",
    windowsHide: true,
    env: { ...process.env, WORKTRACE_EDGE_PROFILE: profile },
  });
}

function withDeadline(promise, milliseconds, errorCode) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(errorCode)), milliseconds);
    }),
  ]).finally(() => clearTimeout(timer));
}

function readDevToolsEndpoint(profile) {
  try {
    const lines = readFileSync(join(profile, "DevToolsActivePort"), "utf8")
      .split(/\r?\n/)
      .filter(Boolean);
    const port = Number(lines[0]);
    if (Number.isInteger(port) && port > 0) return { port };
  } catch (_error) {
    return null;
  }
  return null;
}

function waitForDevToolsEndpoint(profile) {
  const ready = readDevToolsEndpoint(profile);
  if (ready) return Promise.resolve(ready);
  return new Promise((resolveEndpoint, rejectEndpoint) => {
    let watcher;
    const finish = (error, endpoint) => {
      if (watcher) watcher.close();
      if (error) rejectEndpoint(error);
      else resolveEndpoint(endpoint);
    };
    try {
      watcher = watch(profile, () => {
        const endpoint = readDevToolsEndpoint(profile);
        if (endpoint) finish(null, endpoint);
      });
    } catch (error) {
      finish(error);
    }
  });
}

function connectDevTools(webSocketUrl) {
  return new Promise((resolveSocket, rejectSocket) => {
    const socket = new WebSocket(webSocketUrl);
    socket.addEventListener("open", () => resolveSocket(socket), { once: true });
    socket.addEventListener("error", () => {
      rejectSocket(new Error("devtools_socket_failed"));
    }, { once: true });
  });
}

function commandClient(socket) {
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(String(event.data || ""));
    } catch (_error) {
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(`devtools_command_failed_${request.method}`));
    else request.resolve(message.result || {});
  });
  return (method, params = {}) => new Promise((resolveCommand, rejectCommand) => {
    const id = ++nextId;
    pending.set(id, { method, resolve: resolveCommand, reject: rejectCommand });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function readFixtureResult(profile) {
  const endpoint = await waitForDevToolsEndpoint(profile);
  const fixtureUrl = pathToFileURL(fixturePath).href;
  const targetResponse = await fetch(
    `http://127.0.0.1:${endpoint.port}/json/new?${encodeURIComponent(fixtureUrl)}`,
    { method: "PUT" }
  );
  if (!targetResponse.ok) throw new Error("devtools_target_failed");
  const target = await targetResponse.json();
  if (!target.webSocketDebuggerUrl) throw new Error("devtools_target_missing");
  const socket = await connectDevTools(target.webSocketDebuggerUrl);
  try {
    const command = commandClient(socket);
    await command("Runtime.enable");
    await command("Page.bringToFront");
    const evaluation = await command("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `new Promise(function (resolve) {
        function finishFromDocument() {
          var node = document.getElementById("worktrace-result");
          if (!node) return false;
          resolve(node.textContent || "");
          return true;
        }
        if (finishFromDocument()) return;
        var observer = new MutationObserver(function () {
          if (finishFromDocument()) observer.disconnect();
        });
        observer.observe(document.documentElement, { childList: true, subtree: true });
      })`,
    });
    if (evaluation.exceptionDetails) throw new Error("fixture_evaluation_failed");
    const value = evaluation.result && evaluation.result.value;
    if (typeof value !== "string" || !value) {
      throw new Error("fixture_result_missing");
    }
    const result = JSON.parse(value);
    const processIds = ownedEdgeProcessIds(profile);
    await command("Browser.close");
    waitForProcessExit(processIds);
    return result;
  } finally {
    socket.close();
  }
}

if (!existsSync(fixturePath)) {
  fail("fixture_missing");
} else {
  const edge = edgeExecutable();
  if (!edge) {
    fail("edge_unavailable", "Microsoft Edge executable was not found");
  } else {
    const profile = mkdtempSync(join(tmpdir(), "worktrace-fdwork-edge-"));
    let child = null;
    let childExited = false;
    let launchError = null;
    try {
      child = spawn(edge, [
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-mode",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        `--user-data-dir=${profile}`,
        "--remote-debugging-port=0",
        "about:blank",
      ], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
      child.once("error", (error) => { launchError = error; });
      child.once("close", () => { childExited = true; });
      let stderr = "";
      child.stderr.setEncoding("utf8");
      child.stderr.on("data", (chunk) => {
        stderr = (stderr + chunk).slice(-1024 * 1024);
      });
      try {
        const result = await withDeadline(
          readFixtureResult(profile),
          30000,
          "edge_timeout"
        );
        process.stdout.write(`${JSON.stringify(result)}\n`);
        if (result.ok !== true) process.exitCode = 1;
      } catch (error) {
        const code = launchError
          ? "edge_launch_failed"
          : String(error && error.message || "edge_fixture_failed");
        fail(code, launchError ? String(launchError.code || "") : `stderr_${stderr.length}`);
      }
    } finally {
      terminateOwnedEdge(profile);
      if (child && !childExited) terminateProcessTree(child.pid);
      const resolvedProfile = resolve(profile);
      const resolvedTemporaryRoot = resolve(tmpdir());
      if (resolvedProfile.startsWith(`${resolvedTemporaryRoot}\\`)) {
        try {
          rmSync(resolvedProfile, {
            recursive: true,
            force: true,
            maxRetries: 3,
            retryDelay: 100,
          });
        } catch (_error) {
          if (existsSync(resolvedProfile) && !process.exitCode) {
            fail("edge_cleanup_failed", String(_error && _error.code || ""));
          }
        }
      }
    }
  }
}
