"""Export workflow contracts as deterministic JSON Schema."""

import json
from typing import Union

from pydantic import TypeAdapter

from interact_core import (
    ModelCriteriaCatalog,
    ModelEligibility,
    WorkflowBlockAvailability,
    AdminWorkspaceSummary,
    DelegatedAgentTool,
    AgentCatalogSnapshot,
    AgentRevision,
    BudgetPolicy,
    ConnectionResource,
    ConnectionSecretUpdate,
    Conversation,
    ConversationActivity,
    ConversationCreateRequest,
    HttpAgentTool,
    SubscriptionConfiguration,
    TriggerCreate,
    TriggerDefinition,
    TriggerDispatch,
    TriggerEnableUpdate,
    TriggerInputMapping,
    TriggerInvocation,
    TriggerScheduleState,
    WebhookCredentialCreated,
    WebhookCredentialSummary,
    WorkspaceApiKeyCreate,
    WorkspaceApiKeyCreated,
    WorkspaceApiKeySummary,
    WorkflowEvent,
    WorkflowAgentActivity,
    WorkflowCapabilityActivity,
    WorkflowRevision,
    WorkflowValueSummary,
    WorkflowRun,
    UsageSummary,
)


def main() -> None:
    contracts = Union[
        ModelCriteriaCatalog,
    ModelEligibility,
        WorkflowBlockAvailability,
        WorkspaceApiKeyCreate,
        WorkspaceApiKeyCreated,
        WorkspaceApiKeySummary,
        TriggerCreate,
        TriggerDefinition,
        TriggerDispatch,
        TriggerEnableUpdate,
        TriggerInputMapping,
        TriggerInvocation,
        TriggerScheduleState,
        WebhookCredentialCreated,
        WebhookCredentialSummary,
        SubscriptionConfiguration,
        AdminWorkspaceSummary,
        WorkflowAgentActivity,
        WorkflowCapabilityActivity,
        WorkflowValueSummary,
        HttpAgentTool,
        DelegatedAgentTool,
        WorkflowRevision,
        ConnectionResource,
        ConnectionSecretUpdate,
        AgentCatalogSnapshot,
        AgentRevision,
        ConversationCreateRequest,
        Conversation,
        ConversationActivity,
        BudgetPolicy,
        UsageSummary,
        WorkflowRun,
        WorkflowEvent,
    ]
    print(json.dumps(TypeAdapter(contracts).json_schema(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
