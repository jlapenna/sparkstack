---
name: sparkrun run bug report
about: Create a report to help us find & fix issues when running a recipe
title: ''
labels: ''
assignees: ''

---

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Provide the full and unedited `sparkrun run ...` command

**Diagnostics**
Try running it again with `sparkrun run <recipe> --collect-diagnostics diag.ndjson` and attaching the resulting `diag.ndjson`. (The additional `--collect-diagnostics` flag will record information about your spark, sparkrun's configuration, and debug logs during the normal `sparkrun run`. Attaching the diag.ndjson provides us with much richer context without you needing to decide how to describe the details of your setup.)

**Local/Remote**
- Please describe if you're running sparkrun locally on a spark or on a different computer (and if a different computer -- tell us if Mac/Linux/WSL)

**Additional context**
Add any other context about the problem here.

**Suggested Fix**
If you have suggestions on what to change, feel free to include them in addition to other information.
