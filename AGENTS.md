# Release maintenance

When changing core behavior (the Python engine, APIs, SDK, agent templates, policies,
contract fixtures or functional console JavaScript), create a new release after
implementation and validation. Use:

`python tools/manage_releases.py create --bump patch --title "Short release title" --change "Describe the user-visible change"`

Use a minor bump for new capabilities and a major bump for incompatible changes.
Supply the user's local date with `--date YYYY-MM-DD` when the host date differs.
Core changes require a new `VERSION`, catalog entry and immutable archive. Run
`python tools/manage_releases.py check` before reporting work complete.

Never overwrite or delete an existing version archive or invent historical
releases. Preserve existing catalog entries. Marketing copy and styling alone do
not require a core version bump. Rebuild the public release page with
`python tools/manage_releases.py render` when needed.

Stop servers, browsers and other processes you start for testing after use. The
user starts their own console manually. Do not commit, tag, push or publish to
GitHub unless the user explicitly requests it.
