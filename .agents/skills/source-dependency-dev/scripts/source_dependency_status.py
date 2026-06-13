#!/usr/bin/env python3
import json
import os
import shlex
import subprocess


def run_cmd(cmd, cwd=None):
    try:
        env = os.environ.copy()
        env["GH_PAGER"] = ""
        env["GH_PROMPT_DISABLED"] = "1"

        if isinstance(cmd, str):
            cmd = shlex.split(cmd)

        result = subprocess.run(
            cmd, cwd=cwd, shell=False, check=True, capture_output=True, text=True, env=env
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_pr_status(source_dependency_dir, repo_name):
    if not os.path.isdir(source_dependency_dir):
        return []

    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo_name,
        "--author",
        "@me",
        "--state",
        "open",
        "--json",
        "number,title,url,headRefName,reviews,commits,latestReviews,comments,updatedAt",
    ]
    output = run_cmd(cmd, cwd=source_dependency_dir)
    if not output:
        return []

    try:
        prs = json.loads(output)
    except json.JSONDecodeError:
        return []

    return prs


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dependencys = ["openclaw", "sparkrun", "sparkstack-registry"]

    repo_map = {
        "openclaw": "openclaw/openclaw",
        "sparkrun": "spark-arena/sparkrun",
        "sparkstack-registry": "jlapenna/sparkstack-registry",
    }

    print("### 1. Pending Pull Requests\n")
    print("| Repository | PR ID / Link | Branch | Title | Updated At |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    pr_details = []

    for sub in source_dependencys:
        parent_dir = os.path.dirname(os.path.dirname(root_dir))
        if sub == "sparkstack-registry":
            sub_dir = os.path.join(parent_dir, sub)
        else:
            sub_dir = os.path.join(os.path.dirname(parent_dir), sub)
        repo_name = repo_map.get(sub, "")
        prs = get_pr_status(sub_dir, repo_name)
        for pr in prs:
            pr_repo = f"**`{sub}`**"
            pr_link = f"[#{pr['number']}]({pr['url']})"
            branch = f"`{pr['headRefName']}`"
            title = f" `{pr['title']}`"
            updated = pr["updatedAt"][:10]

            print(f"| {pr_repo} | {pr_link} | {branch} | {title} | {updated} |")
            pr_details.append((sub, pr))

    if pr_details:
        print("\n### 2. Latest Updates & Comments\n")
        for sub, pr in pr_details:
            pr_link = f"[#{pr['number']}]({pr['url']})"
            print(f"#### {pr_link} - {pr['title']} (`{sub}`)")

            commits = pr.get("commits", [])
            if commits:
                latest_commit = commits[-1]
                date = latest_commit.get("authoredDate", "")[:10]
                headline = latest_commit.get("messageHeadline", "No commit")
                print(f"- **Latest Update:** {headline} ({date})")

            comments = pr.get("comments", [])
            if comments:
                latest_comment = comments[-1]
                author = latest_comment.get("author", {}).get("login", "Unknown")
                body = latest_comment.get("body", "").replace("\n", " ").strip()
                if len(body) > 120:
                    body = body[:117] + "..."
                print(f"- **Latest Comment (@{author}):** {body}")
            else:
                print("- **Latest Comment:** None")
            print()

    print("\n### 2. Integration Branch Status\n")
    print("| Source Dependency | Integration Branch | Current Configured Tracking |")
    print("| :--- | :--- | :--- |")

    for sub in source_dependencys:
        parent_dir = os.path.dirname(os.path.dirname(root_dir))
        if sub == "sparkstack-registry":
            sub_dir = os.path.join(parent_dir, sub)
        else:
            sub_dir = os.path.join(os.path.dirname(parent_dir), sub)

        branch = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=sub_dir)

        integration_branch = "main" if sub == "sparkstack-registry" else "local-dev"
        if sub == "sparkrun":
            base_ref = "upstream/develop"
        elif sub == "sparkstack-registry":
            base_ref = "origin/main"
        else:
            # For openclaw, local-dev tracks the newest stable tag
            tag_cmd = "git tag -l 'v*' | grep -v beta | sort -V | tail -n 1"
            base_ref = run_cmd(tag_cmd, cwd=sub_dir)
            if not base_ref:
                base_ref = "upstream/main"

        # Determine if current branch is ahead of base_ref
        commits_ahead_output = run_cmd(
            f"git rev-list --count {base_ref}..{branch} 2>/dev/null", cwd=sub_dir
        )
        try:
            commits_ahead = int(commits_ahead_output) if commits_ahead_output else 0
        except ValueError:
            commits_ahead = 0

        status = (
            f"Tracking {branch} ({commits_ahead} unmerged commits)"
            if commits_ahead > 0
            else f"Tracking {branch}"
        )

        repo_col = f"**`{sub}`**"
        print(f"| {repo_col} | `{integration_branch}` | {status} |")


if __name__ == "__main__":
    main()
