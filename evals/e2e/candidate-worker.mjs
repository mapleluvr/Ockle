import { pathToFileURL } from "node:url";

let input = "";
for await (const chunk of process.stdin) input += chunk;

try {
  const request = JSON.parse(input);
  if (request.globals?.structuredClone === "undefined") globalThis.structuredClone = undefined;
  const module = await import(`${pathToFileURL(request.modulePath).href}?ockle-candidate=${Date.now()}`);
  if (!(request.exportName in module)) throw new Error(`candidate export missing: ${request.exportName}`);
  const exported = module[request.exportName];
  const value = request.operation === "get"
    ? exported
    : await exported(...(Array.isArray(request.args) ? request.args : []));
  process.stdout.write(`${JSON.stringify({ ok: true, value: value === undefined ? null : value })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({
    ok: false,
    error: {
      name: error instanceof Error ? error.name : "Error",
      code: error?.code ?? null,
      message: error instanceof Error ? error.message : String(error),
    },
  })}\n`);
}
