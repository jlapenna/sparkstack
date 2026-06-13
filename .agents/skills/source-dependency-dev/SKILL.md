______________________________________________________________________

name: source-dependency-dev
description: A workflow skill governing how to interact with and develop inside source dependencies (like sparkrun and openclaw), including configuring defaults, opening PRs, and running local integration branches.
category: development
risk: safe
source: local
compatibility: claude-code
triggers:

- "how do I use PRs locally"
- "how do I stack our changes"
- "create an integration branch"
- "merge open PRs into a local branch"
- "source dependency local testing"
- "create a PR in the source dependency"
- "push upstream"

______________________________________________________________________

# Source Dependency Development Workflow

## Purpose

When developing features inside upstream dependencies (like `sparkrun` and `openclaw`), we are operating within Git source dependencies that have their own remotes (`origin` for forks, `upstream` for source repositories).

This skill defines the standard operating procedure for checking out source dependencies, establishing correct default GitHub CLI behavior, and aggregating multiple open PRs into a single `local-dev` integration branch for local use.

**CRITICAL RULE:** For `sparkrun`, you **MUST ALWAYS** ensure the `local-dev` branch is the currently checked-out branch in the primary source dependency directory before making any changes, running tests, or diagnosing issues in this project.

## PR Creation Standard

When preparing or updating any upstream PR for these source dependencies, you **MUST** load and follow the `pr-writer` skill. This skill enforces Sentry-style PR standards and ensures clean, contextual PR descriptions. To load the skill, run `view_file` on `~/.gemini/antigravity/skills/pr-writer/SKILL.md` before using `gh pr create` or `gh pr edit`.

## PR Verification and Maintenance

Upstream maintainers will not merge PRs that have failing checks or unaddressed comments. You must actively manage your submissions:

1. **Continuous Integration (CI):** You MUST regularly check the CI status of open PRs using `gh pr checks`. You should only address CI issues if they are related to your changes. If you identify failures that are directly caused by your work, promptly push fixes to the PR branch. Do not fix unrelated CI failures inherited from `main`.
1. **Scope Checking:** When updating a PR or submitting new code, you MUST use the `pr-gutcheck` skill. This ensures all implementation changes strictly adhere to the PR description and any accepted review comments, guarding against scope creep or the unintentional inclusion of unrelated modifications.
1. **Review Comments:** You MUST actively address feedback from human reviewers and automated bots (like Codex bots). Use the `address-github-comments` skill (located globally) to help evaluate and resolve these comments. When updating a PR to address feedback, you MUST reply to every human comment (such as via `gh pr comment`) to explicitly confirm that their concerns have been resolved and what actions were taken. You MUST always ask the user for comment approval before posting any response to GitHub comments. Do not leave reviewers "awaiting replies."
1. **Resolve Conversations:** Pushing code fixes and leaving a top-level `@comment` reply does **not** actually mark the review thread as resolved in GitHub! Once feedback is addressed, you MUST explicitly resolve the individual review conversations programmatically using the GitHub GraphQL API or the `gh` CLI.
   Do not assume conversations will be resolved automatically.
1. **OpenClaw Specific:** For `openclaw` PRs, if the GitHub Codex review bot does not trigger, you should run `codex review --base origin/main` locally and treat the findings as mandatory review items.

## Core Setup: GitHub CLI Routing

Because the source dependencies track the main upstream source repositories natively, we do not configure local "fork" remotes for daily work. Your fork is strictly used by GitHub as a hosting space for PR branches.

1. Ensure your source dependency's default `origin` remote points directly to the upstream repository (e.g., `openclaw/openclaw`), **not** your personal fork.
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

1. **Build on `local-dev`:** For active daily development, build new features directly on top of the `local-dev` branch in the primary source dependency checkout. This allows you to accumulate multiple interdependent or independent features in your local testing environment without losing progress (e.g., you won't lose "change branch A" when starting "new feature C").
1. **Publish via Feature Worktrees:** When a feature is ready to be published as a Pull Request, you MUST NOT push `local-dev` or branch directly off `local-dev`. Instead, create a new feature worktree based strictly on the pristine upstream branch (`origin/develop` for sparkrun, `origin/main` for openclaw).
1. **Migrate to Worktrees:** Port (e.g., via `git cherry-pick <specific-commit-hash>` or patch) only the specific changes for that feature from `local-dev` into the clean feature worktree. NEVER merge `local-dev` into your feature branch.
1. **MANDATORY ISOLATION VERIFICATION:** AI agents frequently and accidentally sweep unrelated changes, release notes, or config churn into PRs. Before pushing a feature branch, you **MUST** run `git diff <upstream-base-branch> --name-only` and explicitly verify that **ONLY** the files related to your specific feature are modified. If any unrelated files appear, you MUST remove them from the commit before pushing.
1. **Push from Worktree:** Push the isolated feature branch from the worktree to your fork and create the PR. This ensures PRs are cleanly mergeable on top of the target base branch without bringing along other unfinished features from `local-dev`.
1. **Update Existing PRs in Worktrees:** All PR feedback patches and CI fixes MUST be applied strictly from within the isolated feature worktree directory. Once updated and pushed, you can merge those fixes back into `local-dev` to keep your local environment up to date.
1. **Handle Closed PRs:** PRs that are closed are considered abandoned. You MUST NOT apply them to the `local-dev` integration branch. If they exist in your local `local-dev` branch, they MUST be reverted locally.
1. **Commit isolated integrations to `sparkstack`:** The root `sparkstack` repo should track the commit of the `local-dev` branch (from the primary source dependency) to ensure stability during system-wide testing. However, when committing this pointer update, you MUST NEVER sweep unrelated files from the `sparkstack` repository into the commit of the main repository.

## Step-by-Step Workflow

### Prep Work

1. Activate the `pr-writer` skill and adhere to it to learn how to structure and write high-quality PR descriptions every time you create or edit a PR.

### 0. Developing on `local-dev`

For new features and local testing, build directly on the `local-dev` integration branch.

1. Navigate to the primary source dependency directory (e.g., `cd ../openclaw` or `cd ../sparkrun`).
1. Ensure you are on the `local-dev` branch. If it doesn't exist, create it from the upstream base branch (see Syncing section below).
1. Commit your work continuously to `local-dev` so you don't lose local progress when moving between tasks.

### 1. Publishing a Feature (Worktree Creation)

When a specific feature or fix is ready for review, extract it into a clean PR branch.

1. Navigate to the primary source dependency directory.
1. Add a new worktree for your feature based on the canonical root (`origin/main`). We conventionally place the worktree inside the `.worktrees/` folder at the root of the repository so it stays within IDE workspaces but remains ignored by `git`. To avoid relative path (`../`) confusion, **always use absolute paths**:
   ```bash
   # resolve the absolute root path from the source dependency directory
   ROOT_DIR="$(cd ../sparkstack && pwd)"

   # create a new branch and worktree safely within the ignored .worktrees space
   git worktree add -b <feature-name> "$ROOT_DIR/.worktrees/<source dependency-name>/<feature-name>" <upstream-base-branch> # e.g. origin/develop or origin/main
   ```
1. Navigate to the newly created absolute worktree path.
1. **Port Your Changes:** Use `git cherry-pick <commit-hash>` (or manual patching) to bring over the specific commits for this feature from your `local-dev` branch into this feature branch. **NEVER** merge `local-dev` into this branch.
1. **MANDATORY VERIFICATION:** Before pushing, you **MUST** verify the branch has no unintended changes:
   ```bash
   git diff <upstream-base-branch> --name-only
   ```
   **CRITICALLY EXAMINE THIS LIST.** If you see any files that are not strictly necessary for your fix/feature (e.g., unrelated release notes, other feature files, dependency lockfile churn), you **MUST** remove them (e.g., using `git checkout <upstream-base-branch> -- <file>` and `git commit --amend`) before opening the PR.
1. **Push and PR:** Push the feature branch to your fork (`git push fork <feature-name>`), and open the PR using the `pr-writer` skill.
1. When finished and merged upstream, clean up the worktree using `git worktree remove <absolute-path>`.

### 2. Updating Existing PRs (Worktree Maintenance)

When returning to an active PR to address upstream feedback, fix CI, or perform requested updates, execute the entire cycle strictly within its isolated feature worktree:

1. **Review Pending Feedback:** Navigate to the worktree and use `gh pr view` and `gh pr comments` to review the active state of the PR.
1. **Apply Updates:** Implements fixes directly in the worktree. Run any local tests if applicable.
1. **Verify Scope (`pr-gutcheck`):** Before committing and pushing, load and execute the `pr-gutcheck` skill against your uncommitted changes to ensure you haven't introduced out-of-scope logic.
1. **Commit & Push:** Commit your approved changes and push the updates up to the active fork PR branch (`git push fork <branch>`).
1. **Resolve Conversations:** Formally address reviewer threads and run the thread resolution script.
1. **Sync Back:** Merge or cherry-pick the updated feature branch back into your primary `local-dev` branch, as changes made to our source dependencies are always required locally.

### 3. Synchronizing the `local-dev` Branch

To ensure your local environment doesn't drift too far from upstream, or if you need to start fresh, update the `local-dev` branch. The strategy differs significantly between repositories to balance between history preservation and stability.

#### A. SparkRun (Automated Rebase)

`sparkrun` uses a **rebase** strategy to keep local patches on top of upstream changes. This is the preferred method because it automatically preserves all local commits and PRs already integrated into `local-dev`.

- **Command:** `uv run manager/update_sparkrun.py --pull-latest`
- **Effect:** Fetches `upstream/main`, then rebases your local `local-dev` branch onto it. Your local-only patches will remain at the top of the commit history.

#### B. OpenClaw (Automated Rebase onto Stable)

`openclaw` uses a **rebase** strategy against tagged stable releases to maintain alignment with official releases while preserving local patches.

- **Command:** `uv run manager/update_openclaw.py --pull-latest` (or similar script if available)
- **Effect:** Fetches the latest stable tag from upstream and rebases your local `local-dev` branch onto it, preserving your local patches.

#### C. Manual Sync Fallback (General)

If automated scripts are unavailable, use these manual primitives:

```bash
git fetch --tags upstream

# For sparkrun (Preserves patches)
git checkout local-dev && git rebase upstream/main

# For openclaw (Preserves patches against stable tag)
git checkout local-dev && git rebase <latest-tag>
```

### 4. Restoring Local-Dev Integrations (After Sync)

If a manual reset clears your `local-dev` patches, you must restore them.

1. **Identify Lost Commits**: Use `git reflog local-dev` to find the SHAs of the commits that were present before the reset.
   ```bash
   git reflog local-dev | head -n 20
   ```
1. **Identify PRs/Branches**: If you don't have the branch names, search for the PRs using keywords from the commit messages:
   ```bash
   gh pr list --search "keyword from commit" --limit 5
   ```
1. **Re-apply Patches**: Merge the identified feature branches back into `local-dev`. For `sparkrun`, also check for PRs from other contributors that may not have been in your local history:
   ```bash
   git merge <branch-name> --no-edit
   ```

### 5. Verify Clean Source Dependency State

Before closing the process, you MUST verify that the git tree for the primary source dependency is entirely clean and that no commits have been left unpushed in any worktree.

**Run these explicit commands to verify the state:**

```bash
# 1. Check the primary worktree is clean
git status

# 2. List all active worktrees
git worktree list

# 3. Check the status of ALL worktrees to find uncommitted or unpushed changes
for wt in $(git worktree list | awk '{print $1}'); do
  echo "--- Checking $wt ---"
  git -C "$wt" status
done
```

There must be **no** uncommitted modifications, **no** staged files, and **no** open indexed commits left unresolved in the primary repository or any worktree. If a worktree says `Your branch is ahead of 'origin/...' by N commits`, you MUST push it and ensure it has an active PR.

### 6. Output and Track the Integration State

After completing the source dependency process, you MUST verify and output the current integrated source dependency state to the user by running `git log --oneline -10` and `git status` in each source dependency directory.
Do not embed dynamic markdown tables inside this skill document, as they become stale immediately. Depend entirely on live git state to generate contextual awareness for the user.

### 7. Completion Condition

The source dependency process is only considered complete when:

1. All primary source dependencies are checked out to their `local-dev` branches.
1. There are absolutely no dangling (untracked, modified, or staged) files left in the primary source dependencies or affecting the root workspace from the process.
1. All feature worktrees are fully pushed to `origin` and have active PRs.

## Prerequisites

1. Ensure the GitHub CLI default repository is correctly targeting upstream (`gh repo set-default <upstream-org>/<repo-name>`).
1. Verify all local feature worktrees are cleanly rebased onto their upstream base branch (`origin/develop` or `origin/main`) prior to triggering large merges.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill to attempt pushing the synthesized `local-dev` branch back up to the canonical `origin` remote.

## Examples

### Anti-Pattern: Inline Coding Chaos

```bash
# BAD: Switching branches directly inside the primary source dependency, breaking parent root git pointers
cd ../openclaw && git checkout -b my-new-feature
```

### Correct Pattern: Worktree Isolation

```bash
# GOOD: Adding an isolated worktree outside the parent's immediate traversal space
ROOT_DIR="$(cd ../sparkstack && pwd)"
git worktree add -b my-new-feature "$ROOT_DIR/.worktrees/openclaw/my-new-feature" origin/main
```

## Output Format

You MUST conclude your integration actions with this exact structure:

```markdown
### 1. Execution Summary
*(Detail the branches fetched, merged, and worktrees created)*

### 2. Active Integrations
*(Directly output the results from running `python3 util/source_dependency_status.py` here)*

### 3. Repo Health
*(Confirm that the primary source dependency and the root `sparkstack` repo show zero dangling/untracked files, and no unpushed commits exist in any worktree)*
```
