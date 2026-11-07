# Release notes - Azure Database for PostgreSQL flexible server

Fixture: excerpt of the page as returned by the Learn MCP microsoft_docs_fetch tool.

## Release: October 2026

- Preview
    - [System metrics](../monitor/concepts-monitoring#system-metrics-preview), starting with the CPU limit monitoring metric (`cpu_limit`), are now available.

## Release: August 2026

- General availability
    - Support for latest [minor versions](../configure-maintain/concepts-supported-versions) 18.6, 17.11, 16.15, 15.19, and 14.24. ^$^
    - [Pre-upgrade validation checks](../configure-maintain/concepts-major-version-upgrade#upgrade-validation-checks) to identify upgrade-blocking problems before starting a major version upgrade.

## Release: June 2026

- General availability

    - [Microsoft Defender Cloud Security Posture Management (CSPM) assessments in Azure Database for PostgreSQL](../security/security-defender-for-cloud#microsoft-defender-for-cloud-security-posture-management-cspm-assessments)
    - Support for view [upcoming maintenance](../configure-maintain/concepts-maintenance#view-upcoming-maintenance)
- Preview

    - [Pre-upgrade validation checks](../configure-maintain/concepts-major-version-upgrade#upgrade-validation-checks) to help identify upgrade-blocking problems before starting the upgrade.

## Release: June 2025

- General availability
    - [Indonesia Central](../overview#azure-regions) region.
    - [Postgis extension](../extensions/concepts-extensions-versions#postgis) version 3.5.2 for PG 13 and above.
- Support for [Ansible collection](https://galaxy.ansible.com/ui/repo/published/azure/azcollection/content/?version=3.6.0) with [API release notes - Azure Database for PostgreSQL](release-notes-api) version.

## Release: April 2025

- Public preview of [Fabric Mirroring](https://techcommunity.microsoft.com/blog/adforpostgresql/announcing-mirroring/4396750) for Azure Database for PostgreSQL.
- Public preview of [Model Context Protocol (MCP) Server](https://techcommunity.microsoft.com/blog/adforpostgresql/introducing-mcp/4404360) for Azure Database for PostgreSQL.

## Release: November 2024

- [Azure Database for PostgreSQL version policy](../configure-maintain/concepts-version-policy) retires on November 14, 2024. Upgrade to a supported version before retirement to ensure continued support and security.

## Release: Aug 2024

- General availability: [postgres_protobuf](../extensions/concepts-extensions-versions#postgres_protobuf) extension.

## Release: May 2024

- Support for the following [extensions](../extensions/how-to-allow-extensions):
    - [TimescaleDB (ver 2.13.0) for PG16](../extensions/concepts-extensions-versions#timescaledb).
    - [login_hook](../extensions/concepts-extensions-versions#login_hook).

## Release: October 2020 - March 2021

- Support for [new regions](../overview#azure-regions).

Important

Features marked with a **$** are automatically available for newly created PostgreSQL servers.

## Contacts

- To contact Azure Support, [file a ticket from the Azure portal](https://portal.azure.com/?#blade/Microsoft_Azure_Support/HelpAndSupportBlade).
