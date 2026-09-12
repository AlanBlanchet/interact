"""Export the public account contracts as deterministic JSON Schema."""

import json
from typing import Union

from pydantic import TypeAdapter

from interact_core import (
    Account,
    AccountUpdate,
    Bootstrap,
    LoginRequest,
    PasswordResetRequest,
    PlatformError,
    RecoveryRequest,
    SignupRequest,
    TokenRequest,
    Workspace,
    WorkspaceCreate,
    WorkspaceInvitation,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMembership,
    WorkspaceMemberRoleUpdate,
    WorkspaceUpdate,
)


def main() -> None:
    contract = Union[
        Account, AccountUpdate, Bootstrap, SignupRequest, LoginRequest, TokenRequest,
        RecoveryRequest, PasswordResetRequest, PlatformError, Workspace, WorkspaceCreate, WorkspaceInvitation,
        WorkspaceInvite, WorkspaceMember, WorkspaceMembership, WorkspaceMemberRoleUpdate, WorkspaceUpdate,
    ]
    print(json.dumps(TypeAdapter(contract).json_schema(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
