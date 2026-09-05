/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * One typed, cursor-addressed delta from the prompt catalogue.
 */
export interface PromptCatalogPage {
  entries: PromptChannelEntry[];
  removed?: PromptKey[];
  cursor?: string | null;
  server_timestamp: string;
}
/**
 * Compare-and-swap channel pointer to one immutable prompt revision.
 */
export interface PromptChannelEntry {
  key: PromptKey;
  channel: string;
  revision: string;
  digest: string;
  lock_version: number;
}
/**
 * Stable prompt identity independent of revisions and publication channels.
 */
export interface PromptKey {
  namespace: string;
  slug: string;
}
/**
 * Server-verified immutable prompt identity persisted with one execution.
 */
export interface PromptExecutionRef {
  key: PromptKey;
  channel: string;
  digest: string;
  revision: string;
}
/**
 * One complete exact-commit prompt snapshot applied by global cursor CAS.
 */
export interface PromptPublicationRequest {
  expected_cursor?: string | null;
  source_commit: string;
  entries: PromptSelection[];
  revisions: PromptRevision[];
}
/**
 * Untrusted channel and digest requested for server-backed resolution.
 */
export interface PromptSelection {
  key: PromptKey;
  channel: string;
  digest: string;
}
/**
 * Immutable prompt content and its verifiable publication provenance.
 */
export interface PromptRevision {
  key: PromptKey;
  revision: string;
  parent_digest?: string | null;
  digest: string;
  content: string;
  source_commit: string;
  created_at: string;
}
