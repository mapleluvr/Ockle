import { createInterface } from "node:readline";

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
function send(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

send({ type: "extension_ui_request", id: "status-1", method: "setStatus", statusKey: "magic-context", statusText: "idle" });
if (process.argv[2] === "interactive-failure") {
  setTimeout(() => send({ type: "extension_ui_request", id: "confirm-1", method: "confirm", title: "unexpected" }), 20);
}

for await (const line of lines) {
  if (!line) continue;
  const command = JSON.parse(line);
  if (command.type === "get_state") {
    send({ type: "response", id: command.id, command: command.type, success: true, data: { model: { provider: "Mapleluv", id: "deepseek-v4-flash" }, thinkingLevel: "max", autoCompactionEnabled: false } });
  } else if (command.type === "get_commands") {
    send({ type: "response", id: command.id, command: command.type, success: true, data: { commands: [] } });
  } else if (command.type === "prompt") {
    send({ type: "response", id: command.id, command: command.type, success: true });
    send({ type: "agent_start" });
    send({ type: "message_update", assistantMessageEvent: { type: "text_delta", delta: "a\u2028b" } });
    send({ type: "agent_end" });
    send({ type: "agent_settled", messages: [] });
  } else if (command.type === "bash") {
    send({ type: "response", id: command.id, command: command.type, success: true, data: { output: "pressure" } });
  } else {
    send({ type: "response", id: command.id, command: command.type, success: true });
  }
}
