# Security policy

## Supported versions

Security fixes target the latest commit on `main`. Older commits and forks do
not receive separate security maintenance. Update to the latest `main` before
checking whether an issue still occurs.

## Reporting a vulnerability

Please keep vulnerability details out of public issues, pull requests, and
discussions.

1. Open the repository's [Security tab](https://github.com/destinesia7187/dataset-check/security).
   If **Report a vulnerability** is available, use it to submit a private report.
2. If private reporting is unavailable, open a
   [contact-only issue](https://github.com/destinesia7187/dataset-check/issues/new?title=Private%20security%20contact%20request)
   titled **Private security contact request**. Include only a request for a
   private communication channel. Share technical details after a private
   channel has been established.

A useful private report includes:

- The affected commit, operating system, browser, and launch method.
- A description of the impact and the conditions required to trigger it.
- Reproduction steps and the expected and actual behavior.
- A minimal synthetic CSV or proof of concept, where relevant.

Remove credentials, personal information, and real datasets from reports.
Allow time to investigate and agree on a fix and disclosure before publishing
exploit details. This project does not provide a guaranteed response timeline
or a paid bug bounty.

## Deployment and data handling

- Dataset Check is designed for one user on their own computer. Bind the server
  to `127.0.0.1` and keep Docker's loopback-only port mapping. The MVP provides
  no authentication, multi-user isolation, or application-level encryption.
- `DATA_DIR` contains source files, raw values, reports, and request metadata.
  Restrict access using operating-system permissions. Idle-retention cleanup
  and ordinary deletion do not securely erase files or remove downloaded
  reports and backups.
- Host, Origin, and custom-header checks protect the local HTTP interface.
  Separate worker processes, deadlines, and storage limits bound processing;
  workers are not an operating-system security sandbox.
- CSV exports escape formula-like values for spreadsheet viewing. JSON exports
  preserve original strings: treat them as data, never as executable code or
  spreadsheet formulas.

See the [README](README.md) for the supported launch configuration, limits, and
recovery behavior.
