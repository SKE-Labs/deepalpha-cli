---
name: env_local
version: "1.0"
description: Environment context for local mode — working directory and path requirements
---

# Environment Context

**Working Directory:** `{cwd}`

**Path Requirements:**
- All file paths must be absolute (e.g., `{cwd}/analysis.py`)
- Use the working directory to construct absolute paths
- Never use relative paths - always construct full absolute paths
