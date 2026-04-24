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

When preparing or updating any upstream PR for these submodules, you **MUST** load and follow the `pr-writer` skill. This skill enforces Sentry-style PR standards and ensures clean, contextual PR descriptions. To load the skill, run `view_file` on `~/.gemini/antigravity/skills/pr-writer/SKILL.md` before using `gh pr create` or `gh pr edit`.

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

1. **Build on `local-dev`:** For active daily development, build new features directly on top of the `local-dev` branch in the primary submodule checkout. This allows you to accumulate multiple interdependent or independent features in your local testing environment without losing progress (e.g., you won't lose "change branch A" when starting "new feature C").
2. **Publish via Feature Worktrees:** When a feature is ready to be published as a Pull Request, do NOT push `local-dev`. Instead, create a new feature worktree based on `origin/main`.
3. **Migrate to Worktrees:** Port (e.g., via `git cherry-pick` or patch) only the specific changes for that feature from `local-dev` into the clean feature worktree.
4. **Push from Worktree:** Push the isolated feature branch from the worktree to your fork and create the PR. This ensures PRs are cleanly mergeable on top of `main` without bringing along other unfinished features from `local-dev`.
5. **Update Existing PRs in Worktrees:** All PR feedback patches and CI fixes MUST be applied strictly from within the isolated feature worktree directory. Once updated and pushed, you can merge those fixes back into `local-dev` to keep your local environment up to date.
6. **Commit isolated integrations to `services`:** The root `services` repo should track the commit of the `local-dev` branch (from the primary submodule) to ensure stability during system-wide testing. However, when committing this pointer update, you MUST NEVER sweep unrelated files from the `services` repository into the commit of the main repository.

## Step-by-Step Workflow

### Prep Work

1. Activate the `pr-writer` skill and adhere to it to learn how to structure and write high-quality PR descriptions every time you create or edit a PR.

### 0. Developing on `local-dev`

For new features and local testing, build directly on the `local-dev` integration branch.

1. Navigate to the primary submodule directory (e.g., `cd openclaw` or `cd sparkrun`).
2. Ensure you are on the `local-dev` branch. If it doesn't exist, create it from the upstream base branch (see Syncing section below).
3. Commit your work continuously to `local-dev` so you don't lose local progress when moving between tasks.

### 1. Publishing a Feature (Worktree Creation)

When a specific feature or fix is ready for review, extract it into a clean PR branch.

1. Navigate to the primary submodule directory.
2. Add a new worktree for your feature based on the canonical root (`origin/main`). We conventionally place the worktree inside the `.worktrees/` folder at the root of the repository so it stays within IDE workspaces but remains ignored by `git`. To avoid relative path (`../`) confusion, **always use absolute paths**:
   ```bash
   # resolve the absolute root path from the submodule directory
   ROOT_DIR="$(cd .. && pwd)"

   # create a new branch and worktree safely within the ignored .worktrees space
   git worktree add -b <feature-name> "$ROOT_DIR/.worktrees/<submodule-name>/<feature-name>" origin/main
   ```
3. Navigate to the newly created absolute worktree path.
4. **Port Your Changes:** Use `git cherry-pick` (or manual patching) to bring over the specific commits for this feature from your `local-dev` branch into this feature branch.
5. **Push and PR:** Push the feature branch to your fork (`git push fork <feature-name>`), and open the PR using the `pr-writer` skill.
6. When finished and merged upstream, clean up the worktree using `git worktree remove <absolute-path>`.

### 2. Updating Existing PRs (Worktree Maintenance)

When returning to an active PR to address upstream feedback, fix CI, or perform requested updates, execute the entire cycle strictly within its isolated feature worktree:

1. **Review Pending Feedback:** Navigate to the worktree and use `gh pr view` and `gh pr comments` to review the active state of the PR.
2. **Apply Updates:** Implements fixes directly in the worktree. Run any local tests if applicable.
3. **Verify Scope (`pr-gutcheck`):** Before committing and pushing, load and execute the `pr-gutcheck` skill against your uncommitted changes to ensure you haven't introduced out-of-scope logic.
4. **Commit & Push:** Commit your approved changes and push the updates up to the active fork PR branch (`git push fork <branch>`).
5. **Resolve Conversations:** Formally address reviewer threads and run the thread resolution script.
6. **Sync Back:** (Optional) If the fixes are needed locally, merge or cherry-pick the updated feature branch back into your primary `local-dev` branch.

### 3. Synchronizing the `local-dev` Branch

To ensure your local environment doesn't drift too far from upstream, or if you need to start fresh, update the `local-dev` branch:

> [!IMPORTANT]
> **Base Branch Differentiation**
>
> - **For `sparkrun`**: `local-dev` should track the tip of the development branch (`origin/main`).
> - **For `openclaw`**: `local-dev` should track the latest stable production tag (bypassing betas).

```bash
git fetch --tags origin

# To update your existing local-dev onto upstream:
git rebase origin/main
```
*(For openclaw, rebase onto the newest stable tag instead of `origin/main`.)*

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

1. All primary submodules are checked out to their `local-dev` branches.
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
