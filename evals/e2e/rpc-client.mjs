import { appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { JsonlDecoder } from "./jsonl.mjs";

const FIRE_AND_FORGET_UI = new Set(["notify", "setStatus", "setWidget", "setTitle", "set_editor_text"]);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

export class RpcClient {
  #child;
  #decoder = new JsonlDecoder();
  #pending = new Map();
  #settledCount = 0;
  #settledWaiters = [];
  #nextId = 1;
  #eventsPath;
  #stderrPath;
  #timeoutMs;
  #exit;
  #closed = false;
  #fatalError = null;

  static async start(options) {
    return new RpcClient(options);
  }

  constructor({ executable, args, cwd, env, eventsPath, stderrPath, timeoutMs = 900000 }) {
    for (const [name, value] of Object.entries({ executable, cwd, eventsPath, stderrPath })) {
      if (typeof value !== "string" || value.length === 0) throw new Error(`${name} is required`);
    }
    mkdirSync(path.dirname(eventsPath), { recursive: true });
    mkdirSync(path.dirname(stderrPath), { recursive: true });
    this.#eventsPath = eventsPath;
    this.#stderrPath = stderrPath;
    this.#timeoutMs = timeoutMs;
    this.#child = spawn(executable, args, {
      cwd,
      env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.#exit = deferred();
    this.#child.stdout.on("data", (chunk) => this.#acceptChunk(chunk));
    this.#child.stderr.on("data", (chunk) => appendFileSync(this.#stderrPath, chunk));
    this.#child.on("error", (error) => this.#fail(error));
    this.#child.on("exit", (code, signal) => {
      const outcome = { code, signal };
      if (code === 0) this.#exit.resolve(outcome);
      else this.#exit.reject(new Error(`Pi RPC exited code=${code} signal=${signal ?? "none"}`));
      if (!this.#closed) this.#fail(new Error(`Pi RPC exited before close code=${code} signal=${signal ?? "none"}`));
    });
  }

  get pid() {
    return this.#child.pid;
  }

  async command(type, fields = {}, timeoutMs = this.#timeoutMs) {
    if (this.#fatalError) throw this.#fatalError;
    if (this.#closed) throw new Error("RPC client is closed");
    const id = `ockle-${this.#nextId++}`;
    const pending = deferred();
    const timer = setTimeout(() => {
      this.#pending.delete(id);
      pending.reject(new Error(`RPC command timed out: ${type}`));
    }, timeoutMs);
    this.#pending.set(id, { ...pending, timer, type });
    this.#child.stdin.write(`${JSON.stringify({ id, type, ...fields })}\n`);
    return pending.promise;
  }

  async prompt(message, timeoutMs = this.#timeoutMs) {
    const expectedSettled = this.#settledCount + 1;
    await this.command("prompt", { message }, timeoutMs);
    if (this.#settledCount >= expectedSettled) return;
    const waiter = deferred();
    const timer = setTimeout(() => {
      const index = this.#settledWaiters.findIndex((candidate) => candidate.waiter === waiter);
      if (index >= 0) this.#settledWaiters.splice(index, 1);
      waiter.reject(new Error("RPC prompt timed out waiting for agent_settled"));
    }, timeoutMs);
    this.#settledWaiters.push({ target: expectedSettled, waiter, timer });
    await waiter.promise;
  }

  async close(timeoutMs = this.#timeoutMs) {
    if (this.#closed) return this.#exit.promise;
    this.#closed = true;
    this.#child.stdin.end();
    let timer;
    try {
      return await Promise.race([
        this.#exit.promise,
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("Pi RPC shutdown timed out")), timeoutMs);
        }),
      ]);
    } catch (error) {
      this.#child.kill();
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async abort(timeoutMs = 5000) {
    if (!this.#closed) {
      this.#closed = true;
      this.#child.stdin.end();
      this.#child.kill();
    }
    let timer;
    try {
      return await Promise.race([
        this.#exit.promise.catch((error) => ({ error: error.message })),
        new Promise((resolve) => {
          timer = setTimeout(() => {
            this.#child.kill("SIGKILL");
            resolve({ forced: true });
          }, timeoutMs);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  #acceptChunk(chunk) {
    let values;
    try {
      values = this.#decoder.push(chunk);
    } catch (error) {
      this.#fail(new Error(`invalid RPC JSONL: ${error.message}`));
      return;
    }
    for (const value of values) this.#accept(value);
  }

  #accept(value) {
    appendFileSync(this.#eventsPath, `${JSON.stringify(value)}\n`);
    if (value.type === "response" && value.id) {
      const pending = this.#pending.get(value.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.#pending.delete(value.id);
      if (value.success) pending.resolve(value.data);
      else pending.reject(new Error(value.error ?? `RPC command failed: ${pending.type}`));
      return;
    }
    if (value.type === "agent_settled") {
      this.#settledCount += 1;
      for (const candidate of [...this.#settledWaiters]) {
        if (this.#settledCount < candidate.target) continue;
        clearTimeout(candidate.timer);
        this.#settledWaiters.splice(this.#settledWaiters.indexOf(candidate), 1);
        candidate.waiter.resolve();
      }
      return;
    }
    if (value.type === "extension_ui_request") {
      if (FIRE_AND_FORGET_UI.has(value.method)) return;
      if (value.id) {
        this.#child.stdin.write(`${JSON.stringify({ type: "extension_ui_response", id: value.id, cancelled: true })}\n`);
      }
      this.#fail(new Error(`unexpected interactive extension UI request: ${value.method ?? "unknown"}`));
    }
  }

  #fail(error) {
    if (!this.#fatalError) this.#fatalError = error;
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
    for (const candidate of this.#settledWaiters) {
      clearTimeout(candidate.timer);
      candidate.waiter.reject(error);
    }
    this.#settledWaiters = [];
  }
}
