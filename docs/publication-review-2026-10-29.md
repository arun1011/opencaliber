# Pre-publication review — 29 October 2026

## Conclusion

No confirmed infringement or exposed credential was identified by this limited technical review. This is not legal clearance, a penetration test, a trademark search, or a guarantee that no secrets or defects exist. Media ownership and employer/IP permissions cannot be established from source code alone.

## Confirmed inconsistencies corrected

- Agents Library still said no distribution license was selected. Changed it to Apache-2.0 and retained third-party scope guidance.
- LOCAL_TOOL.md repeated the old license restriction, which propagated into generated runtime README files. Corrected it and regenerated packages.
- LOCAL_TOOL.md still attributed narration to Microsoft Zira. Corrected it to Microsoft David.
- README's no-key / standard-library statement was too broad for optional live agent starters and hosted deployment. Scoped it to the evaluator and desktop console, with provider charges and hosted dependencies stated explicitly.

These edits were applied to both the original workspace and the public repository copy. Nothing was pushed.

## Matters requiring owner confirmation

1. Walkthrough audio: generated with the installed Windows Microsoft David Desktop voice. No specific license granting public redistribution of this generated audio is documented in the repository. This is an unresolved permission check, not a finding of infringement. Confirm the applicable voice/Windows terms or replace narration with your own recording or a service with explicit output rights. Apache-2.0 on the software does not establish voice-media rights.
2. Logo: SVG artwork originated from another folder supplied by the owner. Confirm ownership or permission to reuse it. A supplied path is not evidence of ownership. No trademark clearance for OpenCaliber was performed.
3. Retained-volume bootstrap: deploy/bootstrap.py explicitly records adaptation from Impact Studio. Confirm you own that source or have permission and retain any required upstream notices. The current repository does not document the original project's license. Do not simply remove provenance to hide reuse.
4. Personal project: the README states independent personal-project status. Employer policies, assignment clauses and outside-work requirements were not available and were not reviewed. A disclaimer cannot override those terms.

## Technical evidence

- Scanned 93 reachable Git-history blobs for selected credential/private-key patterns; no matches. This covers local refs, not every possible remote-only/deleted ref, arbitrary secret format, or image/video content.
- Reviewed tracked paths; no .env credentials, databases, model weights, private trace history or Windows font binaries were tracked.
- Queried OSV for the three pinned runtime dependencies and all 24 packages resolved by a dry-run of requirements-dev.txt on the current Windows/Python environment: no advisories returned at review time. Nothing was installed by that resolution. Linux resolution, already deployed environments and future versions can differ.
- Dependency metadata includes MIT, BSD, Apache, PSF, python-dateutil dual-license and certifi MPL-2.0. No obvious conflict was identified for separately installed dependencies. Preserve upstream terms and notices if redistributing dependencies; this is not a complete transitive source/license audit.
- Passed 78 engine tests, 12 hosted boundary/deployment tests, 14 adoption tests, 13 desktop API tests, 2 Pages builder tests and 6 Node SDK tests. The complete agent-library test suite, paid provider calls and AWS deployment were not rerun.
- Static Pages tests check both domain-root and /opencaliber/ paths and downloadable packages. Desktop and hosted runtime remain distinct.
- Rule scores are heuristic severity, not anomaly probabilities. The 70 synthetic scenarios are regression contracts, not independent security-effectiveness evidence. The 64 agent packs share a bounded starter runtime and are not 64 independently validated autonomous systems.

## Suggested public description

“OpenCaliber is my independent open-source evaluation toolkit for AI agent action traces. It applies configurable rules, links findings to agent actions, and includes synthetic regression scenarios and provider integration examples. It is an advisory developer tool; it does not guarantee safety or automatically contain agents.”

Avoid describing this release as a trained fraud model, comprehensive security product, certified system, or validated research benchmark.

## References

- Apache license: https://www.apache.org/licenses/LICENSE-2.0
- OSV vulnerability API: https://api.osv.dev/v1/querybatch
- FastAPI license: https://github.com/fastapi/fastapi/blob/master/LICENSE
- Uvicorn license: https://github.com/encode/uvicorn/blob/main/LICENSE.md
- Boto3 license: https://github.com/boto/boto3/blob/develop/LICENSE
