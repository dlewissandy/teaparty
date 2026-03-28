# Self-Review

This is adversarial review. Your goal is to find what's wrong, not to confirm you're done. Agents consistently ship incomplete work when asked to "check" — so instead, assume you cut corners and hunt for where.

## Step 1: Re-read the issue

`gh issue view $0` — read it fresh, as if for the first time. Note anything you missed or misunderstood.

## Step 2: Re-read design docs

Re-read every design doc cited in Phase 1. Does your code faithfully implement what they specify?

## Step 3: Find three problems

Review `git diff origin/develop...HEAD` and find at least three problems. They exist — look harder. Common hiding spots:

- **Dead code:** Functions/classes you wrote that nothing calls. Grep for each one.
- **Partial implementation:** You implemented the easy path but skipped the hard one. Check every branch and error case the spec describes.
- **Shoddy tests:** Tests that assert on trivial properties, mock away the behavior under test, or would pass on a broken implementation. For each test, ask: "If I deleted the fix, would this test catch it?"
- **Missing integration:** You wrote a component but didn't wire it into its callers. The feature doesn't actually activate at runtime.
- **Scope drift:** Changes that don't trace to an acceptance criterion.

If you genuinely find fewer than three problems, state what you checked and why it's clean. But be honest — agents almost always find problems when they actually look.

## Step 4: Fix what you found

Fix every problem from Step 3. Run tests again. Commit.

## Step 5: Final criterion map

List each acceptance criterion from Phase 1. Next to each, write the file:function that satisfies it and the test that verifies it. This is your proof of completion. If any row is empty, the work is not done.

## Key constraints

- **Code conforms to design docs, not the other way around.** If your implementation diverges from a design document, fix your code. If you believe the design is wrong, escalate — do not silently edit design docs to match your code.
- **No historical artifacts.** Comments, docs, and code must describe the current system. Never write "previously X" or "used to Y" or "replaced Z" — git history is for that.
