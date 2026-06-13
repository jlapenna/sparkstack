---

name: pr-gutcheck
description: "Review a Pull Request to ensure the implementation strictly matches the PR description and comments, and does nothing else."
category: development
risk: low
source: local
compatibility: claude-code
triggers:

- audit PR
- scope creep
- review pull request
- check PR intent
- evaluate comments

---

# PR Gut Check

## Purpose

This skill ensures an agent performs a strict "gut check" on a Pull Request. It verifies that the PR's implementation perfectly aligns with its stated purpose in the PR description and any associated comments, explicitly flagging any scope creep, undocumented changes, or missed requirements.

## Use this skill when

- Executing a code review on a Pull Request.
- Checking if a PR's code changes strictly match the author's description and stated intent.
- Verifying whether an implementation correctly addresses all discussion threads and reviewer comments.
- Auditing a diff for scope creep or unrelated changes sneaking into the PR.

## Do not use this skill when

- You are looking to do a deep security audit (use security reviews).
- You are primarily looking for code quality or logic bugs (use code reviews).

## Instructions

1. **Context Gathering**

   - **Read the PR Description:** Carefully analyze the PR title, body, and any linked issues to establish the explicit "intent" of the PR.
   - **Read the Comments:** Review all associated feedback, reviewer requests, and discussions on the PR to capture any evolved context or constraints.
   - **Read the Implementation:** Inspect the actual code changes (diffs) made in the PR.

1. **The "Gut Check" Evaluation**

   - **Intent Alignment:** Does the code actually accomplish the goal defined in the PR description?
   - **Comment Alignment:** Does the code correctly fulfill the agreements or resolutions reached in the PR comments?

1. **Scope Creep Detection**

   - **Unrelated Changes:** Identify any file changes, refactors, or new configurations that are completely unrelated to the PR's stated goals.
   - **"Sneak-ins":** Flag modifications that "sneak in" extra functionality, dependency updates, or fixes not documented in the PR description.

1. **Integration with Other Review Skills**
   To produce a fully comprehensive PR audit, layer in these specific skills:

   - **Review Enhance**: If the PR lacks a proper description, use this skill *first* to generate a detailed summary from the diff, then use the generated summary as the baseline for your gut check.
   - **Code Review**: Once the scope gut-check passes, use these skills to hunt for logic bugs, performance regressions, readability issues, and security vulnerabilities within the approved scope.
   - **Fix Review**: If the PR specifically claims to patch an audit finding or bug, invoke this skill to scientifically verify that the fix addresses the root cause without introducing new regressions.

1. **Deliver the Verdict**

   - **Overall Assessment:** Clearly state whether the PR "Passes" or "Fails" the gut check.
   - **Out-of-Scope Items:** Provide a bulleted list of any undocumented or unrelated changes found in the implementation.
   - **Missing Items:** List any requirements from the PR description or comments that are missing from the implementation.
   - **Actionable Advice:** Recommend next steps (e.g., "Revert the unrelated changes in file X," or "Update the PR description to cover the added scope").
   - **Next Steps:** Propose kicking off full code-quality/security checks via code review if the PR passed the strict scope check.

## Prerequisites

1. Before stating a verdict, you MUST actively read the PR text description `body` AND the PR comment conversation threads (`gh pr view` and `gh pr comments`).
1. You MUST execute a comprehensive diff generation (`gh pr diff`) across all files to catch buried modifications.

## Examples

### Anti-Pattern: Permissive Auditing

```markdown
# BAD Verdict
The PR looks great, it fixes the bug. There is a random package.json upgrade for an unrelated library, but it's probably fine. Pass.
```

### Correct Pattern: Strict Scope Containment

```markdown
# GOOD Verdict
**Verdict: Fail (Scope Creep Detected)**
This PR is explicitly scoped to "Add caching logic to Redis layer", but the diff in `utils_auth.py` sneaks in unrelated changes to the JWT validation expiration timers. Remove the JWT changes.
```

## Output Format

Conclude the Gut Check STRICTLY with:

```markdown
### 1. Verdict Assessment
*(State explicitly: **PASS** or **FAIL (Scope Creep/Missed Intent)**)*

### 2. Out-of-Scope Items
*(Bullet list of any configurations, files, or dependency upgrades found in the diff that were not logically announced in the PR body. If none, write "None Detected")*

### 3. Missing Requirements
*(Bullet list of any promises made by the PR author in the body/comments that were not actually coded in the diff. If none, write "None Detected")*

### 4. Required Action Plan
*(Actionable steps for the author to pass the audit, e.g. "Revert modifications to file X" or "Update the PR description to admit you modified Z")*
```
