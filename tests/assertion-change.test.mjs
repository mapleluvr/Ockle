import assert from "node:assert/strict";
import test from "node:test";

import { checkAssertionChanges } from "../guard/src/assertion-change.mjs";

function check(base, candidate, file = "test/value.test.js") {
  return checkAssertionChanges({
    baseFiles: new Map([[file, base]]),
    candidateFiles: new Map([[file, candidate]]),
  });
}

const importAssert = `import assert from "node:assert/strict";`;

test("adding an assertion is clear with complete coverage", () => {
  const result = check(
    `${importAssert}\nassert.equal(value(), 1);`,
    `${importAssert}\nassert.equal(value(), 1);\nassert.equal(otherValue(), 2);`,
  );

  assert.equal(result.verdict, "clear");
  assert.equal(result.coverage, "complete");
  assert.deepEqual(result.findings, []);
  assert.deepEqual(result.errors, []);
});

test("deleting or rewriting an existing assertion blocks", () => {
  const deleted = check(
    `${importAssert}\nassert.strictEqual(value(), 1);`,
    `${importAssert}`,
  );
  const rewrittenExpected = check(
    `${importAssert}\nassert.strictEqual(value(), 1);`,
    `${importAssert}\nassert.strictEqual(value(), 2);`,
  );
  const rewrittenActual = check(
    `${importAssert}\nassert.strictEqual(value(), 1);`,
    `${importAssert}\nassert.strictEqual(otherValue(), 1);`,
  );

  for (const result of [deleted, rewrittenExpected, rewrittenActual]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.coverage, "complete");
    assert.equal(result.findings.length, 1);
    assert.equal(result.findings[0].kind, "removed-or-rewritten");
    assert.match(result.findings[0].id, /^[a-f0-9]{20}$/);
  }
});

test("formatting, movement, and diagnostic-message edits stay clear", () => {
  const result = check(
    `${importAssert}
     assert.strictEqual(value(), 1, "old diagnostic");
     assert.ok(ready(), "old readiness message");`,
    `${importAssert}
     // The same behavioral checks moved and reformatted.
     assert.ok(
       ready(),
       "new readiness message",
     );
     assert.strictEqual(value(), 1, "new diagnostic");`,
  );

  assert.equal(result.verdict, "clear");
  assert.equal(result.coverage, "complete");
});

test("assertions are a multiset, so removing one duplicate blocks", () => {
  const result = check(
    `${importAssert}\nassert.equal(value(), 1);\nassert.equal(value(), 1);`,
    `${importAssert}\nassert.equal(value(), 1);`,
  );

  assert.equal(result.verdict, "blocked");
  assert.equal(result.findings.length, 1);
});

test("duplicate findings have stable unique IDs", () => {
  const result = check(
    `${importAssert}\nassert.equal(value(), 1);\nassert.equal(value(), 1);`,
    `${importAssert}`,
  );

  assert.equal(result.findings.length, 2);
  assert.equal(new Set(result.findings.map((finding) => finding.id)).size, 2);
});

test("destructured ESM and CommonJS node assertions are protected", () => {
  const esm = check(
    `import { strictEqual as same } from "node:assert";\nsame(value(), 1);`,
    `import { strictEqual as same } from "node:assert";\nsame(value(), 2);`,
  );
  const bareStrict = check(
    `import assert from "assert/strict";\nassert.equal(value(), 1);`,
    `import assert from "assert/strict";\nassert.equal(value(), 2);`,
  );
  const commonjs = check(
    `const assert = require("node:assert/strict");\nassert.deepEqual(value(), { ok: true });`,
    `const assert = require("node:assert/strict");\nassert.deepEqual(value(), { ok: false });`,
    "test/value.test.cjs",
  );
  const commonjsDestructured = check(
    `const { rejects } = require("node:assert/strict");\nawait rejects(run, /denied/);`,
    `const { rejects } = require("node:assert/strict");\nawait rejects(run, /allowed/);`,
    "test/value.test.cjs",
  );

  for (const result of [esm, bareStrict, commonjs, commonjsDestructured]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.length, 1);
  }
});

test("Jest, Vitest, and Chai expect chains are protected", () => {
  const jest = check(
    `test("value", () => expect(value()).not.toBe(2));`,
    `test("value", () => expect(value()).not.toBe(3));`,
  );
  const vitest = check(
    `import { expect } from "vitest";\nexpect(load()).resolves.toEqual({ ok: true });`,
    `import { expect } from "vitest";\nexpect(load()).resolves.toEqual({ ok: false });`,
    "test/value.test.ts",
  );
  const chai = check(
    `import { expect } from "chai";\nexpect(value()).to.equal(1);`,
    `import { expect } from "chai";\nexpect(value()).to.equal(2);`,
  );

  for (const result of [jest, vitest, chai]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.length, 1);
  }
});

test("nested strict, TypeScript import-equals, and Chai property assertions are protected", () => {
  const nestedStrict = check(
    `import assert from "node:assert";\nassert.strict.equal(value(), 1);`,
    `import assert from "node:assert";`,
  );
  const importEquals = check(
    `import assert = require("node:assert/strict");\nassert.equal(value(), 1);`,
    `import assert = require("node:assert/strict");`,
    "test/value.test.ts",
  );
  const chaiProperty = check(
    `import { expect } from "chai";\nexpect(value()).to.be.true;`,
    `import { expect } from "chai";`,
  );
  const chaiCommonJsProperty = check(
    `const expect = require("chai").expect;\nexpect(value()).to.be.false;`,
    `const expect = require("chai").expect;`,
    "test/value.test.cjs",
  );

  for (const result of [nestedStrict, importEquals, chaiProperty, chaiCommonJsProperty]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.length, 1);
  }
});

test("Node throw-family diagnostic messages do not define assertion behavior", () => {
  const messageOnly = check(
    `${importAssert}\nassert.throws(run, "old message");\nassert.doesNotThrow(load, "old message");\nassert.rejects(fetchValue, /denied/, "old message");`,
    `${importAssert}\nassert.throws(run, "new message");\nassert.doesNotThrow(load, "new message");\nassert.rejects(fetchValue, /denied/, "new message");`,
  );
  const behaviorChange = check(
    `${importAssert}\nassert.rejects(fetchValue, /denied/, "message");`,
    `${importAssert}\nassert.rejects(fetchValue, /allowed/, "message");`,
  );

  assert.equal(messageOnly.verdict, "clear");
  assert.equal(behaviorChange.verdict, "blocked");
});

test("local bindings named assert or expect are not treated as framework assertions", () => {
  const base = `
    import assert from "node:assert/strict";
    assert.equal(value(), 1);
    function callUserCode(assert, expect) {
      assert(userValue());
      expect(userValue()).toBe(1);
    }
  `;
  const candidate = `
    import assert from "node:assert/strict";
    assert.equal(value(), 1);
    function callUserCode(assert, expect) {
      assert(otherUserValue());
      expect(otherUserValue()).toBe(2);
    }
  `;
  const result = check(base, candidate);

  assert.equal(result.verdict, "clear");
  assert.equal(result.findings.length, 0);
});

test("moving an assertion across files or renaming its import alias stays clear", () => {
  const result = checkAssertionChanges({
    baseFiles: new Map([["test/old.test.js", `
      import assert from "node:assert/strict";
      assert.equal(value(), 1);
    `]]),
    candidateFiles: new Map([["test/new.test.js", `
      import verify from "node:assert/strict";
      verify.equal(value(), 1);
    `]]),
  });

  assert.equal(result.verdict, "clear");
  assert.equal(result.findings.length, 0);
});

test("type-only assertion edits stay clear and static computed methods stay protected", () => {
  const typeOnly = check(
    `${importAssert}\nassert.equal((value as OldType).count, 1);`,
    `${importAssert}\nassert.equal((value as NewType).count, 1);`,
    "test/value.test.ts",
  );
  const computed = check(
    `${importAssert}\nassert["equal"](value(), 1);`,
    `${importAssert}\nassert["equal"](value(), 2);`,
  );

  assert.equal(typeOnly.verdict, "clear");
  assert.equal(computed.verdict, "blocked");
});

test("TypeScript syntax is parsed without changing assertion identity", () => {
  const source = `
    import assert from "node:assert/strict";
    const value = result as { count: number };
    assert.equal(value.count, 1);
  `;
  const result = check(source, source, "test/value.test.ts");

  assert.equal(result.verdict, "clear");
  assert.equal(result.coverage, "complete");
});

test("Chai namespace expect and assert forms are protected", () => {
  const esmExpect = check(
    `import chai from "chai";\nchai.expect(value()).to.equal(1);`,
    `import chai from "chai";\nchai.expect(value()).to.equal(2);`,
  );
  const commonJsExpect = check(
    `const chai = require("chai");\nchai.expect(value()).to.be.true;`,
    `const chai = require("chai");\nchai.expect(value()).to.be.false;`,
    "test/value.test.cjs",
  );
  const esmAssert = check(
    `import { assert } from "chai";\nassert.equal(value(), 1);`,
    `import { assert } from "chai";\nassert.equal(value(), 2);`,
  );
  const namespaceAssert = check(
    `import * as chai from "chai";\nchai.assert.equal(value(), 1);`,
    `import * as chai from "chai";\nchai.assert.equal(value(), 2);`,
  );

  for (const result of [esmExpect, commonJsExpect, esmAssert, namespaceAssert]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.length, 1);
  }
});

test("optional assertion calls are protected", () => {
  const optionalMethod = check(
    `${importAssert}\nassert.equal?.(value(), 1);`,
    `${importAssert}\nassert.equal?.(value(), 2);`,
  );
  const optionalObject = check(
    `${importAssert}\nassert?.equal(value(), 1);`,
    `${importAssert}`,
  );
  const optionalExpect = check(
    `expect(value())?.toBe(1);`,
    `expect(value())?.toBe(2);`,
  );
  const optionalChaiProperty = check(
    `import { expect } from "chai";\nexpect(value())?.to.be.true;`,
    `import { expect } from "chai";`,
  );

  for (const result of [optionalMethod, optionalObject, optionalExpect, optionalChaiProperty]) {
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.length, 1);
  }
});

test("equivalent static syntax does not create assertion-change findings", () => {
  const result = check(
    `${importAssert}\nassert.deepEqual(value().name, { label: "ready" });`,
    `${importAssert}\nassert.deepEqual(value()["name"], { "label": \`ready\` });`,
  );

  assert.equal(result.verdict, "clear");
  assert.equal(result.findings.length, 0);
});

test("JSX in JavaScript test files remains inside parser coverage", () => {
  const result = check(
    `${importAssert}\nconst view = <div>{value()}</div>;\nassert.equal(view.type, "div");`,
    `${importAssert}\nconst view = <div>{value()}</div>;\nassert.equal(view.type, "span");`,
  );

  assert.equal(result.verdict, "blocked");
  assert.equal(result.coverage, "complete");
});

test("a parse failure is indeterminate with partial coverage", () => {
  const result = check(
    `${importAssert}\nassert.equal(value(), 1);`,
    `${importAssert}\nassert.equal(value(, 1);`,
  );

  assert.equal(result.verdict, "indeterminate");
  assert.equal(result.coverage, "partial");
  assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].side, "candidate");
});
