---
name: github
description: >-
  Interact with GitHub using the official GitHub CLI (gh) and Git.
  Use when the user asks to authenticate with GitHub, manage repositories,
  create or review pull requests, manage issues, trigger or view GitHub Actions,
  or create releases.
---

# GitHub & GitHub CLI (gh) Workflow Guide

This skill provides standard procedures, command patterns, and best practices for interacting with GitHub repositories, pull requests, issues, releases, and actions using the official `gh` CLI.

---

## 1. Authentication & Status

Always verify authentication before performing remote operations:

```bash
# Check current authentication status
gh auth status

# Login to GitHub (interactive or browser)
gh auth login

# Refresh authentication token if expired
gh auth refresh -s repo,workflow,read:org
```

---

## 2. Repository Operations

### View & Clone
```bash
# View current repository details on GitHub
gh repo view

# View repository in browser
gh repo view --web

# Clone a repository
gh repo clone <owner>/<repo>

# Fork repository
gh repo fork --clone=true
```

### Create & Manage Remote
```bash
# Create a new repository on GitHub and push existing local repo
gh repo create <repo-name> --public --source=. --remote=origin --push

# Create a private repository
gh repo create <repo-name> --private --source=. --remote=origin --push
```

---

## 3. Branching & Pull Requests (PR)

### Create & Submit PR
```bash
# 1. Create a feature branch
git checkout -b feature/<feature-name>

# 2. Stage and commit changes
git add .
git commit -m "feat: description of changes"

# 3. Push branch to remote
git push -u origin feature/<feature-name>

# 4. Create Pull Request
gh pr create --title "feat: descriptive PR title" --body "Summary of changes made."

# 5. Open PR in browser
gh pr view --web
```

### Review & Merge PR
```bash
# List open Pull Requests
gh pr list

# Check status of PRs related to current branch
gh pr status

# View PR diff
gh pr diff <pr-number>

# Checkout a PR locally for testing
gh pr checkout <pr-number>

# Merge a PR (squash or rebase)
gh pr merge <pr-number> --squash --delete-branch
```

---

## 4. Issue Management

```bash
# List open issues
gh issue list

# Create a new issue
gh issue create --title "Bug: title" --body "Description of the issue"

# View an issue
gh issue view <issue-number>

# Close an issue
gh issue close <issue-number> --comment "Fixed in commit XYZ"
```

---

## 5. Releases & GitHub Actions

### Releases
```bash
# List releases
gh release list

# Create a new release with assets
gh release create v1.0.0 --title "Release v1.0.0" --notes "Release notes summary"
```

### GitHub Actions Workflows
```bash
# List recent workflow runs
gh run list

# View details of a specific workflow run
gh run view <run-id>

# Watch live logs of a running workflow
gh run watch <run-id>

# Trigger a manual workflow dispatch
gh workflow run <workflow-name.yml>
```
