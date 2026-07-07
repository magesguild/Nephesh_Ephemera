from __future__ import annotations

import enum


class ComplianceLevel(enum.Enum):
    NON_COMPLIANT = "non_compliant"
    COMPLIANT = "compliant"
    COMPLIANT_READ_ONLY = "compliant_read_only"


class ServerMode(enum.Enum):
    NON_COMPLIANT = "non_compliant"
    COMPLIANT = "compliant"


COMPLIANCE_DESCRIPTIONS = {
    ComplianceLevel.NON_COMPLIANT: "No compliance guarantees. Not suitable for PHI, PCI, or regulated data.",
    ComplianceLevel.COMPLIANT: "Full compliance controls. Suitable for regulated data with audit trails, auth, and redaction.",
    ComplianceLevel.COMPLIANT_READ_ONLY: "Compliant read-only access. Can view regulated data but cannot mutate it.",
}

COMPLIANT_ONLY_TOOLS: set[str] = set()


def is_tool_available_in_mode(
    tool_name: str,
    tool_compliance: ComplianceLevel,
    server_mode: ServerMode,
) -> tuple[bool, str | None]:
    if server_mode == ServerMode.NON_COMPLIANT:
        if tool_compliance == ComplianceLevel.NON_COMPLIANT:
            return True, None
        return True, None
    if server_mode == ServerMode.COMPLIANT:
        if tool_compliance == ComplianceLevel.NON_COMPLIANT:
            return False, (
                f"Tool '{tool_name}' is not available in compliant mode. "
                f"It is classified as {tool_compliance.value} and may not meet regulatory requirements."
            )
        return True, None
    return False, f"Unknown server mode: {server_mode}"
