"""Workspace records through the existing authenticated catalog session."""

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from interact_core import AgentGraph, AgentGraphUpdate, AgentRevision, AgentRevisionRef, CompanyProfile, ConfiguredModelRef, ReleaseInfo, TriggerInvocation, WorkflowRevision, WorkflowRevisionRef, WorkflowRun
from interact_core.accounts import Bootstrap
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from interact.agents.catalog import CatalogSnapshot
from interact.agents.catalog_connection import CatalogAuthenticationError, CatalogConnection, CatalogConnectionError
from interact.criteria import Criteria
from interact.server_prompts import ServerPrompts


class WorkspaceConflictError(CatalogConnectionError):
    """The displayed graph is no longer current; keep the unsaved draft."""


class WorkflowConflictError(CatalogConnectionError):
    """The selected workflow revision changed before execution."""


class WorkflowRunRejected(CatalogConnectionError):
    """This attempt was rejected before dispatch; prior attempts remain independent."""


class WorkflowRunUncertain(CatalogConnectionError):
    """A request may have reached execution; inspect it using the retained key."""


class WorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workflow: WorkflowRevisionRef
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    invocation: TriggerInvocation = Field(default_factory=TriggerInvocation)


class AgentEdit(BaseModel):
    """Only editable fields, with omitted fields preserving server values."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reports_to: UUID | None = None
    criteria: str | None = None
    criteria_weights: str = ""
    reasoning: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    model: ConfiguredModelRef | None = None

    def apply(self, current: AgentRevision):
        changes = self.model_dump(exclude_unset=True)
        if "criteria" in changes and self.criteria:
            Criteria.parse(self.criteria)
        if "criteria_weights" in changes:
            Criteria.validate_weights(self.criteria_weights)
        return AgentRevision.model_validate({
            **current.model_dump(), **changes, "revision": uuid4(),
            "parent_revision": current.revision, "created_at": datetime.now(UTC),
        })


class ServerWorkspace(ServerPrompts):
    """No separate credentials, offline authoring, or caller-selected HTTP paths."""

    @classmethod
    def configured(cls):
        connection = CatalogConnection.load()
        if connection is None:
            raise CatalogConnectionError("No server workspace configured. Use interact agents sync to connect.")
        return cls(connection=connection)

    @property
    def workspace_endpoint(self):
        if self.connection.workspace_id is None:
            raise CatalogConnectionError("Select a server workspace first.")
        return f"/v1/workspaces/{self.connection.workspace_id}"

    def read_record(self, suffix: Literal["agent-graph", "agent-catalog", "workflows", "company", "version", "models"], schema, *, transport=None):
        path = "/v1/version" if suffix == "version" else f"{self.workspace_endpoint}/{suffix}"
        with self.session(transport=transport) as client:
            payload = self.connection.request(client, "GET", path)
            try:
                return TypeAdapter(schema).validate_json(payload)
            except ValueError as error:
                raise CatalogConnectionError(f"Invalid server {suffix} response.") from error

    def graph(self, *, transport=None):
        return self.read_record("agent-graph", AgentGraph, transport=transport)

    def agent_catalog(self, *, transport=None):
        return self.read_record("agent-catalog", CatalogSnapshot, transport=transport)

    def workflows(self, *, transport=None):
        return self.read_record("workflows", tuple[WorkflowRevision, ...], transport=transport)

    def company(self, *, transport=None):
        return self.read_record("company", CompanyProfile, transport=transport)

    def version(self, *, transport=None):
        return self.read_record("version", ReleaseInfo, transport=transport)

    def models(self, *, transport=None):
        return self.read_record("models", tuple[ConfiguredModelRef, ...], transport=transport)

    def can_edit(self, *, transport=None):
        if self.connection.auth_mode == "token":
            return False
        with self.session(transport=transport) as client:
            bootstrap = Bootstrap.model_validate_json(self.connection.request(client, "GET", "/v1/bootstrap"))
            return any(workspace.workspace_id == self.connection.workspace_id and workspace.role != "viewer" for workspace in bootstrap.workspaces)

    def agent_revision(self, reference: AgentRevisionRef, *, transport=None):
        with self.session(transport=transport) as client:
            payload = self.connection.request(client, "GET", f"{self.workspace_endpoint}/agents/{reference.id}/revisions/{reference.revision}")
            value = AgentRevision.model_validate_json(payload)
            if value.id != reference.id or value.revision != reference.revision:
                raise CatalogConnectionError("Server returned a different agent revision.")
            return value

    def workflow_history(self, workflow_id: UUID, *, transport=None):
        with self.session(transport=transport) as client:
            payload = self.connection.request(client, "GET", f"{self.workspace_endpoint}/workflows/{workflow_id}/runs")
            values = TypeAdapter(tuple[WorkflowRun, ...]).validate_json(payload)
            if any(value.workflow.key.id != workflow_id for value in values):
                raise CatalogConnectionError("Server returned another workflow's history.")
            return values

    def workflow_status(self, workflow_id: UUID, idempotency_key: str, *, transport=None):
        return next((run for run in self.workflow_history(workflow_id, transport=transport) if run.idempotency_key == idempotency_key), None)

    def run_workflow(self, request: WorkflowRunRequest, *, transport=None):
        """Execute only the displayed revision; retain the same key after uncertain delivery."""
        with self.session(transport=transport) as client:
            headers = {"Content-Type": "application/json", "If-Match": f'"{request.workflow.revision}"',
                       "Idempotency-Key": request.idempotency_key}
            if self.connection.auth_mode == "preview":
                bootstrap = Bootstrap.model_validate_json(self.connection.request(client, "GET", "/v1/bootstrap"))
                if not any(workspace.workspace_id == self.connection.workspace_id and workspace.role != "viewer" for workspace in bootstrap.workspaces):
                    raise CatalogAuthenticationError("Workspace execution permission is required; request retained.")
                headers["x-csrf-token"] = bootstrap.csrf_token
            # Token execution uses only existing server-granted scope. No credential grant or
            # local execute entitlement: the endpoint authorizes every invocation.
            try:
                with client.stream("POST", f"{self.workspace_endpoint}/workflows/{request.workflow.key.id}/runs",
                                   content=request.invocation.model_dump_json(), headers=headers) as response:
                    if response.status_code in {401, 403, 404}:
                        self.connection.invalidate_access(client)
                        raise CatalogAuthenticationError(f"Workflow execution refused (HTTP {response.status_code}); request retained. Existing execute permission is required.")
                    if response.status_code == 409:
                        raise WorkflowConflictError("Selected workflow revision changed; nothing dispatched by this request. Reload workflows and review the new revision.")
                    if response.status_code in (400, 413):
                        raise WorkflowRunRejected("Workflow inputs rejected before dispatch. Correct input names and values, choose New execution, then submit explicitly.")
                    if response.status_code >= 500:
                        raise WorkflowRunUncertain("Server execution response failed. Check execution status with the same request key before retrying.")
                    if not 200 <= response.status_code < 300:
                        raise CatalogConnectionError(f"Workflow request rejected (HTTP {response.status_code}); inputs and request key retained.")
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 16 << 20:
                            raise WorkflowRunUncertain("Run response exceeds the limit. Check execution status with the same request key.")
            except httpx.HTTPError as error:
                raise WorkflowRunUncertain("Execution response unavailable; work may still be running. Check status with the same request key; do not create another execution.") from error
            try:
                run = WorkflowRun.model_validate_json(payload)
            except ValueError as error:
                raise WorkflowRunUncertain("Invalid execution response. Check status with the same request key.") from error
            if run.workflow != request.workflow or run.idempotency_key != request.idempotency_key or run.invocation != request.invocation:
                raise WorkflowRunUncertain("Execution response differs from the selected revision or inputs. Check status with the same request key.")
            return run

    def link(self, view: Literal["agents", "workflows", "company", "personal", "connections", "prompts", "version", "assistant"], identity: UUID | None = None):
        query = urlencode({"agent" if view == "agents" else "workflow": str(identity)}) if identity and view in {"agents", "workflows"} else ""
        return f"{self.connection.endpoint.rstrip('/')}/#{view}{'?' + query if query else ''}"

    def save_graph(self, update: AgentGraphUpdate, *, transport=None):
        if self.connection.auth_mode == "token":
            raise CatalogAuthenticationError("This connection is read-only. Edit in the signed-in server workspace; draft retained.")
        with self.session(transport=transport) as client:
            bootstrap = Bootstrap.model_validate_json(self.connection.request(client, "GET", "/v1/bootstrap"))
            if not any(workspace.workspace_id == self.connection.workspace_id and workspace.role != "viewer" for workspace in bootstrap.workspaces):
                raise CatalogAuthenticationError("Workspace edit permission is required; draft retained.")
            with client.stream("PUT", f"{self.workspace_endpoint}/agent-graph",
                               content=update.model_dump_json(exclude_unset=True),
                               headers={"Content-Type": "application/json", "x-csrf-token": bootstrap.csrf_token}) as response:
                if response.status_code in {401, 403, 404}:
                    self.connection.invalidate_access(client)
                    raise CatalogAuthenticationError(f"Server edit refused (HTTP {response.status_code}). Sign in with workspace edit permission; draft retained.")
                if response.status_code == 409:
                    raise WorkspaceConflictError("Server graph changed. Draft retained; reload current graph before retrying.")
                if not 200 <= response.status_code < 300:
                    raise CatalogConnectionError(f"Server rejected graph (HTTP {response.status_code}); draft retained. Check parent, criteria and provider capabilities.")
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 16 << 20:
                        raise CatalogConnectionError("Server graph exceeds response limit; refresh to verify save.")
            try:
                saved = AgentGraph.model_validate_json(payload)
            except ValueError as error:
                raise CatalogConnectionError("Invalid saved graph; draft retained. Refresh to verify save.") from error
            heads = {agent.id: agent for agent in saved.agents}
            for proposed in update.agents:
                actual = heads.get(proposed.id)
                if actual is None or any(getattr(actual, field) != getattr(proposed, field) for field in AgentEdit.model_fields):
                    raise CatalogConnectionError("Save response differs from requested agent edit; draft retained. Refresh to verify save.")
            if "root_agent" in update.model_fields_set and (saved.root_agent.id if saved.root_agent else None) != update.root_agent:
                raise CatalogConnectionError("Save response differs from requested Assistant root; draft retained.")
            return saved

    def edit_agent(self, graph: AgentGraph, agent_id: UUID, edit: AgentEdit, *, transport=None):
        current = next((agent for agent in graph.agents if agent.id == agent_id), None)
        if current is None:
            raise ValueError("Agent is absent from the displayed graph.")
        changed = edit.apply(current)
        return self.save_graph(AgentGraphUpdate(expected_revision=graph.revision, agents=(changed,)), transport=transport)

    def set_root(self, graph: AgentGraph, agent_id: UUID | None, *, transport=None):
        changed = ()
        if agent_id is not None:
            current = next((agent for agent in graph.agents if agent.id == agent_id), None)
            if current is None:
                raise ValueError("Root is absent from the displayed graph.")
            if current.reports_to is not None:
                changed = (AgentEdit(reports_to=None).apply(current),)
        return self.save_graph(AgentGraphUpdate(expected_revision=graph.revision, root_agent=agent_id, agents=changed), transport=transport)
