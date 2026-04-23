#!/usr/bin/env python3
import subprocess
import json
import os


def run_cmd(cmd, cwd=None):
    try:
        env = os.environ.copy()
        env["GH_PAGER"] = ""
        env["GH_PROMPT_DISABLED"] = "1"
        result = subprocess.run(
            cmd, cwd=cwd, shell=True, check=True, capture_output=True, text=True, env=env
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_pr_status(submodule_dir):
    if not os.path.isdir(submodule_dir):
        return []

    cmd = "gh pr list --author '@me' --state open --json number,title,url,headRefName,reviews,commits,latestReviews,comments,updatedAt"
    output = run_cmd(cmd, cwd=submodule_dir)
    if not output:
        return []

    try:
        prs = json.loads(output)
    except json.JSONDecodeError:
        return []

    return prs


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    submodules = ["openclaw", "sparkrun"]

    print("### 1. Pending Pull Requests\n")
    print("| Repository | PR ID / Link | Branch | Title | Updated At |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    pr_details = []

    for sub in submodules:
        sub_dir = os.path.join(root_dir, sub)
        prs = get_pr_status(sub_dir)
        for pr in prs:
            repo_name = f"**`{sub}`**"
            pr_link = f"[#{pr['number']}]({pr['url']})"
            branch = f"`{pr['headRefName']}`"
            title = f" `{pr['title']}`"
            updated = pr["updatedAt"][:10]

            print(f"| {repo_name} | {pr_link} | {branch} | {title} | {updated} |")
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

    print("\n### 2. `local-dev` Branch Status\n")
    print("| Submodule | Integration Branch | Current Configured Tracking |")
    print("| :--- | :--- | :--- |")

    for sub in submodules:
        sub_dir = os.path.join(root_dir, sub)
        branch = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=sub_dir)

        # Determine if local-dev is ahead of main
        commits_ahead = run_cmd(
            "git rev-list --count main..local-dev 2>/dev/null || echo 0", cwd=sub_dir
        )
        status = (
            f"Tracking {branch} ({commits_ahead} unmerged commits)"
            if commits_ahead
            else f"Tracking {branch}"
        )

        repo_name = f"**`{sub}`**"
        print(f"| {repo_name} | `local-dev` | {status} |")


if __name__ == "__main__":
    main()
