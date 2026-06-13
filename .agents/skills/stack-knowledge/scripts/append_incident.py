#!/usr/bin/env python3
import datetime

SKILL_FILE = "skills/stack-knowledge/SKILL.md"


def append_incident(title, scenario, hypothesis, action, result, learnings):
    date_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

    incident_block = f"""
______________________________________________________________________

### {date_str} — {title}

- **Scenario**: {scenario}
- **Hypothesis**: {hypothesis}
- **Action**: {action}
- **Result**: {result}

**Learnings:**

"""
    for learning in learnings:
        incident_block += f"- {learning}\n"

    try:
        with open(SKILL_FILE, "a") as f:
            f.write(incident_block)
        print(f"Successfully appended incident to {SKILL_FILE}")
    except FileNotFoundError:
        print(f"Error: {SKILL_FILE} not found. Ensure you run this from the project root.")


if __name__ == "__main__":
    print("Stack Knowledge Incident Logger")
    print("-" * 30)
    title = input("Short Title: ")
    scenario = input("Scenario: ")
    hypothesis = input("Hypothesis: ")
    action = input("Action: ")
    result = input("Result: ")
    print("Learnings (enter one per line, leave blank to finish):")
    learnings = []
    while True:
        line = input("> ")
        if not line.strip():
            break
        learnings.append(line.strip())

    append_incident(title, scenario, hypothesis, action, result, learnings)
