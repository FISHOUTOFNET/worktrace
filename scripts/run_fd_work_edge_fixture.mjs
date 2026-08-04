import { existsSync, mkdtempSync, rmSync } from "node:fs";
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

function decodeHtmlText(value) {
  return value
    .replace(/&quot;/g, "\"")
    .replace(/&#39;|&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
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

function terminateOwnedEdge(profile) {
  if (terminatedProfiles.has(profile)) return;
  terminatedProfiles.add(profile);
  const command = [
    "$owned = Get-CimInstance Win32_Process -Filter \"Name = 'msedge.exe'\"",
    "| Where-Object { $_.CommandLine -like ('*' + $env:WORKTRACE_EDGE_PROFILE + '*') }",
    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
  ].join(" ");
  spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf8",
    windowsHide: true,
    env: { ...process.env, WORKTRACE_EDGE_PROFILE: profile },
  });
}

function runEdge(edge, args, profile) {
  return new Promise((resolveExecution) => {
    const child = spawn(edge, args, { windowsHide: true });
    let stdout = "";
    let stderr = "";
    let settled = false;
    let timedOut = false;
    let resultCaptured = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolveExecution(result);
    };
    const timeout = setTimeout(() => {
      timedOut = true;
      terminateProcessTree(child.pid);
      terminateOwnedEdge(profile);
      setTimeout(() => finish({ status: null, stdout, stderr, timedOut }), 1000);
    }, 30000);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      if (stdout.length > 8 * 1024 * 1024) {
        terminateProcessTree(child.pid);
        finish({ status: null, stdout: "", stderr, outputExceeded: true });
      } else if (
        !resultCaptured
        && stdout.includes('id="worktrace-result"')
        && stdout.includes("</pre>")
      ) {
        resultCaptured = true;
        terminateProcessTree(child.pid);
        terminateOwnedEdge(profile);
        setTimeout(() => finish({ status: 0, stdout, stderr }), 250);
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      if (stderr.length > 1024 * 1024) stderr = stderr.slice(-1024 * 1024);
    });
    child.on("error", (error) => finish({ error, stdout, stderr }));
    child.on("close", (status) => finish({
      status: resultCaptured ? 0 : status,
      stdout,
      stderr,
      timedOut,
    }));
  });
}

if (!existsSync(fixturePath)) {
  fail("fixture_missing");
} else {
  const edge = edgeExecutable();
  if (!edge) {
    fail("edge_unavailable", "Microsoft Edge executable was not found");
  } else {
    const profile = mkdtempSync(join(tmpdir(), "worktrace-fdwork-edge-"));
    try {
      const execution = await runEdge(edge, [
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-mode",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        `--user-data-dir=${profile}`,
        "--virtual-time-budget=10000",
        "--dump-dom",
        pathToFileURL(fixturePath).href,
      ], profile);
      if (execution.timedOut) {
        fail(
          "edge_timeout",
          `stdout_${execution.stdout.length}_result_${execution.stdout.includes("worktrace-result")}`
        );
      } else if (execution.outputExceeded) {
        fail("edge_output_limit");
      } else if (execution.error) {
        fail(
          "edge_launch_failed",
          String(execution.error.code || "")
        );
      } else if (execution.status !== 0) {
        fail("edge_fixture_failed", `exit_${execution.status}`);
      } else {
        const documentText = String(execution.stdout || "");
        const match = documentText.match(
          /<pre id="worktrace-result">([\s\S]*?)<\/pre>/i
        );
        if (!match) {
          fail("fixture_result_missing");
        } else {
          try {
            const result = JSON.parse(decodeHtmlText(match[1]));
            process.stdout.write(`${JSON.stringify(result)}\n`);
            if (result.ok !== true) process.exitCode = 1;
          } catch (_error) {
            fail("fixture_result_invalid");
          }
        }
      }
    } finally {
      terminateOwnedEdge(profile);
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
          if (!process.exitCode) fail("edge_cleanup_failed");
        }
      }
    }
  }
}
