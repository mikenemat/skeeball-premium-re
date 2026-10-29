# Software contribution instructions

Read README.md before changing these tools. Keep contributions limited to
reviewed generic utilities, synthetic fixtures, and public documentation.
Do not add user inputs, generated reports, local paths, or workspace handoffs.

Run `python tools/check_public_tree.py --worktree` before preparing a commit.
Review the actual content of every staged file: the guard checks paths and types,
not privacy, provenance, or licensing. Never bypass the publication guard or
force-add ignored files. Review additions to public-files.txt deliberately.

For owner-authorized local work, follow internal/AGENTS.md when it exists.
