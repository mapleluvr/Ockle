import { createHash } from "node:crypto";

import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";

const traverse = traverseModule.default ?? traverseModule;
const ASSERT_MODULES = new Set(["assert", "assert/strict", "node:assert", "node:assert/strict"]);
const EXPECT_MODULES = new Set(["@jest/globals", "chai", "vitest"]);
const OMITTED_AST_FIELDS = new Set([
  "end",
  "errors",
  "extra",
  "innerComments",
  "leadingComments",
  "loc",
  "start",
  "trailingComments",
  "typeAnnotation",
  "typeArguments",
  "typeParameters",
]);
const TYPE_ONLY_WRAPPERS = new Set([
  "TSAsExpression",
  "TSInstantiationExpression",
  "TSNonNullExpression",
  "TSSatisfiesExpression",
  "TSTypeAssertion",
  "TypeCastExpression",
]);

function isMemberNode(node) {
  return node?.type === "MemberExpression" || node?.type === "OptionalMemberExpression";
}

function isCallNode(node) {
  return node?.type === "CallExpression" || node?.type === "OptionalCallExpression";
}

function stableNode(node) {
  if (Array.isArray(node)) return node.map(stableNode);
  if (!node || typeof node !== "object") return node;
  if (TYPE_ONLY_WRAPPERS.has(node.type)) return stableNode(node.expression);
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    return { type: "StringLiteral", value: node.quasis[0]?.value.cooked ?? node.quasis[0]?.value.raw ?? "" };
  }
  if (isMemberNode(node)) {
    const property = staticProperty(node);
    if (property !== null) {
      return {
        type: node.type,
        object: stableNode(node.object),
        property: { type: "StaticProperty", value: property },
        optional: Boolean(node.optional),
      };
    }
  }
  if (node.type === "ObjectProperty" && !node.computed) {
    const key = node.key.type === "Identifier"
      ? node.key.name
      : node.key.type === "StringLiteral" || node.key.type === "NumericLiteral"
        ? String(node.key.value)
        : null;
    if (key !== null) {
      return {
        type: "ObjectProperty",
        key: { type: "StaticProperty", value: key },
        value: stableNode(node.value),
        kind: node.kind ?? "init",
        method: Boolean(node.method),
      };
    }
  }
  const result = {};
  for (const key of Object.keys(node).sort()) {
    if (OMITTED_AST_FIELDS.has(key)) continue;
    result[key] = stableNode(node[key]);
  }
  return result;
}

function parserPlugins(file) {
  const plugins = ["decorators-legacy", "importAttributes"];
  if (/\.[cm]?tsx?$/i.test(file)) plugins.push("typescript");
  if (/\.(?:[cm]?js|jsx|tsx)$/i.test(file)) plugins.push("jsx");
  return plugins;
}

function registerBinding(path, name, descriptor, descriptors) {
  const binding = path.scope.getBinding(name);
  if (binding) descriptors.set(binding.identifier, descriptor);
}

function importedName(specifier) {
  return specifier.imported?.name ?? specifier.imported?.value ?? "default";
}

function requireTarget(node) {
  let call = node;
  let member = null;
  if (isMemberNode(node) && !node.computed && node.property.type === "Identifier") {
    call = node.object;
    member = node.property.name;
  }
  if (
    !isCallNode(call)
    || call.callee.type !== "Identifier"
    || call.callee.name !== "require"
    || call.arguments.length !== 1
    || call.arguments[0].type !== "StringLiteral"
  ) return null;
  return { source: call.arguments[0].value, member };
}

function bindingDescriptors(ast) {
  const descriptors = new WeakMap();
  traverse(ast, {
    ImportDeclaration(path) {
      const source = path.node.source.value;
      for (const specifier of path.node.specifiers) {
        if (ASSERT_MODULES.has(source)) {
          const imported = importedName(specifier);
          const descriptor = (
            specifier.type === "ImportDefaultSpecifier"
            || specifier.type === "ImportNamespaceSpecifier"
            || imported === "strict"
          )
            ? { kind: "assert-object" }
            : { kind: "assert-function", method: imported };
          registerBinding(path, specifier.local.name, descriptor, descriptors);
        } else if (EXPECT_MODULES.has(source)) {
          const imported = importedName(specifier);
          if (source === "chai" && (
            specifier.type === "ImportDefaultSpecifier"
            || specifier.type === "ImportNamespaceSpecifier"
          )) {
            registerBinding(path, specifier.local.name, { kind: "chai-namespace" }, descriptors);
          } else if (imported === "expect") {
            registerBinding(path, specifier.local.name, {
              kind: "expect",
              propertyAssertions: source === "chai",
            }, descriptors);
          } else if (source === "chai" && imported === "assert") {
            registerBinding(path, specifier.local.name, {
              kind: "assert-object",
              framework: "chai-assert",
            }, descriptors);
          }
        }
      }
    },
    TSImportEqualsDeclaration(path) {
      const reference = path.node.moduleReference;
      const source = reference.type === "TSExternalModuleReference"
        && reference.expression?.type === "StringLiteral"
        ? reference.expression.value
        : null;
      if (source && ASSERT_MODULES.has(source)) {
        registerBinding(path, path.node.id.name, { kind: "assert-object" }, descriptors);
      }
    },
    VariableDeclarator(path) {
      const target = requireTarget(path.node.init);
      if (!target) return;
      if (ASSERT_MODULES.has(target.source)) {
        if (path.node.id.type === "Identifier") {
          registerBinding(path, path.node.id.name, { kind: "assert-object" }, descriptors);
        } else if (path.node.id.type === "ObjectPattern") {
          for (const property of path.node.id.properties) {
            if (property.type !== "ObjectProperty" || property.computed) continue;
            const imported = property.key.name ?? property.key.value;
            const local = property.value.type === "Identifier" ? property.value.name : null;
            if (!local) continue;
            registerBinding(
              path,
              local,
              imported === "strict"
                ? { kind: "assert-object" }
                : { kind: "assert-function", method: imported },
              descriptors,
            );
          }
        }
      } else if (EXPECT_MODULES.has(target.source)) {
        if (path.node.id.type === "Identifier" && target.source === "chai" && target.member === null) {
          registerBinding(path, path.node.id.name, { kind: "chai-namespace" }, descriptors);
        } else if (path.node.id.type === "Identifier" && target.member === "expect") {
          registerBinding(path, path.node.id.name, {
            kind: "expect",
            propertyAssertions: target.source === "chai",
          }, descriptors);
        } else if (path.node.id.type === "Identifier" && target.source === "chai" && target.member === "assert") {
          registerBinding(path, path.node.id.name, {
            kind: "assert-object",
            framework: "chai-assert",
          }, descriptors);
        } else if (path.node.id.type === "ObjectPattern") {
          for (const property of path.node.id.properties) {
            if (property.type !== "ObjectProperty" || property.computed) continue;
            const imported = property.key.name ?? property.key.value;
            const local = property.value.type === "Identifier" ? property.value.name : null;
            if (imported === "expect" && local) {
              registerBinding(path, local, {
                kind: "expect",
                propertyAssertions: target.source === "chai",
              }, descriptors);
            } else if (target.source === "chai" && imported === "assert" && local) {
              registerBinding(path, local, {
                kind: "assert-object",
                framework: "chai-assert",
              }, descriptors);
            }
          }
        }
      }
    },
  });
  return descriptors;
}

function descriptorAt(path, name, descriptors, { globalExpect = false } = {}) {
  const binding = path.scope.getBinding(name);
  if (!binding) return globalExpect && name === "expect"
    ? { kind: "expect", propertyAssertions: false }
    : null;
  return descriptors.get(binding.identifier) ?? null;
}

function staticProperty(member) {
  if (!member.computed && member.property.type === "Identifier") return member.property.name;
  if (member.computed && member.property.type === "StringLiteral") return member.property.value;
  return null;
}

function memberChain(node) {
  const parts = [];
  let current = node;
  while (isMemberNode(current)) {
    const property = staticProperty(current);
    if (property === null) return null;
    parts.unshift(property);
    current = current.object;
  }
  return { root: current, parts };
}

function expectRootDescriptor(path, call, descriptors) {
  if (!isCallNode(call)) return null;
  if (call.callee.type === "Identifier") {
    const descriptor = descriptorAt(path, call.callee.name, descriptors, { globalExpect: true });
    return descriptor?.kind === "expect" ? descriptor : null;
  }
  if (isMemberNode(call.callee)) {
    const chain = memberChain(call.callee);
    if (chain?.root.type === "Identifier" && chain.parts.join(".") === "expect") {
      const descriptor = descriptorAt(path, chain.root.name, descriptors);
      if (descriptor?.kind === "chai-namespace") {
        return { kind: "expect", propertyAssertions: true };
      }
    }
  }
  return null;
}

function expectChain(path, node, descriptors) {
  const chain = memberChain(node);
  if (!chain || !isCallNode(chain.root) || chain.parts.length === 0) return null;
  const descriptor = expectRootDescriptor(path, chain.root, descriptors);
  if (!descriptor) return null;
  return { ...chain, descriptor };
}

function expectAssertionCall(path, descriptors) {
  const node = path.node;
  if (!isMemberNode(node.callee)) return null;
  const chain = expectChain(path, node.callee, descriptors);
  if (!chain) return null;

  return {
    framework: "expect",
    method: chain.parts.join("."),
    args: [...chain.root.arguments, ...node.arguments],
  };
}

function expectPropertyAssertion(path, descriptors) {
  const parent = path.parentPath?.node;
  if ((isMemberNode(parent) && parent.object === path.node)
    || (isCallNode(parent) && parent.callee === path.node)) return null;
  const chain = expectChain(path, path.node, descriptors);
  if (!chain?.descriptor.propertyAssertions) return null;
  return {
    framework: "expect",
    method: chain.parts.join("."),
    args: [...chain.root.arguments],
  };
}

function assertionCall(path, descriptors) {
  const node = path.node;
  const { callee } = node;
  if (callee.type === "Identifier") {
    const descriptor = descriptorAt(path, callee.name, descriptors);
    if (descriptor?.kind === "assert-function") {
      return { framework: "node-assert", method: descriptor.method, args: node.arguments };
    }
    if (descriptor?.kind === "assert-object") {
      return {
        framework: descriptor.framework ?? "node-assert",
        method: "ok",
        args: node.arguments,
      };
    }
  }
  if (isMemberNode(callee)) {
    const chain = memberChain(callee);
    if (chain?.root.type === "Identifier") {
      const descriptor = descriptorAt(path, chain.root.name, descriptors);
      const method = descriptor?.kind === "chai-namespace"
        && chain.parts.length === 2
        && chain.parts[0] === "assert"
        ? chain.parts[1]
        : chain.parts.length === 1
          ? chain.parts[0]
          : chain.parts.length === 2 && chain.parts[0] === "strict"
            ? chain.parts[1]
            : null;
      if (descriptor?.kind === "assert-object" && method) {
        return {
          framework: descriptor.framework ?? "node-assert",
          method,
          args: node.arguments,
        };
      }
      if (descriptor?.kind === "chai-namespace" && method) {
        return { framework: "chai-assert", method, args: node.arguments };
      }
    }
  }
  return expectAssertionCall(path, descriptors);
}

function behaviorArgs(framework, method, args) {
  if (framework === "expect") return args;
  if (framework === "chai-assert") {
    if (["throws", "doesNotThrow"].includes(method)) return args.slice(0, 3);
    return args.slice(0, 2);
  }
  if (method === "fail") return [];
  if (method === "ok" || method === "ifError") return args.slice(0, 1);
  if (["throws", "doesNotThrow", "rejects", "doesNotReject"].includes(method)) {
    const secondIsMessage = args.length === 2
      && (args[1]?.type === "StringLiteral" || args[1]?.type === "TemplateLiteral");
    return secondIsMessage ? args.slice(0, 1) : args.slice(0, 2);
  }
  return args.slice(0, 2);
}

function extractAssertions(file, source) {
  const ast = parse(source, {
    sourceType: "unambiguous",
    plugins: parserPlugins(file),
  });
  const descriptors = bindingDescriptors(ast);
  const assertions = [];
  const recordAssertion = (path, call) => {
    const normalized = JSON.stringify({
      framework: call.framework,
      method: call.method,
      args: behaviorArgs(call.framework, call.method, call.args).map(stableNode),
    });
    assertions.push({
      file,
      line: path.node.loc?.start.line ?? null,
      column: path.node.loc?.start.column ?? null,
      framework: call.framework,
      method: call.method,
      normalized,
    });
  };

  const visitCall = (path) => {
    const call = assertionCall(path, descriptors);
    if (call) recordAssertion(path, call);
  };
  const visitMember = (path) => {
    const call = expectPropertyAssertion(path, descriptors);
    if (call) recordAssertion(path, call);
  };
  traverse(ast, {
    CallExpression: visitCall,
    OptionalCallExpression: visitCall,
    MemberExpression: visitMember,
    OptionalMemberExpression: visitMember,
  });

  return assertions;
}

function findingId(assertion, occurrence) {
  return createHash("sha256")
    .update(`assertion-change@1\0${assertion.file}\0${assertion.normalized}\0${occurrence}`)
    .digest("hex")
    .slice(0, 20);
}

export function checkAssertionChanges({ baseFiles, candidateFiles }) {
  const errors = [];
  const baseAssertions = [];
  const candidateAssertions = [];

  for (const [file, source] of baseFiles) {
    try {
      baseAssertions.push(...extractAssertions(file, source));
    } catch (error) {
      errors.push({ file, side: "base", message: error.message });
    }
  }
  for (const [file, source] of candidateFiles) {
    try {
      candidateAssertions.push(...extractAssertions(file, source));
    } catch (error) {
      errors.push({ file, side: "candidate", message: error.message });
    }
  }

  const remaining = new Map();
  for (const assertion of candidateAssertions) {
    remaining.set(assertion.normalized, (remaining.get(assertion.normalized) ?? 0) + 1);
  }

  const findings = [];
  const occurrences = new Map();
  for (const assertion of baseAssertions) {
    const occurrenceKey = `${assertion.file}\0${assertion.normalized}`;
    const occurrence = (occurrences.get(occurrenceKey) ?? 0) + 1;
    occurrences.set(occurrenceKey, occurrence);
    const count = remaining.get(assertion.normalized) ?? 0;
    if (count > 0) {
      remaining.set(assertion.normalized, count - 1);
      continue;
    }
    findings.push({
      id: findingId(assertion, occurrence),
      rule: "assertion-change",
      kind: "removed-or-rewritten",
      file: assertion.file,
      line: assertion.line,
      column: assertion.column,
      occurrence,
      framework: assertion.framework,
      method: assertion.method,
    });
  }

  return {
    verdict: errors.length > 0 ? "indeterminate" : findings.length > 0 ? "blocked" : "clear",
    coverage: errors.length > 0 ? "partial" : "complete",
    findings,
    errors,
  };
}
