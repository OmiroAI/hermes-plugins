# Scoped collaborator Drive

An opt-in native plugin plus a standalone **required gateway admission command**.
Google policy and a fresh bounded worker live here; Hermes core knows only the
versioned command protocol. The plugin never edits Hermes source. It is a reference
implementation for one owner's agent, **not a multi-tenant security sandbox**.

This package requires the companion core change in
[OmiroAI/hermes-agent, feature/required-gateway-policy](https://github.com/OmiroAI/hermes-agent/tree/feature/required-gateway-policy).
Its generic interface is documented in `website/docs/developer-guide/gateway-admission-policy.md`
in that branch. Stock Hermes versions without it must not be activated with
collaborators. Ordinary optional hooks do not provide the same required-command
failure semantics. An upstream release is not required: build the pinned fork
commit with its own Dockerfile, then install this separately pinned package.

## Installation and configuration

Install into a **separate worker virtual environment**, not Hermes's managed
runtime. For example, from a reviewed checkout of this repository:

```sh
python3 -m venv /opt/collaborator-worker
/opt/collaborator-worker/bin/pip install ./plugins/scoped-collaborator-drive
install -d -m 0700 /var/lib/collaborator-drive
```

These are example operator paths; choose paths appropriate to your installation.
The worker needs Google Application Default Credentials with Drive and Documents
scopes (`google.auth.default`), and `OPENAI_API_KEY` for an OpenAI-compatible model.
An optional `base_url` in worker.json selects another compatible endpoint. Provision
credentials outside chat and the public source tree. Drive Activity API/scope is
**not required** for the standing project/current-access rule. Google APIs and the
model provider receive the data needed for the requested work; obtain the owner's
approval for those providers. No telemetry is sent elsewhere.

Copy and customize [registry.json](examples/registry.json) and
[worker.json](examples/worker.json). The example is deliberately paused and revoked.
Keep the registry, policy command, worker configuration and core configuration
operator-controlled and outside collaborator/agent-writable locations; mount the
registry read-only in containers. Mode checks reject group/world-writable registry
files but cannot prove founder identity or prevent a same-UID owner modifying them.
A credential broker or separate OS identity/container is required for a real
adversarial boundary; the reference worker's SDK credentials may have broader
access than the operations the application exposes.

In the **owning profile's** Hermes config.yaml:

```yaml
gateway:
  admission_policy:
    command:
      - /opt/collaborator-worker/bin/collaborator-drive-gate
      - --registry
      - /etc/collaborator-drive/registry.json
      - --worker-config
      - /etc/collaborator-drive/worker.json
      - --state-dir
      - /var/lib/collaborator-drive
    timeout_seconds: 600
```

For optional native CLI discovery, install this plugin directory with Hermes's
normal native plugin installer, enable `scoped-collaborator-drive`, then run
`hermes collaborator-check /etc/collaborator-drive/registry.json`. This validates
structure only. The required command is independent of optional plugin loading:
disabling or failing to load a native plugin cannot remove a configured gate.
Do not configure both an older private ingress patch and this gate concurrently.

Before activation, run the tests below and verify your installed image's real
entry points, normalized identities, routing, credential visibility and live API
responses. Validate founder mappings out of band. Only the operator applying a
verified founder's approval sets registry `activation: active` and grants' `status:
active`. There is no model or chat-accessible registry writer. A malformed registry,
missing command, checker exception or timeout consumes the input and pauses; it
never falls through to the ordinary privileged agent. Missing model configuration
can also pause founder passthrough because the command cannot initialize.

## Registry and request contract

There is **one registry** containing founder identities, trusted internal chat IDs
and collaborator grants. Each grant records platform + stable user ID, Google
email, venture, approved project folder IDs, allowed actions, exclusions, approving
founder, approval source and active/revoked status. `task_approvals` preserves prior
specific approvals as provenance when migrating an old record; it does not bypass
current permission checks. Remove the old authorization record after migration.
No person's identity is embedded in code, SOUL or a skill.

`resource_scope: venture_current_access` means descendants of approved project
roots **AND** a current exact-target user ACL for the registered Google email.
Sharing by any current project editor qualifies; no per-share actor attribution or
per-task folder list is required. Only verified founders may change identities,
venture roots, actions, exclusions or status. Folder IDs still establish a finite
venture boundary; arbitrary items shared elsewhere do not qualify.

Founder accounts bypass only in private chats or exact trusted internal chat
platform/ID pairs. All external groups, including messages from founders, use the
restricted path. General gateway allowlists and group administrator status alone
are not founder proof. Unknown identities and missing/ambiguous grants pause.

The worker binds one immutable transport identity and venture for the request.
With one active venture the user sends normal text including Drive links/IDs.
With several grants the request is explicit:

```json
{"venture":"example-venture","request":"Review document DOCUMENT_ID and create a draft in FOLDER_ID."}
```

The model receives no founder prompt, SOUL, history, memory, MCP, shell, browser,
plugins or delegation tools. Its only tool dispatches `inspect`, `list_folder`, `read_text`, `transcribe`,
`create_draft` and `replace_doc`. Source access is rechecked before delivery and
mutation. Replacement requires a fresh revision and plain Google Doc body; every
write requires exact text readback. A durable per-message attempt marker permits
one write and prevents blind retries after an ambiguous API result or timeout.
Operators inspect any attempted mutation before starting a new request. State
must persist across restarts; don't auto-clean attempt markers. Sender locks
serialize local concurrent requests. Groups receive only generic status or
verified draft links; direct messages may receive scoped results.

## SOUL and venture skills

Merge [the generic SOUL section](examples/SOUL.md) into the agent's existing SOUL;
preserve its default confidentiality. A venture skill should say: use only the
single registry and required scoped worker, stay in the current approved venture,
pause unsupported operations, preserve task-specific provenance there, and never
copy authorization identities or grants into the skill. These are instructions;
identity, action, ancestry, ACL and dispatch checks are code.

## Supported evidence and limitations

The Google adapter conservatively supports My Drive ancestry and an exact-target
user ACL, including available inherited user entries. Reader access permits reads;
writer/owner is needed for existing edits and draft destinations. The
agent account's capabilities never establish the collaborator's access. Expired,
deleted, published-view-only and uncertain permissions pause. Shared drives,
shortcuts, group/domain/link-only access, limited-access ancestry without direct
permission evidence, encryption and download restrictions pause. Broad or
published write audiences pause to avoid implicit publication. A current ACL check
using the agent's credential is **not collaborator impersonation** and cannot prove
all contextual Google restrictions; check/use are separate non-atomic requests.

This public adapter reads/edits plain Google Docs and lists up to 100 verified
children. Optional local transcription downloads at most 200 MB and processes the
first 15 minutes. Configure `transcriber_command` as an operator-owned argv list in
worker.json; it receives one local WAV path and must emit exactly `{"text":"..."}`
on stdout within 600 seconds. Install and pin your local speech model separately;
no model download or shell is provided. `ffmpeg_path` defaults to `/usr/bin/ffmpeg`
and may name an operator-vetted absolute decoder path. The decoder permits only
local file/pipe protocols and selected media formats; decoder and transcriber get
a minimal environment without API secrets. Missing adapter/decoder, oversized media,
invalid output or any uncertainty pauses. Transcription quality and media formats
require deployment testing. Visual frame review, rich/multi-tab editing and
arbitrary file extraction are unsupported; recorded approval does not implement
an adapter. The model's interpretation of "explicitly requested", semantic
venture relevance and editorial quality remain instructions/human review, not
reliable deterministic authorization. Grant approval provenance is recorded, not
cryptographically verified. No reliable sandbox claim is made.

The core branch covers normal messages, busy steering, producer/relay ingress,
reaction/platform hooks and Telegram inline callbacks. Other adapters' independent
controls need separate audit; do not expose untested control surfaces. The reference
worker uses POSIX file locking. A configured command runs with its process's OS
credentials/environment. Use separate OS/container credentials for hostile input;
Hermes itself remains an operator-trusted single-tenant application. Test each
profile/transport before exposure. Windows descendant termination is not covered
by the POSIX worker. Timeout/cancellation cannot roll back a completed Drive write.

## Tests

Offline tests use synthetic identities, `.invalid` email addresses and fake Google
responses. They cover allow, unrelated/unknown/revoked denial, uncertain permission,
exclusions, current edit roles, immutable identity, group output, founder routes,
mutation markers and rechecks. No test sends platform messages or changes real Drive
files. For core/real command integration, set `HERMES_AGENT_SOURCE` to the companion
checkout and run with its test dependencies installed:

```sh
python -m pytest plugins/scoped-collaborator-drive/tests -q
HERMES_AGENT_SOURCE=/path/to/hermes-agent python -m pytest plugins/scoped-collaborator-drive/tests -q
```

Core checks run via that repository's `scripts/run_tests.sh`. Live deployment
checks are still required; offline results are not evidence of live Drive ACL or
adversarial transport enforcement. Pin and record both repository commits and the
built image digest; mutable branch names are discovery references only.

### Container layer

The included [Dockerfile](Dockerfile) layers the plugin worker onto an already
built, reviewed Hermes core image without editing that core or replacing its s6
entrypoint. From this repository's root:

```sh
docker build -f plugins/scoped-collaborator-drive/Dockerfile \
  --build-arg HERMES_BASE=your-registry/hermes@sha256:YOUR_REVIEWED_CORE_DIGEST \
  -t collaborator-drive:YOUR_PLUGIN_COMMIT .
```

The base image must already contain the required admission change. For a local
build with the same Docker daemon/builder, a freshly built `hermi-core:CORE_COMMIT`
tag may be used instead; record/verify its actual image ID and do not pull or
replace it between the two builds. Remote builders need access to the pinned
base image in their own image store or registry. This layer
installs compatible bounded dependencies, not a hash-locked transitive dependency
set; retain build provenance and review resolved dependencies for production. Pin
both source commits and the resulting immutable image ID. Keep the root base user
and inherited entrypoint; Hermes CLI runs as its existing unprivileged user.
No Compose deployment, registry activation or credential migration is automatic.
