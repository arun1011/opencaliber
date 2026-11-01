# Package download counts

## Activate on GitHub Pages
1. Push this code to main in the public repository. Keep the Pages source set to GitHub Actions.
2. Open GitHub Actions → **Publish download packages** → Run workflow. Choose main and a new version tag, for example `v0.6.0`.
3. The workflow tests and builds the console plus all agent ZIPs, publishes them as GitHub Release assets, records the initial count file, and triggers Pages. Wait for both workflows to succeed.
4. Pages uses release links only if the latest stable release contains every required ZIP and its checksum file. Otherwise existing static links remain usable, but uncounted.
5. Open `download-counts.json` on the repository’s `download-metrics` branch to inspect console totals, agent totals, assets and daily snapshots. There is no download-report page in the console. For programmatic access the authenticated console endpoint `/api/downloads` reads the file; a fork can set `OPENCALIBER_GITHUB_REPOSITORY=owner/repository` on the console server.

No analytics account, visitor cookie or browser tracking script is required. GitHub supplies the release asset `download_count` values. This measures downloads of the packages distributed by the site, including direct GitHub downloads. It cannot distinguish site referrals, unique people, installations, bots or repeat downloads.

## Persistent file and deployment safety

The canonical file is **`download-counts.json` on the `download-metrics` branch**. The **Record download counts** workflow refreshes it hourly or on manual request. Release publishing also updates it before triggering Pages. Its Git commit history preserves prior snapshots. This branch is independent of source and Pages deployments: never replace it with a blank file when deploying code.

Every asset is keyed by its immutable GitHub asset ID. Updates use the highest observed count and retain assets missing from later API responses. Deleting an old release does not remove previously recorded counts. A replacement asset has a new ID, so its count adds to the retained history. Do not overwrite published assets to refresh a package; publish a new version instead. API errors, invalid files and concurrent-write conflicts fail without resetting the existing file. The workflow serializes updates; a conflict can be retried.

The file stores cumulative totals, per-asset/version counters and daily cumulative snapshots. Daily values are observations, not a record of exact download times. The updater queries the latest 100 release records each run and retains counters already recorded for older releases. Downloads not observed before an asset is deleted cannot be recovered. GitHub source archives, git clones, ZIPs served directly from Pages and packages served by an internal Python server are not included.

Pages copies the latest available file into its output as `download-counts.json` during a deployment. That deployed copy is a point-in-time snapshot; the branch file remains canonical and updates independently. The console reads the branch file rather than relying on an older site deployment. Before the first snapshot exists it can show live GitHub counts, explicitly labeled as not yet persisted.

**Earlier static GitHub Pages downloads are unknown.** GitHub Pages did not provide these counters. The file keeps `legacy_pages_downloads: null`; no historic total is invented or silently reset to zero.

## File format and permissions

`version` and `repository` identify the ledger. `assets` maps numeric GitHub asset IDs to names, release tags and cumulative counts. `total_downloads`, `console_downloads`, `agent_downloads` and `daily_totals` provide aggregate views. Invalid existing ledgers are rejected rather than reinitialized.

The hourly workflow uses its short-lived GitHub Actions token with repository contents write permission to update only the counter file on the metrics branch. Release publishing also needs contents write and actions write to publish assets and dispatch Pages. The public console report uses read-only public URLs; no GitHub secret is shipped in the site or ZIPs. Production voice/model tooling, runtime evaluation history and workspace contract cases are not release assets.
