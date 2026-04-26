#!/usr/bin/env python3
import json
import subprocess
import sys


def get_pr_number():
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "number", "-q", ".number"],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())
    except subprocess.CalledProcessError:
        print(
            "Error: Could not determine current PR. Run this script inside a branch with an open PR."
        )
        sys.exit(1)


def main():
    pr_number = get_pr_number()
    print(f"Fetching review threads for PR #{pr_number}...")

    # Needs repo and owner info to run exact GraphQL
    try:
        repo_info = subprocess.run(
            ["gh", "repo", "view", "--json", "owner,name"],
            capture_output=True,
            text=True,
            check=True,
        )
        repo_data = json.loads(repo_info.stdout)
        owner, name = repo_data["owner"]["login"], repo_data["name"]
    except Exception as e:
        print(f"Failed to fetch repo data: {e}")
        sys.exit(1)

    query = """
    query($name: String!, $owner: String!, $pr_number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $pr_number) {
          reviewThreads(first: 50) {
            nodes {
              id
              isResolved
              comments(first: 1) {
                nodes {
                  body
                }
              }
            }
          }
        }
      }
    }
    """
    cmd = [
        "gh",
        "api",
        "graphql",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"pr_number={pr_number}",
        "-f",
        f"query={query}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

    unresolved = [t for t in threads if not t["isResolved"]]
    if not unresolved:
        print("No unresolved review threads found!")
        sys.exit(0)

    print(f"Found {len(unresolved)} unresolved threads. Resolving...")
    for t in unresolved:
        thread_id = t["id"]
        comment_preview = (
            t["comments"]["nodes"][0]["body"][:50] + "..."
            if t["comments"]["nodes"]
            else "Unknown comment"
        )
        print(f"Resolving thread [{thread_id}] ('{comment_preview}')")

        mut_query = """
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread { isResolved }
          }
        }
        """
        mut_cmd = [
            "gh",
            "api",
            "graphql",
            "-F",
            f"threadId={thread_id}",
            "-f",
            f"query={mut_query}",
        ]
        subprocess.run(mut_cmd, capture_output=True)

    print("Successfully resolved threads.")


if __name__ == "__main__":
    main()
