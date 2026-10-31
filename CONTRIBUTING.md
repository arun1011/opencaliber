# Contributing

Open an issue describing the problem and a reproducible synthetic example before proposing a substantial change. Do not submit credentials, private traces, customer data or employer-owned code without permission.

For a pull request, explain the behavior change and run `python -m unittest discover -s tests -v`, `python -m unittest discover -s examples/database_summary -v` and `node --test tests/test_node_sdk.mjs` after installing requirements-dev.txt. Add regression cases for changed evaluation behavior. Keep risk scores described as heuristic severity, not probability. Document unsupported scenarios and avoid claims of comprehensive protection.

By intentionally submitting a contribution, you provide it under the Apache License 2.0 terms in LICENSE and confirm you have permission to contribute it. Retain applicable third-party notices.
