# Regression fixtures

`connector-preview-worker.txt` is the exact, unmodified Sites 1.1.7 starter bridge
from the MIT PetMCP runtime at:
https://github.com/smallgreen-cloud/petmcp-sites/blob/ed20ee8fbda440a7f1b44007528394b726ae4f62/worker/index.ts

Its license is retained in `connector-preview-worker.LICENSE`. The narrow CON-3
exception checks the entire file's SHA-256, path and valid Sites declarations.
Tests remove the DEV guard and add a runtime reference elsewhere to prove that
the exception cannot become a global CONNECTORS allowlist. Review any changed
starter source and its actual production/dev boundary before accepting a new
fingerprint.

Temporary fixture accounts, names and declarations are synthetic. No test
creates a hosted Site or independent Cloudflare resources.
