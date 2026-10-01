# Security policy

Please report suspected vulnerabilities privately through GitHub's security
advisory feature rather than a public issue.

## Public repository boundary

Bibleit's source, SQL schema, Docker configuration, and `.env.example` are
intended to be public. Never commit real `.env` files, database URLs, OAuth
client secrets, email-provider keys, access tokens, database dumps, production
configuration exports, SSH host private keys, or user private keys.

Local Compose credentials are development-only and PostgreSQL is published on
`127.0.0.1`. Production deployments must use independently generated secrets,
TLS-verified database connections, restricted database/network access, and a
platform secret manager. Rotate a value immediately if it reaches Git history;
removing the line in a later commit is not sufficient.

Only SSH public keys are accepted by the dashboard. Browser cookies should be
`Secure` in production. Access tokens, session values, OAuth states, and action
codes are stored as hashes. Backups and logs can still contain sensitive user
data and must receive the same access controls as the primary database.
