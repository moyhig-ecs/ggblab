# Security policy

## Reporting a vulnerability

Report it privately through GitHub's Security Advisories for this repository ("Report a vulnerability" under the
Security tab). Please do not open a public issue for it. Include the version, the host (Python or Julia), and the
smallest input that shows the behaviour.

Expect an acknowledgement within 7 days and, for a confirmed report, a fix or a written plan within 30 days. Fixes are
listed under **Security** in `CHANGELOG.md`.

## Supported versions

| Version            | Supported |
| ------------------ | --------- |
| 2.0.0rc4 and later | yes       |
| 2.0.0rc1 – rc3     | no (upgrade) |
| 1.x                | no (frozen) |

## Deployment assumption

ggblab's relay runs inside a **single-user** Jupyter server (a laptop, or one user's server under JupyterHub). Every
handler requires the server's login (`@web.authenticated`), and that login is the boundary: whoever is logged in to the
server can reach every box on it.

Known limitation: the relay does not check which user or document owns a box (`mount`). On a server shared by several
users (real-time collaboration, a shared single-process server) one user can read and drive another's box. Do not run
ggblab on such a server. See `docs/security.md`.
