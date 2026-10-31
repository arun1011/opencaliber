# Repository layout

This guide maps the source files needed to run, integrate and extend OpenCaliber.

| Area | Purpose |
|---|---|
| opencaliber/ | Evaluation engine, adapters, SDK, desktop API and hosted API |
| web/ | Console, public website, agent catalog and finished walkthrough |
| sdk/ and examples/ | Integration code and runnable traces |
| agent_templates/ | Source for downloadable agent starter packages |
| data/agent_cases.json and tests/ | Synthetic contracts and regression checks |
| tools/ | Reproducible case/package/site builders and deployment validation |
| .github/workflows/pages.yml | GitHub Pages static-site deployment |
| application.py, Procfile, .ebextensions/, .platform/, deploy/ | Elastic Beanstalk service deployment |
| docs/ | User, integration and deployment documentation |
| artifacts/ and dist/ | Ignored runtime data and generated build outputs; never commit |

GitHub Pages hosts the public website, downloads and console setup instructions. It does not run Python evaluation APIs. Elastic Beanstalk hosts the Python service with its configured authentication and storage.

Use docs/github-pages.md for Pages and docs/elastic-beanstalk.md for AWS. Agent pack generation and the console ZIP build use only the Python standard library. Optional hosted runtime dependencies are in requirements.txt; development checks use requirements-dev.txt.
