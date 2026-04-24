______________________________________________________________________

name: submodule-development
description: A workflow skill governing how to interact with and develop inside submodules (like sparkrun and openclaw), including configuring defaults, opening PRs, and running local integration branches.
category: development
risk: safe
source: local
compatibility: claude-code
triggers:

- "how do I use PRs locally"
- "how do I stack our changes"
- "create an integration branch"
- "merge open PRs into a local branch"
- "submodule local testing"
- "create a PR in the submodule"
- "push upstream"

______________________________________________________________________

# Submodule Development Workflow

## Purpose

When developing features inside upstream dependencies (like `sparkrun` and `openclaw`), we are operating within Git submodules that have their own remotes (`origin` for forks, `upstream` for source repositories).

This skill defines the standard operating procedure for checking out submodules, establishing correct default GitHub CLI behavior, and aggregating multiple open PRs into a single `local-dev` integration branch for local use.

## PR Creation Standard

When preparing or updating any upstream PR for these submodules, you **MUST** load and follow the `pr-writer` skill. This skill enforces Sentry-style PR standards and ensures clean, contextual PR descriptions. To load the skill, run `view_file` on `/home/jlapenna/.gemini/antigravity/skills/pr-writer/SKILL.md` before using `gh pr create` or `gh pr edit`.

## PR Verification and Maintenance

Upstream maintainers will not merge PRs that have failing checks or unaddressed comments. You must actively manage your submissions:

1. **Continuous Integration (CI):** You MUST regularly check the CI status of open PRs using `gh pr checks`. You should only address CI issues if they are related to your changes. If you identify failures that are directly caused by your work, promptly push fixes to the PR branch. Do not fix unrelated CI failures inherited from `main`.
1. **Scope Checking:** When updating a PR or submitting new code, you MUST use the `pr-gutcheck` skill. This ensures all implementation changes strictly adhere to the PR description and any accepted review comments, guarding against scope creep or the unintentional inclusion of unrelated modifications.
1. **Review Comments:** You MUST actively address feedback from human reviewers and automated bots (like Codex bots). Use the `address-github-comments` skill (located globally) to help evaluate and resolve these comments. When updating a PR to address feedback, you MUST reply to every human comment (such as via `gh pr comment`) to explicitly confirm that their concerns have been resolved and what actions were taken. Do not leave reviewers "awaiting replies."
1. **Resolve Conversations:** Pushing code fixes and leaving a top-level `@comment` reply does **not** actually mark the review thread as resolved in GitHub! Once feedback is addressed, you MUST explicitly resolve the individual review conversations programmatically. Use the helper script:
   ```bash
   uv run python skills/submodule-development/scripts/resolve_pr_threads.py
   ```
   Do not assume conversations will be resolved automatically.
1. **OpenClaw Specific:** For `openclaw` PRs, if the GitHub Codex review bot does not trigger, you should run `codex review --base origin/main` locally and treat the findings as mandatory review items.

## Core Setup: GitHub CLI Routing

Because the submodules track the main upstream source repositories natively, we do not configure local "fork" remotes for daily work. Your fork is strictly used by GitHub as a hosting space for PR branches.

1. Ensure your submodule's default `origin` remote points directly to the upstream repository (e.g., `openclaw/openclaw`), **not** your personal fork.
1. Ensure the GitHub CLI default repository is targeted correctly:
   ```bash
   gh repo set-default <upstream-org>/<repo-name>
   ```
   _(This guarantees `gh` commands natively interact with the upstream project, automatically routing pushes to your fork behind the scenes when using `gh pr create`.)_
1. If human developers are working locally and want standard `git push` behaviors to securely route to their fork without altering the `origin` fetch target, configure `pushDefault`:
   ```bash
   git remote add fork <url-to-your-fork>
   git config remote.pushDefault fork
   ```
   _(This establishes the gold standard topology: all clones/fetches synchronize with the canonical upstream `origin`, while all pushes safely isolate onto the `fork` hosting space)._

## Feature Integration Principles

1. **Feature Worktrees for All Development:** Instead of switching feature branches inside the primary submodule directory, you MUST create a Git worktree for every feature or bug fix branch (e.g., `git worktree add ../<submodule>-<feature-branch> <branch>`). The primary submodule checkout (e.g., `openclaw/` or `sparkrun/`) must remain firmly pinned to either `origin/main` or the `local-dev` integration branch at all times.
1. **Modify Code Exclusively in Worktrees:** All source code modifications, programmatic file edits, and PR feedback patches MUST be applied strictly from within the isolated feature worktree directory. Never commit or edit feature code directly in the primary submodule checkout.
1. **Use an integration branch for testing the stack:** Instead of stacking interdependent PRs to test them together, create a `local-dev` branch inside the primary submodule strictly for local execution, which safely merges all active feature branches resulting from your worktrees.
1. **Keep independent features unstacked:** Unless feature B fundamentally depends on feature A, always branch off `origin/main` for clean PRs.
1. **No Orphan Commits on `local-dev`:** The `local-dev` branch is strictly a read-only aggregation target. You must **never** author new commits directly onto `local-dev` that aren't also safely contained in a standalone feature worktree.
1. **Commit isolated integrations to `services`:** The root `services` repo should track the commit of the `local-dev` branch (from the primary submodule) to ensure stability during system-wide testing. However, when committing this pointer update, you MUST NEVER sweep unrelated files from the `services` repository into the commit of the main repository.
1. **No Unsubmitted Changes:** Never end up with unsubmitted changes in the main submodule directory. Any modifications you make in a worktree must be correctly tracked and fully committed; otherwise, you dirty the state and violate the submodule protocol.

## Step-by-Step Workflow

### Prep Work

1. Activate the `pr-writer` skill and adhere to it to learn how to structure and write high-quality PR descriptions every time you create or edit a PR.

### 0. Setting Up Feature Worktrees

If you need to make changes to a submodule, do NOT change branches in the main submodule directory.

1. Navigate to the primary submodule directory (e.g. `cd openclaw`).
1. Add a new worktree for your feature. We conventionally place the worktree inside the `.worktrees/` folder at the root of the repository so it stays within IDE workspaces but remains ignored by `git`. To avoid relative path (`../`) confusion, **always use absolute paths**:
   ```bash
   # resolve the absolute root path from the submodule directory
   ROOT_DIR="$(cd .. && pwd)"

   # create a new branch and worktree safely within the ignored .worktrees space
   git worktree add -b <feature-name> "$ROOT_DIR/.worktrees/<submodule-name>/<feature-name>" origin/main
   ```
1. Navigate to the newly created absolute worktree path to perform all coding, testing, and PR creation.
1. When finished and merged, clean up the worktree using `git worktree remove <absolute-path>`.

### Updating Existing PRs (Worktree Maintenance)

When returning to an active PR to address upstream feedback, fix CI, or perform requested updates, you must execute the entire cycle strictly within its isolated feature worktree:

1. **Review Pending Feedback:** Navigate to the worktree and use `gh pr view` and `gh pr comments` to review the active state of the PR and identify the specific actions required.
1. **Apply Updates:** Implements fixes directly in the worktree. Run any local tests if applicable.
1. **Verify Scope (`pr-gutcheck`):** Before committing and pushing, load and execute the `pr-gutcheck` skill against your uncommitted changes or recent local commits to ensure you are strictly resolving the required feedback and haven't introduced out-of-scope logic.
1. **Commit & Push:** Commit your approved changes and push the updates up to the active fork PR branch (`git push fork <branch>`).
1. **Resolve Conversations:** Formally address the reviewer threads using GitHub tools (as described in the PR Verification section) and explicitly mark conversations as resolved.

### 1. Identify the Submodule and Open PRs

Ensure you are inside the primary submodule directory (e.g., `cd openclaw` or `cd sparkrun`).

**Verify Remotes:** Before starting, verify your Git remotes (`git remote -v`). This workflow assumes `origin` points to the main upstream repository.

List the active PR branches you wish to test (or use `gh pr list` generally to find other contributors' PRs):

```bash
gh pr list --author "@me"
```

### 2. Prepare the `local-dev` Branch

Ensure you are synchronized with the `origin` repository and create a fresh `local-dev` branch based on the designated canonical root for each specific proxy framework:

> [!IMPORTANT]
> **Base Branch Differentiation**
>
> - **For `sparkrun`**: `local-dev` MUST ALWAYS be based on the tip of the development branch (`origin/main`).
> - **For `openclaw`**: `local-dev` MUST ALWAYS be based on the latest stable production tag (bypassing betas). Do not use `origin/main` for openclaw.

```bash
git fetch --tags origin
# For sparkrun:
git checkout -B local-dev origin/main

# For openclaw:
# Automatically find the newest stable v2026.x tag (excluding -beta and -rc)
LATEST_STABLE=$(git tag --sort=-creatordate | grep -E '^v[0-9]{4}\.[0-9]+\.[0-9]+$' | head -n 1)
git checkout -B local-dev "$LATEST_STABLE"
```

_(Using `-B` forcefully resets `local-dev` to the canonical root if it already exists, clearing out old unmerged artifacts)._

### 3. Merge the Feature Branches

**Check All Worktrees First:** You MUST explicitly check all active feature worktrees (e.g. inside `.worktrees/<submodule>/`) and rebase them onto `origin/main` before merging. This prevents them from falling behind upstream, ensuring they are always clean and ready for PR submission.

Because your remote is the main upstream repository, rather than fetching individual branches from forks, you will seamlessly pull the exact head state of any PR directly from GitHub's internal pull refs. **Always merge sequentially (one by one)**.

If you are merging local worktrees that haven't been pushed yet, you can merge them directly by branch name from within the primary submodule directory.

For PRs already upstream, run the following:

```bash
git fetch origin pull/<PR-ID>/head
git merge --no-edit FETCH_HEAD
# (Repeat for each PR)
```

For local feature worktree branches:

```bash
git merge --no-edit <feature-branch>
```

_Note: If there are merge conflicts between features, resolve them locally on `local-dev` after the failing merge command. Merging sequentially ensures you know exactly which PR introduced the collision._

### 4. Verify Clean Submodule State

Before closing the process, you MUST verify that the git tree for the primary submodule is entirely clean. Run `git status` inside the main submodule directory. There must be **no** uncommitted modifications, **no** staged files, and **no** open indexed commits left unresolved. If any exist, you must either commit or revert them to ensure the submodule protocol isn't violated.

### 5. Update the Root Repo Pointer

Navigate back to the root (`services`) directory. Since the submodule's pointer has moved, the root repo will show unstaged changes.
Commit this updated pointer to ensure system stability, but you MUST isolate the commit to ONLY the submodule path.

```bash
cd ..
git add <submodule-dir>
git commit -m "chore: point <submodule> to local-dev integration branch"
```

### 6. Output and Track the Integration State

After completing the submodule process, you MUST run `python3 scripts/submodule_status.py` to output the current integrated submodule PRs to the user cleanly.
Do not embed dynamic markdown tables inside this skill document, as they become stale immediately. Depend entirely on the `submodule_status.py` script to generate contextual awareness for the user.

### 7. Completion Condition

The submodule process is only considered complete when:

1. All primary submodules have been successfully restored to their `local-dev` branches.
1. There are absolutely no dangling (untracked, modified, or staged) files left in the primary submodules or affecting the root workspace from the process.

## Prerequisites

1. Ensure the GitHub CLI default repository is correctly targeting upstream (`gh repo set-default <upstream-org>/<repo-name>`).
1. Verify all local feature worktrees are cleanly rebased onto `origin/main` prior to triggering large merges.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill to attempt pushing the synthesized `local-dev` branch back up to the canonical `origin` remote.

## Examples

### Anti-Pattern: Inline Coding Chaos

```bash
# BAD: Switching branches directly inside the primary submodule, breaking parent root git pointers
cd openclaw && git checkout -b my-new-feature
```

### Correct Pattern: Worktree Isolation

```bash
# GOOD: Adding an isolated worktree outside the parent's immediate traversal space
ROOT_DIR="$(cd .. && pwd)"
git worktree add -b my-new-feature "$ROOT_DIR/.worktrees/openclaw/my-new-feature" origin/main
```

## Output Format

You MUST conclude your integration actions with this exact structure:

```markdown
### 1. Execution Summary
*(Detail the branches fetched, merged, and worktrees created)*

### 2. Active Integrations
*(Directly output the results from running `python3 scripts/submodule_status.py` here)*

### 3. Repo Health
*(Confirm that the primary submodule and the root `services` repo show zero dangling/untracked files)*
```
