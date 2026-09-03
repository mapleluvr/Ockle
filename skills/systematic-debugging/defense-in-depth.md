# Defense-in-Depth Validation

## Scope

This applies to bugs caused by invalid data reaching a dangerous operation —
not to every bug. One layer that provably covers all entry paths is enough;
add a further layer only when a distinct bypass exists (a second entry path,
a mock or refactor that skips the first check, a platform-specific edge).
Stop when every known entry path is covered and state why the next layer
was omitted.

## Overview

When you fix a bug caused by invalid data, adding validation at one place feels sufficient. But that single check can be bypassed by different code paths, refactoring, or mocks.

**Core principle:** Validate at each layer the data actually passes through. Stop when one layer provably covers all entry paths; each extra layer must name the bypass it blocks. This makes this recurrence much less likely.

## Why Multiple Layers

Single validation: "We fixed the bug"
Multiple layers: "In this session, the recurrence was blocked on every path we could reach"

Different layers catch different cases:
- Entry validation catches most bugs
- Business logic catches edge cases
- Environment guards prevent context-specific dangers
- Debug logging records context for forensics (observability, not a preventive layer)

## The Four Layers

### Layer 1: Entry Point Validation
**Purpose:** Reject obviously invalid input at API boundary

```typescript
function createProject(name: string, workingDirectory: string) {
  if (!workingDirectory || workingDirectory.trim() === '') {
    throw new Error('workingDirectory cannot be empty');
  }
  if (!existsSync(workingDirectory)) {
    throw new Error(`workingDirectory does not exist: ${workingDirectory}`);
  }
  if (!statSync(workingDirectory).isDirectory()) {
    throw new Error(`workingDirectory is not a directory: ${workingDirectory}`);
  }
  // ... proceed
}
```

### Layer 2: Business Logic Validation
**Purpose:** Ensure data makes sense for this operation

```typescript
function initializeWorkspace(projectDir: string, sessionId: string) {
  if (!projectDir) {
    throw new Error('projectDir required for workspace initialization');
  }
  // ... proceed
}
```

### Layer 3: Environment Guards
**Purpose:** Prevent dangerous operations in specific contexts

Restricted exception to the production-purity rule (see
`test-driven-development/writing-good-tests.md`: production classes carry
production methods only — that rule bans new test-only *methods*; this is a
branch inside an already-dangerous operation). Keep the branch in production
only when all four hold: (a) the operation is destructive or hard to reverse;
(b) test misuse happened before or has a foreseeable path; (c) the guard is a
no-op for safe production inputs; (d) a bypass test names the misuse it
blocks. Otherwise move the check to test utilities or the caller.

```typescript
async function gitInit(directory: string) {
  // In tests, refuse git init outside temp directories
  if (process.env.NODE_ENV === 'test') {
    const normalized = normalize(resolve(directory));
    const tmpDir = normalize(resolve(tmpdir()));

    if (!normalized.startsWith(tmpDir)) {
      throw new Error(
        `Refusing git init outside temp dir during tests: ${directory}`
      );
    }
  }
  // ... proceed
}
```

### Layer 4: Debug Instrumentation (observability, not prevention)
**Purpose:** Capture context for forensics

```typescript
async function gitInit(directory: string) {
  const stack = new Error().stack;
  logger.debug('About to git init', {
    directory,
    cwd: process.cwd(),
    stack,
  });
  // ... proceed
}
```

## Applying the Pattern

When you find a bug:

1. **Trace the data flow** - Where does bad value originate? Where used?
2. **Map all checkpoints** - List every point data passes through
3. **Add validation where a bypass exists** - Entry, business, environment first; logging is forensics, not a layer. Single layer covering all paths: stop and record why.
4. **Test each layer you added** - Only where ≥2 entry paths exist, a mock can bypass, or platforms differ: try to bypass layer 1, verify layer 2 catches it. Otherwise the layer's own test suffices.

## Example from Session

Bug: Empty `projectDir` caused `git init` in source code

**Data flow:**
1. Test setup → empty string
2. `Project.create(name, '')`
3. `WorkspaceManager.createWorkspace('')`
4. `git init` runs in `process.cwd()`

**Four layers added:**
- Layer 1: `Project.create()` validates not empty/exists/writable
- Layer 2: `WorkspaceManager` validates projectDir not empty
- Layer 3: `RepositoryManager` refuses git init outside tmpdir in tests
- Layer 4: Stack trace logging before git init

**Result:** All 1847 tests passed; in this session (2025-10-03) the bug was not reproduced in the re-run

## Key Insight

In this session, each layer caught a distinct bypass we observed:
- Different code paths bypassed entry validation
- Mocks bypassed business logic checks
- Edge cases on different platforms needed environment guards
- Debug logging identified structural misuse

**Stop when one layer provably covers all entry paths.** Add a check at the next layer only for a bypass this layer cannot see.
