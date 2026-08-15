"""Deny-by-default capability grants and fenced argv-only dispatch."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit

from .canonical import canonical_digest
from .journal import (
    EffectState,
    Journal,
    JournalError,
    ReconciliationRequired,
)
from .state_machine import RunState


class CapabilityDenied(RuntimeError):
    """A request or dispatch did not satisfy every bound authority condition."""


class PolicyInvalid(ValueError):
    """A capability policy was ambiguous, unsafe, or structurally unknown."""


class DispatchStatus(str, Enum):
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"
    RECONCILIATION_REQUIRED = "reconciliation_required"


_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATTERN_META = frozenset("()[]{}+?\\^$|")
_SHELL_META = frozenset("\x00\n\r;&|<>`$(){}[]*?~\\'\"")
_FORBIDDEN_ENV_PARTS = (
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "CREDENTIAL",
    "PROXY",
    "API_KEY",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "AUTH_SOCK",
    "SESSION",
    "COOKIE",
    "BEARER",
)
_FORBIDDEN_ENV_PREFIXES = ("AWS_", "GITHUB_", "DB_", "DATABASE_")
_TERM_GRACE_SECONDS = 0.25
_KILL_GRACE_SECONDS = 0.25
WORKER_COMMIT_AUTHORITY_SECONDS = 29.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PolicyInvalid(f"{name} must be a non-empty NUL-free string")
    return value


def _require_digest(name: str, value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise PolicyInvalid(f"{name} must be a lowercase SHA-256 digest")
    return value


def _contains_traversal(value: str) -> bool:
    decoded = unquote(value)
    parsed = urlsplit(decoded)
    path = parsed.path if parsed.scheme else decoded
    return any(part == ".." for part in PurePosixPath(path).parts)


def _validate_resource_pattern(pattern: object) -> str:
    value = _require_text("resource_pattern", pattern)
    wildcard = value.endswith("/**")
    base = value[:-3] if wildcard else value
    if "*" in base or any(character in value for character in _PATTERN_META):
        raise PolicyInvalid(
            "resource_pattern supports only an exact value or a trailing /**"
        )
    if _contains_traversal(base):
        raise PolicyInvalid("resource_pattern cannot contain path traversal")
    return value


def _validate_resource(resource: str) -> None:
    if _contains_traversal(resource):
        raise CapabilityDenied("resource contains path traversal")
    if any(character in resource for character in ("\x00", "\n", "\r")):
        raise CapabilityDenied("resource contains unsafe characters")


def _is_path_resource(value: str) -> bool:
    return Path(value).is_absolute()


def _canonical_path(value: str, *, reject_symlink: bool = True) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise CapabilityDenied("resource path must be absolute")
    lexical = Path(os.path.abspath(path))
    resolved = path.resolve(strict=False)
    if reject_symlink and lexical != resolved:
        raise CapabilityDenied("resource path cannot traverse a symlink")
    return str(resolved)


def _within(path: str, root: str) -> bool:
    try:
        Path(path).relative_to(Path(root))
    except ValueError:
        return False
    return True


def _resource_matches(pattern: str, resource: str) -> bool:
    wildcard = pattern.endswith("/**")
    base = pattern[:-3] if wildcard else pattern
    if _is_path_resource(base):
        canonical_base = _canonical_path(base, reject_symlink=False)
        canonical_resource = _canonical_path(resource)
        return canonical_resource == canonical_base or (
            wildcard and _within(canonical_resource, canonical_base)
        )
    return resource == base or (
        wildcard and resource.startswith(base.rstrip("/") + "/")
    )


def _safe_argv_item(value: str) -> bool:
    if not value:
        return False
    return not any(character in _SHELL_META for character in value)


def _is_sensitive_environment_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(_FORBIDDEN_ENV_PREFIXES) or any(
        part in upper for part in _FORBIDDEN_ENV_PARTS
    )


@dataclass(frozen=True)
class ExecutableIdentity:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    content_sha256: str

    def canonical_record(self) -> dict[str, object]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "content_sha256": self.content_sha256,
        }


def _hash_fd(fd: int) -> str:
    digest = sha256()
    offset = 0
    while True:
        chunk = os.pread(fd, 1024 * 1024, offset)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)
        offset += len(chunk)


def _open_executable(path: str) -> tuple[int, ExecutableIdentity]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise PolicyInvalid("allowed executable cannot be opened safely") from error
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o111 == 0:
            raise PolicyInvalid("allowed executable is not an executable file")
        identity = ExecutableIdentity(
            details.st_dev,
            details.st_ino,
            details.st_mode,
            details.st_size,
            details.st_mtime_ns,
            _hash_fd(fd),
        )
        return fd, identity
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class CapabilityRequest:
    source: str
    capability: str
    resource: str
    operation: str
    requested_argv: tuple[str, ...] = ()
    task_fingerprint: str = ""

    def __post_init__(self) -> None:
        for name in ("source", "capability", "resource", "operation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if isinstance(self.requested_argv, str | bytes) or any(
            not isinstance(item, str) for item in self.requested_argv
        ):
            raise ValueError("requested_argv must be a sequence of strings")
        object.__setattr__(self, "requested_argv", tuple(self.requested_argv))
        if (
            not isinstance(self.task_fingerprint, str)
            or _DIGEST.fullmatch(self.task_fingerprint) is None
        ):
            raise ValueError("task_fingerprint must be a lowercase SHA-256 digest")

    def canonical_record(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "source": self.source,
                "capability": self.capability,
                "resource": self.resource,
                "operation": self.operation,
                "requested_argv": self.requested_argv,
                "task_fingerprint": self.task_fingerprint,
            }
        )


@dataclass(frozen=True)
class RunContext:
    run_id: str
    revision: int
    state: RunState
    workflow_release_digest: str
    approval_digest: str
    actor_class: str
    effect_id: str
    worker_id: str

    def __post_init__(self) -> None:
        for name in ("run_id", "actor_class", "effect_id", "worker_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a non-negative integer")
        object.__setattr__(self, "state", RunState(self.state))
        for name in ("workflow_release_digest", "approval_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class CapabilityRule:
    policy_id: str
    capability: str
    operation: str
    resource_pattern: str
    allowed_argv_prefix: tuple[str, ...]
    required_run_state: RunState
    approval_digest: str
    actor_class: str
    timeout_seconds: int
    idempotency_strategy: str
    reconciliation_strategy: str
    allowed_environment_names: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]
    executable_identity: ExecutableIdentity
    executable_fd: int

    def canonical_record(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "capability": self.capability,
            "operation": self.operation,
            "resource_pattern": self.resource_pattern,
            "allowed_argv_prefix": self.allowed_argv_prefix,
            "required_run_state": self.required_run_state.value,
            "approval_digest": self.approval_digest,
            "actor_class": self.actor_class,
            "timeout_seconds": self.timeout_seconds,
            "idempotency_strategy": self.idempotency_strategy,
            "reconciliation_strategy": self.reconciliation_strategy,
            "allowed_environment_names": self.allowed_environment_names,
            "allowed_write_roots": self.allowed_write_roots,
            "executable_identity": self.executable_identity.canonical_record(),
        }


_TOP_LEVEL_FIELDS = frozenset({"schema_version", "workflow_release_digest", "policies"})
_RULE_FIELDS = frozenset(
    {
        "policy_id",
        "capability",
        "operation",
        "resource_pattern",
        "allowed_argv_prefix",
        "required_run_state",
        "approval_digest",
        "actor_class",
        "timeout_seconds",
        "idempotency_strategy",
        "reconciliation_strategy",
        "allowed_environment_names",
        "allowed_write_roots",
    }
)


@dataclass(frozen=True)
class CapabilityPolicy:
    schema_version: str
    workflow_release_digest: str
    rules: tuple[CapabilityRule, ...]
    digest: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapabilityPolicy:
        if not isinstance(value, Mapping):
            raise PolicyInvalid("capability policy must be a mapping")
        unknown = set(value) - _TOP_LEVEL_FIELDS
        if unknown:
            raise PolicyInvalid(f"unknown field: {min(unknown)}")
        if value.get("schema_version") != "1.0":
            raise PolicyInvalid("schema_version must be 1.0")
        workflow_release_digest = _require_digest(
            "workflow_release_digest", value.get("workflow_release_digest")
        )
        raw_rules = value.get("policies")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise PolicyInvalid("policies must be a non-empty list")
        rules: list[CapabilityRule] = []
        identifiers: set[str] = set()
        for index, raw in enumerate(raw_rules):
            if not isinstance(raw, Mapping):
                raise PolicyInvalid(f"policies[{index}] must be a mapping")
            missing = _RULE_FIELDS - set(raw)
            unknown = set(raw) - _RULE_FIELDS
            if missing:
                raise PolicyInvalid(f"missing field: {min(missing)}")
            if unknown:
                raise PolicyInvalid(f"unknown field: {min(unknown)}")
            policy_id = _require_text("policy_id", raw["policy_id"])
            if _IDENTIFIER.fullmatch(policy_id) is None or policy_id in identifiers:
                raise PolicyInvalid(
                    "policy_id must be unique and use safe identifier characters"
                )
            identifiers.add(policy_id)
            capability = _require_text("capability", raw["capability"])
            operation = _require_text("operation", raw["operation"])
            if operation not in {"read", "write", "execute"}:
                raise PolicyInvalid("operation must be read, write, or execute")
            raw_prefix = raw["allowed_argv_prefix"]
            if (
                not isinstance(raw_prefix, list)
                or not raw_prefix
                or any(
                    not isinstance(item, str) or not _safe_argv_item(item)
                    for item in raw_prefix
                )
            ):
                raise PolicyInvalid(
                    "allowed_argv_prefix must contain safe non-empty strings"
                )
            executable = Path(raw_prefix[0])
            if not executable.is_absolute():
                raise PolicyInvalid("allowed executable must be an absolute path")
            try:
                executable_realpath = str(executable.resolve(strict=True))
            except OSError as error:
                raise PolicyInvalid("allowed executable does not exist") from error
            prefix = (executable_realpath, *(str(item) for item in raw_prefix[1:]))
            try:
                required_state = RunState(raw["required_run_state"])
            except (TypeError, ValueError) as error:
                raise PolicyInvalid("required_run_state is unknown") from error
            timeout = raw["timeout_seconds"]
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or not 1 <= timeout <= 300
            ):
                raise PolicyInvalid("timeout_seconds must be between 1 and 300")
            if raw["idempotency_strategy"] != "effect-id":
                raise PolicyInvalid("idempotency_strategy must be effect-id")
            if raw["reconciliation_strategy"] != "journal-probe":
                raise PolicyInvalid("reconciliation_strategy must be journal-probe")
            environment = raw["allowed_environment_names"]
            if not isinstance(environment, list) or any(
                not isinstance(item, str) or _ENVIRONMENT_NAME.fullmatch(item) is None
                for item in environment
            ):
                raise PolicyInvalid("allowed_environment_names must contain safe names")
            if len(environment) != len(set(environment)):
                raise PolicyInvalid("allowed_environment_names contains a duplicate")
            raw_roots = raw["allowed_write_roots"]
            if not isinstance(raw_roots, list) or any(
                not isinstance(item, str) or not Path(item).is_absolute()
                for item in raw_roots
            ):
                raise PolicyInvalid("allowed_write_roots must contain absolute paths")
            roots_list: list[str] = []
            for item in raw_roots:
                if _contains_traversal(item):
                    raise PolicyInvalid(
                        "allowed_write_roots cannot contain path traversal"
                    )
                lexical_root = Path(os.path.abspath(item))
                resolved_root = Path(item).resolve(strict=False)
                if lexical_root != resolved_root:
                    raise PolicyInvalid("allowed_write_roots cannot contain a symlink")
                roots_list.append(str(resolved_root))
            roots = tuple(roots_list)
            if len(roots) != len(set(roots)):
                raise PolicyInvalid("allowed_write_roots contains a duplicate")
            resource_pattern = _validate_resource_pattern(raw["resource_pattern"])
            path_pattern = resource_pattern.removesuffix("/**")
            if operation != "read" and _is_path_resource(path_pattern) and not roots:
                raise PolicyInvalid(
                    "filesystem mutation policies require at least one allowed write root"
                )
            if any(_within(executable_realpath, root) for root in roots):
                raise PolicyInvalid(
                    "allowed executable cannot be inside an allowed write root"
                )
            executable_fd, executable_identity = _open_executable(executable_realpath)
            rules.append(
                CapabilityRule(
                    policy_id,
                    capability,
                    operation,
                    resource_pattern,
                    prefix,
                    required_state,
                    _require_digest("approval_digest", raw["approval_digest"]),
                    _require_text("actor_class", raw["actor_class"]),
                    timeout,
                    "effect-id",
                    "journal-probe",
                    tuple(environment),
                    roots,
                    executable_identity,
                    executable_fd,
                )
            )
        record = {
            "schema_version": "1.0",
            "workflow_release_digest": workflow_release_digest,
            "policies": [rule.canonical_record() for rule in rules],
        }
        return cls(
            "1.0",
            workflow_release_digest,
            tuple(rules),
            canonical_digest(record),
        )


@dataclass(frozen=True)
class Grant:
    grant_id: str
    request_digest: str
    policy_digest: str
    policy_id: str
    capability: str
    operation: str
    resource: str
    actor_class: str
    allowed_argv_prefix: tuple[str, ...]
    canonical_argv: tuple[str, ...]
    argv_digest: str
    task_fingerprint: str
    executable_realpath: str
    executable_identity: ExecutableIdentity
    allowed_environment_names: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]
    timeout_seconds: int
    idempotency_strategy: str
    reconciliation_strategy: str
    run_id: str
    run_revision: int
    run_state: RunState
    workflow_release_digest: str
    approval_digest: str
    effect_id: str
    fence: int
    worker_id: str
    issued_at: datetime
    expires_at: datetime
    lease_expires_at: datetime

    def _content(self) -> dict[str, object]:
        return {
            "request_digest": self.request_digest,
            "policy_digest": self.policy_digest,
            "policy_id": self.policy_id,
            "capability": self.capability,
            "operation": self.operation,
            "resource": self.resource,
            "actor_class": self.actor_class,
            "allowed_argv_prefix": self.allowed_argv_prefix,
            "canonical_argv": self.canonical_argv,
            "argv_digest": self.argv_digest,
            "task_fingerprint": self.task_fingerprint,
            "executable_realpath": self.executable_realpath,
            "executable_identity": self.executable_identity.canonical_record(),
            "allowed_environment_names": self.allowed_environment_names,
            "allowed_write_roots": self.allowed_write_roots,
            "timeout_seconds": self.timeout_seconds,
            "idempotency_strategy": self.idempotency_strategy,
            "reconciliation_strategy": self.reconciliation_strategy,
            "run_id": self.run_id,
            "run_revision": self.run_revision,
            "run_state": self.run_state.value,
            "workflow_release_digest": self.workflow_release_digest,
            "approval_digest": self.approval_digest,
            "effect_id": self.effect_id,
            "fence": self.fence,
            "worker_id": self.worker_id,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "lease_expires_at": self.lease_expires_at.isoformat(),
        }

    def verify_digest(self) -> bool:
        return self.grant_id == canonical_digest(self._content())


@dataclass(frozen=True)
class BrokerDecision:
    request_digest: str
    allowed: bool
    reason_code: str
    observed_at: datetime
    capability: str = ""
    resource: str = ""
    run_id: str = ""
    revision: int = -1
    policy_digest: str = ""


@dataclass(frozen=True)
class EffectResult:
    status: DispatchStatus
    effect_id: str
    fence: int
    returncode: int | None
    stdout: str
    stderr: str
    evidence_ref: str | None


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
ResultValidator = Callable[[subprocess.CompletedProcess[str]], object]
AuditSink = Callable[[BrokerDecision], None]


class CapabilityBroker:
    """Issue bound grants and execute only exact argv vectors under journal fencing."""

    def __init__(
        self,
        policy: CapabilityPolicy,
        journal: Journal,
        *,
        clock: Callable[[], datetime] | None = None,
        process_runner: ProcessRunner | None = None,
        environment: Mapping[str, str] | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.policy = policy
        self.journal = journal
        self._clock = clock or _utc_now
        self._uses_real_runner = process_runner is None
        self._process_runner = process_runner or self._run_process_tree
        self._environment = dict(os.environ if environment is None else environment)
        self._audit_sink = audit_sink
        self._issued: dict[str, Grant] = {}
        self._decisions: list[BrokerDecision] = []
        self._executable_directory = tempfile.TemporaryDirectory(
            prefix="cdd-verified-executables-"
        )
        executable_root = Path(self._executable_directory.name)
        executable_root.chmod(0o700)
        trusted: dict[str, str] = {}
        materialized_by_digest: dict[str, str] = {}
        for rule in self.policy.rules:
            digest = rule.executable_identity.content_sha256
            materialized = materialized_by_digest.get(digest)
            if materialized is None:
                target = executable_root / digest
                shutil.copyfile(
                    rule.allowed_argv_prefix[0],
                    target,
                    follow_symlinks=False,
                )
                copied = target.lstat()
                if not stat.S_ISREG(copied.st_mode) or target.is_symlink():
                    raise PolicyInvalid("verified executable copy is not regular")
                target.chmod(0o500)
                descriptor, copied_identity = _open_executable(str(target))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                if (
                    copied_identity.size != rule.executable_identity.size
                    or copied_identity.content_sha256 != digest
                ):
                    raise PolicyInvalid("verified executable copy failed attestation")
                materialized = str(target)
                materialized_by_digest[digest] = materialized
            trusted[rule.policy_id] = materialized
        executable_root.chmod(0o500)
        self._trusted_executables = MappingProxyType(trusted)

    @property
    def decisions(self) -> tuple[BrokerDecision, ...]:
        return tuple(self._decisions)

    def _record_decision(self, decision: BrokerDecision) -> None:
        self._decisions.append(decision)
        if self._audit_sink is not None:
            self._audit_sink(decision)

    def _deny(
        self,
        request_digest: str,
        code: str,
        message: str,
        *,
        request: CapabilityRequest | None = None,
        context: RunContext | None = None,
        grant: Grant | None = None,
    ) -> None:
        self._record_decision(
            BrokerDecision(
                request_digest,
                False,
                code,
                self._clock(),
                request.capability
                if request is not None
                else grant.capability
                if grant
                else "",
                request.resource
                if request is not None
                else grant.resource
                if grant
                else "",
                context.run_id
                if context is not None
                else grant.run_id
                if grant
                else "",
                context.revision
                if context is not None
                else grant.run_revision
                if grant
                else -1,
                self.policy.digest,
            )
        )
        raise CapabilityDenied(message)

    def authorize(self, request: CapabilityRequest, context: RunContext) -> Grant:
        return self._authorize(request, context, prepared_adoption_ref=None)

    def authorize_prepared_adoption(
        self,
        request: CapabilityRequest,
        context: RunContext,
        prepared_adoption_ref: str,
    ) -> Grant:
        if (
            not isinstance(prepared_adoption_ref, str)
            or re.fullmatch(
                r"effect-stage://sha256/[a-f0-9]{64}", prepared_adoption_ref
            )
            is None
        ):
            self._deny(
                canonical_digest(request.canonical_record()),
                "prepared-adoption-evidence",
                "prepared adoption evidence is invalid",
                request=request,
                context=context,
            )
        return self._authorize(
            request,
            context,
            prepared_adoption_ref=prepared_adoption_ref,
        )

    def _authorize(
        self,
        request: CapabilityRequest,
        context: RunContext,
        *,
        prepared_adoption_ref: str | None,
    ) -> Grant:
        request_digest = canonical_digest(request.canonical_record())

        def deny(code: str, message: str) -> None:
            self._deny(
                request_digest,
                code,
                message,
                request=request,
                context=context,
            )

        if context.workflow_release_digest != self.policy.workflow_release_digest:
            deny("workflow-release-mismatch", "workflow release does not match policy")
        if request.source == "extension" and request.operation != "read":
            deny(
                "untrusted-source-mutation",
                "extension payloads cannot request mutating capabilities",
            )
        try:
            _validate_resource(request.resource)
        except CapabilityDenied as error:
            deny("unsafe-resource", str(error))
        candidates = [
            rule
            for rule in self.policy.rules
            if rule.capability == request.capability
            and rule.operation == request.operation
        ]
        if not candidates:
            deny("unknown-capability", "capability is not allowed")
        actor_candidates = [
            rule for rule in candidates if rule.actor_class == context.actor_class
        ]
        if not actor_candidates:
            deny("actor-mismatch", "actor class is not allowed")
        approval_candidates = [
            rule
            for rule in actor_candidates
            if rule.approval_digest == context.approval_digest
        ]
        if not approval_candidates:
            deny(
                "approval-mismatch",
                "approval digest does not match policy",
            )
        state_candidates = [
            rule
            for rule in approval_candidates
            if rule.required_run_state is context.state
        ]
        if not state_candidates:
            deny("state-mismatch", "run state does not match policy")
        matches = [
            rule
            for rule in state_candidates
            if _resource_matches(rule.resource_pattern, request.resource)
        ]
        if len(matches) != 1:
            reason = (
                "resource is not allowed"
                if not matches
                else "capability policy is ambiguous"
            )
            deny("resource-mismatch", reason)
        rule = matches[0]
        snapshot = self.journal.get_run(context.run_id)
        if (
            snapshot is None
            or snapshot.revision != context.revision
            or snapshot.state is not context.state
        ):
            deny(
                "run-context-drift",
                "run context does not match journal",
            )
        resource = request.resource
        if _is_path_resource(resource):
            try:
                resource = _canonical_path(resource)
            except CapabilityDenied as error:
                deny("unsafe-resource", str(error))
        if (
            request.operation != "read"
            and _is_path_resource(resource)
            and not any(_within(resource, root) for root in rule.allowed_write_roots)
        ):
            deny("write-scope", "resource is outside allowed write roots")
        requested_argv = self._validate_requested_argv(
            request_digest, request, rule, resource
        )
        issued_at = self._clock()
        commit_authority_seconds = (
            WORKER_COMMIT_AUTHORITY_SECONDS
            if request.capability in {"worker.analysis", "worker.implementation"}
            else 0.0
        )
        dispatch_authority_seconds = (
            rule.timeout_seconds + _TERM_GRACE_SECONDS + _KILL_GRACE_SECONDS
        )
        lease_ttl = rule.timeout_seconds + max(
            dispatch_authority_seconds, commit_authority_seconds
        )
        try:
            lease = self.journal.acquire_attempt(
                context.run_id,
                context.effect_id,
                context.worker_id,
                timedelta(seconds=lease_ttl),
            )
            if prepared_adoption_ref is None:
                lease.assert_dispatch_allowed()
            else:
                effect = self.journal.get_effect(context.run_id, context.effect_id)
                if (
                    lease.dispatch_allowed
                    or effect is None
                    or effect.state is not EffectState.PREPARED
                    or effect.evidence_ref != prepared_adoption_ref
                ):
                    deny(
                        "prepared-adoption-mismatch",
                        "prepared adoption does not match durable stage authority",
                    )
        except ReconciliationRequired:
            deny(
                "reconciliation-required",
                "effect requires reconciliation",
            )
        except JournalError as error:
            deny(
                "journal-authority",
                f"journal denied authority: {type(error).__name__}",
            )
        content: dict[str, Any] = {
            "request_digest": request_digest,
            "policy_digest": self.policy.digest,
            "policy_id": rule.policy_id,
            "capability": request.capability,
            "operation": request.operation,
            "resource": resource,
            "actor_class": context.actor_class,
            "allowed_argv_prefix": rule.allowed_argv_prefix,
            "canonical_argv": requested_argv,
            "argv_digest": canonical_digest(requested_argv),
            "task_fingerprint": request.task_fingerprint,
            "executable_realpath": rule.allowed_argv_prefix[0],
            "executable_identity": rule.executable_identity,
            "allowed_environment_names": rule.allowed_environment_names,
            "allowed_write_roots": rule.allowed_write_roots,
            "timeout_seconds": rule.timeout_seconds,
            "idempotency_strategy": rule.idempotency_strategy,
            "reconciliation_strategy": rule.reconciliation_strategy,
            "run_id": context.run_id,
            "run_revision": context.revision,
            "run_state": context.state,
            "workflow_release_digest": context.workflow_release_digest,
            "approval_digest": context.approval_digest,
            "effect_id": context.effect_id,
            "fence": lease.fence,
            "worker_id": context.worker_id,
            "issued_at": issued_at,
            "expires_at": issued_at
            + timedelta(seconds=rule.timeout_seconds + commit_authority_seconds),
            "lease_expires_at": lease.expires_at,
        }
        provisional = Grant("", **content)
        grant = Grant(canonical_digest(provisional._content()), **content)
        self._issued[grant.grant_id] = grant
        self._record_decision(
            BrokerDecision(
                request_digest,
                True,
                "prepared-adoption-authorized"
                if prepared_adoption_ref is not None
                else "authorized",
                issued_at,
                request.capability,
                request.resource,
                context.run_id,
                context.revision,
                self.policy.digest,
            )
        )
        return grant

    def _validate_grant(
        self, grant: Grant, *, minimum_validity_seconds: float = 0.0
    ) -> None:
        if (
            not isinstance(minimum_validity_seconds, int | float)
            or isinstance(minimum_validity_seconds, bool)
            or minimum_validity_seconds < 0
        ):
            raise ValueError("minimum grant validity must be non-negative")
        if not isinstance(grant, Grant) or not grant.verify_digest():
            self._deny("invalid-grant", "grant-digest", "grant digest is invalid")
        if self._issued.get(grant.grant_id) != grant:
            self._deny(
                grant.request_digest,
                "grant-not-issued",
                "grant was not issued by this broker",
            )
        if grant.workflow_release_digest != self.policy.workflow_release_digest:
            self._deny(
                grant.request_digest,
                "workflow-release-drift",
                "workflow release changed",
                grant=grant,
            )
        if grant.policy_digest != self.policy.digest:
            self._deny(
                grant.request_digest, "policy-drift", "capability policy changed"
            )
        now = self._clock()
        if now >= grant.expires_at:
            self._deny(grant.request_digest, "grant-expired", "grant expired")
        minimum_valid_until = now + timedelta(seconds=minimum_validity_seconds)
        if minimum_valid_until >= grant.expires_at:
            self._deny(
                grant.request_digest,
                "grant-deadline",
                "grant does not cover the bounded commit deadline",
                grant=grant,
            )
        required_lease_until = now + timedelta(
            seconds=(grant.timeout_seconds + _TERM_GRACE_SECONDS + _KILL_GRACE_SECONDS)
        )
        if grant.lease_expires_at < required_lease_until:
            self._deny(
                grant.request_digest,
                "lease-deadline",
                "lease does not cover the complete dispatch deadline",
                grant=grant,
            )
        snapshot = self.journal.get_run(grant.run_id)
        if (
            snapshot is None
            or snapshot.revision != grant.run_revision
            or snapshot.state is not grant.run_state
        ):
            self._deny(
                grant.request_digest,
                "run-context-drift",
                "run context drifted after authorization",
            )
        if _is_path_resource(grant.resource):
            try:
                current_resource = _canonical_path(grant.resource)
            except CapabilityDenied:
                self._deny(
                    grant.request_digest,
                    "resource-drift",
                    "resource drifted after authorization",
                )
            if current_resource != grant.resource or (
                grant.operation != "read"
                and not any(
                    _within(current_resource, root)
                    for root in grant.allowed_write_roots
                )
            ):
                self._deny(
                    grant.request_digest,
                    "resource-drift",
                    "resource drifted after authorization",
                )

    def _materialize_argv(
        self, request_digest: str, argv: Sequence[str]
    ) -> tuple[str, ...]:
        if isinstance(argv, str | bytes):
            self._deny(
                request_digest, "argv-type", "argv must be a sequence of strings"
            )
        materialized = tuple(argv)
        if not materialized:
            self._deny(request_digest, "argv-empty", "argv cannot be empty")
        if any(not isinstance(item, str) for item in materialized):
            self._deny(request_digest, "argv-type", "every argv item must be a string")
        if any(not _safe_argv_item(item) for item in materialized):
            self._deny(
                request_digest,
                "argv-shell-syntax",
                "argv contains shell syntax or expansion",
            )
        return materialized

    def _validate_requested_argv(
        self,
        request_digest: str,
        request: CapabilityRequest,
        rule: CapabilityRule,
        resource: str,
    ) -> tuple[str, ...]:
        materialized = self._materialize_argv(request_digest, request.requested_argv)
        prefix = rule.allowed_argv_prefix
        if materialized[: len(prefix)] != prefix:
            self._deny(
                request_digest,
                "argv-prefix",
                "argv does not match the allowed prefix",
            )
        prohibited = {
            "--dangerously-bypass-approvals-and-sandbox",
            "--approve-for-me",
            "--add-dir",
            "--dangerously-bypass-hook-trust",
        }
        if (
            prohibited.intersection(materialized)
            or "danger-full-access" in materialized
        ):
            self._deny(
                request_digest, "worker-danger-flag", "dangerous argv is forbidden"
            )
        if request.capability in {"worker.analysis", "worker.implementation"}:
            mode = (
                "read-only"
                if request.capability == "worker.analysis"
                else "workspace-write"
            )
            if (
                Path(prefix[0]).name == "limactl"
                and len(prefix) == 8
                and prefix[1] == "shell"
                and _IDENTIFIER.fullmatch(prefix[2]) is not None
                and prefix[3] == "--"
                and Path(prefix[4]).is_absolute()
                and Path(prefix[5]).is_absolute()
                and prefix[6] == "--workspace-base"
                and Path(prefix[7]).is_absolute()
            ):
                suffix = materialized[len(prefix) :]
                if (
                    len(suffix) != 9
                    or suffix[0] != "--authority-digest"
                    or _DIGEST.fullmatch(suffix[1]) is None
                    or suffix[2] != "--source-snapshot-digest"
                    or _DIGEST.fullmatch(suffix[3]) is None
                    or suffix[4] != "--kind"
                    or suffix[5]
                    != ("analysis" if mode == "read-only" else "implementation")
                    or suffix[6] != "--task-fingerprint"
                    or suffix[7] != request.task_fingerprint
                    or suffix[8] != "--json"
                ):
                    self._deny(
                        request_digest,
                        "worker-command-grammar",
                        "worker command does not match canonical argv grammar",
                    )
                expected = materialized
            else:
                expected = (
                    prefix[0],
                    "exec",
                    "--sandbox",
                    mode,
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--cd",
                    resource,
                    "--json",
                    "-",
                )
            if materialized != expected:
                self._deny(
                    request_digest,
                    "worker-command-grammar",
                    "worker command does not match canonical argv grammar",
                )
        return materialized

    def _validate_argv(
        self, grant: Grant, argv: Sequence[str]
    ) -> tuple[tuple[str, ...], int, int]:
        materialized = self._materialize_argv(grant.request_digest, argv)
        if (
            materialized != grant.canonical_argv
            or canonical_digest(materialized) != grant.argv_digest
        ):
            self._deny(
                grant.request_digest,
                "argv-grant-mismatch",
                "argv does not exactly match the grant",
            )
        try:
            executable = str(Path(materialized[0]).resolve(strict=True))
            executable_fd, identity = _open_executable(materialized[0])
        except (OSError, PolicyInvalid):
            self._deny(
                grant.request_digest, "unknown-executable", "executable is unavailable"
            )
        rule = next(
            (item for item in self.policy.rules if item.policy_id == grant.policy_id),
            None,
        )
        if (
            rule is None
            or executable != grant.executable_realpath
            or identity != grant.executable_identity
            or rule.executable_identity != grant.executable_identity
            or _hash_fd(rule.executable_fd) != grant.executable_identity.content_sha256
        ):
            os.close(executable_fd)
            self._deny(
                grant.request_digest,
                "unknown-executable",
                "executable identity changed",
            )
        return materialized, executable_fd, rule.executable_fd

    def _child_environment(
        self, grant: Grant, *, isolated_home: str | None = None
    ) -> dict[str, str]:
        environment = {
            name: self._environment[name]
            for name in grant.allowed_environment_names
            if name in self._environment and not _is_sensitive_environment_name(name)
        }
        environment["CDD_IDEMPOTENCY_KEY"] = grant.effect_id
        environment["CDD_EFFECT_FENCE"] = str(grant.fence)
        if isolated_home is not None:
            environment["HOME"] = isolated_home
            environment["TMPDIR"] = isolated_home
            environment["CODEX_HOME"] = self._environment.get(
                "CODEX_HOME", str(Path.home() / ".codex")
            )
        return environment

    @staticmethod
    def _seatbelt_literal(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _seatbelt_command(
        self,
        grant: Grant,
        command: tuple[str, ...],
        isolated_home: str,
        read_roots: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not Path("/usr/bin/sandbox-exec").is_file():
            self._deny(
                grant.request_digest,
                "worker-sandbox-unavailable",
                "outer worker sandbox is unavailable",
                grant=grant,
            )
        codex_home = self._environment.get("CODEX_HOME") or str(Path.home() / ".codex")
        literal = self._seatbelt_literal
        system_reads = (
            "/System",
            "/Library",
            "/usr",
            "/bin",
            "/sbin",
            "/Applications",
            "/private/etc",
            "/private/var/select",
        )
        approved_reads = tuple(
            dict.fromkeys((*system_reads, grant.resource, *read_roots))
        )
        trusted_executable = command[0]
        ancestor_metadata = tuple(
            dict.fromkeys(
                str(parent)
                for root in (grant.resource, isolated_home, *read_roots)
                for parent in Path(root).parents
                if str(parent) != "/"
            )
        )
        rules = [
            "(version 1)",
            '(import "system.sb")',
            "(deny file-read*)",
            "(deny file-write*)",
            "(deny network*)",
            "(allow process-exec)",
            "(allow file-read* "
            + " ".join(f"(subpath {literal(path)})" for path in approved_reads)
            + ")",
            "(allow file-read-metadata "
            + " ".join(f"(literal {literal(path)})" for path in ancestor_metadata)
            + ")",
            f"(allow file-read* file-write* (subpath {literal(isolated_home)}))",
            (
                "(allow file-read* file-write* "
                f"(subpath {literal(codex_home)}) "
                f"(process-path {literal(trusted_executable)}))"
            ),
            (f"(allow network* (process-path {literal(trusted_executable)}))"),
            (f"(allow mach* ipc* (process-path {literal(trusted_executable)}))"),
            f"(deny process-exec (literal {literal('/usr/bin/security')}))",
        ]
        if grant.capability == "worker.implementation":
            rules.append(f"(allow file-write* (subpath {literal(grant.resource)}))")
        return ("/usr/bin/sandbox-exec", "-p", "\n".join(rules), *command)

    @staticmethod
    def _worker_outcome(completed: subprocess.CompletedProcess[str]) -> DispatchStatus:
        if completed.returncode != 0:
            return DispatchStatus.FAILED
        denied = False
        failed = False
        for line in (completed.stdout or "").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") if isinstance(event, dict) else None
            if not isinstance(item, dict) or item.get("type") != "command_execution":
                continue
            if item.get("status") == "in_progress":
                continue
            exit_code = item.get("exit_code")
            if exit_code in (0, None):
                continue
            failed = True
            detail = " ".join(
                str(item.get(name, "")) for name in ("aggregated_output", "output")
            )
            if "Operation not permitted" in detail or "Permission denied" in detail:
                denied = True
        if denied:
            return DispatchStatus.DENIED
        if failed:
            return DispatchStatus.FAILED
        return DispatchStatus.COMPLETED

    @staticmethod
    def _run_process_tree(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        timeout = float(kwargs.pop("timeout"))
        stdin_text = kwargs.pop("input", None)
        kwargs.pop("check", None)
        if kwargs.pop("capture_output", False):
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
        if stdin_text is not None:
            kwargs["stdin"] = subprocess.PIPE
        process = subprocess.Popen(argv, start_new_session=True, **kwargs)
        try:
            stdout, stderr = process.communicate(input=stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process_group = process.pid

            def group_exists() -> bool:
                try:
                    os.killpg(process_group, 0)
                except ProcessLookupError:
                    return False
                return True

            try:
                os.killpg(process_group, signal.SIGTERM)
            except ProcessLookupError:
                pass
            term_deadline = time.monotonic() + _TERM_GRACE_SECONDS
            while group_exists() and time.monotonic() < term_deadline:
                process.poll()
                time.sleep(0.01)
            if group_exists():
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            kill_deadline = time.monotonic() + _KILL_GRACE_SECONDS
            while group_exists() and time.monotonic() < kill_deadline:
                process.poll()
                time.sleep(0.01)
            if process.poll() is None:
                process.wait(timeout=_KILL_GRACE_SECONDS)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            raise subprocess.TimeoutExpired(
                argv,
                timeout,
                output=error.output,
                stderr=error.stderr,
            ) from error
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout,
            stderr,
        )

    @staticmethod
    def _evidence_ref(
        grant: Grant,
        *,
        returncode: int | None,
        stdout: str,
        stderr: str,
        outcome: str,
    ) -> str:
        digest = canonical_digest(
            {
                "effect_id": grant.effect_id,
                "fence": grant.fence,
                "outcome": outcome,
                "returncode": returncode,
                "stdout_digest": canonical_digest(stdout),
                "stderr_digest": canonical_digest(stderr),
            }
        )
        return f"effect-result://sha256/{digest}"

    def dispatch(self, grant: Grant, argv: Sequence[str]) -> EffectResult:
        result, _ = self._dispatch(grant, argv)
        return result

    def commit_prepared_adoption(
        self,
        grant: Grant,
        prior_stage_ref: str,
        adopted_stage_ref: str,
        prepared: object,
        committer: Callable[[object, Callable[[float], None]], object],
    ) -> tuple[EffectResult, object | None]:
        """Adopt and commit a staged result without re-running the worker."""
        self._validate_grant(grant)
        try:
            self.journal.adopt_prepared(
                grant.effect_id,
                grant.fence,
                prior_stage_ref,
                adopted_stage_ref,
            )
        except JournalError:
            return (
                EffectResult(
                    DispatchStatus.RECONCILIATION_REQUIRED,
                    grant.effect_id,
                    grant.fence,
                    None,
                    "",
                    "",
                    None,
                ),
                None,
            )

        def validate_commit_authority(required_seconds: float) -> None:
            self._validate_grant(grant, minimum_validity_seconds=required_seconds)
            self.journal.record_effect(
                grant.effect_id,
                grant.fence,
                EffectState.PREPARED,
                adopted_stage_ref,
                minimum_lease_ttl=timedelta(seconds=required_seconds),
            )

        try:
            validation = committer(prepared, validate_commit_authority)
            self.journal.record_effect(
                grant.effect_id,
                grant.fence,
                EffectState.COMPLETED,
                adopted_stage_ref,
            )
        except Exception:  # noqa: BLE001 - adoption remains typed reconciliation
            return (
                EffectResult(
                    DispatchStatus.RECONCILIATION_REQUIRED,
                    grant.effect_id,
                    grant.fence,
                    None,
                    "",
                    "",
                    None,
                ),
                None,
            )
        return (
            EffectResult(
                DispatchStatus.COMPLETED,
                grant.effect_id,
                grant.fence,
                0,
                "",
                "",
                adopted_stage_ref,
            ),
            validation,
        )

    def _dispatch(
        self,
        grant: Grant,
        argv: Sequence[str],
        *,
        stdin_text: str | None = None,
        result_validator: ResultValidator | None = None,
        result_preparer: Callable[
            [subprocess.CompletedProcess[str]], tuple[str, object]
        ]
        | None = None,
        result_committer: Callable[[object, Callable[[float], None]], object]
        | None = None,
        sandbox_read_roots: tuple[str, ...] = (),
    ) -> tuple[EffectResult, object | None]:
        self._validate_grant(grant)
        command, executable_fd, policy_fd = self._validate_argv(grant, argv)
        effect = self.journal.get_effect(grant.run_id, grant.effect_id)
        if effect is None or effect.state is not EffectState.INTENT:
            self._deny(
                grant.request_digest,
                "already-dispatched",
                "grant was already dispatched",
            )
        try:
            self.journal.record_effect(
                grant.effect_id, grant.fence, EffectState.STARTED, None
            )
        except JournalError as error:
            self._deny(
                grant.request_digest,
                "fence-drift",
                f"journal fence drift: {type(error).__name__}",
            )
        cwd = (
            grant.resource
            if _is_path_resource(grant.resource) and Path(grant.resource).is_dir()
            else None
        )
        isolated_home_manager: tempfile.TemporaryDirectory[str] | None = None
        execution_command = (
            self._trusted_executables[grant.policy_id],
            *command[1:],
        )
        isolated_home: str | None = None
        if (
            self._uses_real_runner
            and grant.capability.startswith("worker.")
            and Path(command[0]).name != "limactl"
        ):
            isolated_home_manager = tempfile.TemporaryDirectory(
                prefix="cdd-worker-home-"
            )
            isolated_home = isolated_home_manager.name
            execution_command = self._seatbelt_command(
                grant,
                execution_command,
                isolated_home,
                sandbox_read_roots,
            )
        try:
            completed = self._process_runner(
                execution_command,
                input=stdin_text,
                cwd=cwd,
                env=self._child_environment(grant, isolated_home=isolated_home),
                timeout=grant.timeout_seconds,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                pass_fds=(policy_fd, executable_fd),
            )
        except (subprocess.TimeoutExpired, OSError):
            return (
                EffectResult(
                    DispatchStatus.RECONCILIATION_REQUIRED,
                    grant.effect_id,
                    grant.fence,
                    None,
                    "",
                    "",
                    None,
                ),
                None,
            )
        finally:
            os.close(executable_fd)
            if isolated_home_manager is not None:
                isolated_home_manager.cleanup()
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        status = (
            self._worker_outcome(completed)
            if grant.capability.startswith("worker.")
            else DispatchStatus.COMPLETED
            if completed.returncode == 0
            else DispatchStatus.FAILED
        )
        validation: object | None = None
        prepared: object | None = None
        prepared_ref: str | None = None
        try:
            if result_preparer is not None and status is DispatchStatus.COMPLETED:
                if result_committer is None:
                    raise RuntimeError("prepared result requires a committer")
                prepared_ref, prepared = result_preparer(completed)
                if not isinstance(prepared_ref, str) or not prepared_ref.strip():
                    raise RuntimeError("prepared result requires durable evidence")
            elif result_validator is not None and status is DispatchStatus.COMPLETED:
                validation = result_validator(completed)
        except Exception:
            evidence = self._evidence_ref(
                grant,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                outcome="policy-violation",
            )
            self.journal.record_effect(
                grant.effect_id, grant.fence, EffectState.COMPLETED, evidence
            )
            self._record_decision(
                BrokerDecision(
                    grant.request_digest,
                    False,
                    "result-policy-violation",
                    self._clock(),
                    grant.capability,
                    grant.resource,
                    grant.run_id,
                    grant.run_revision,
                    self.policy.digest,
                )
            )
            raise
        if prepared_ref is not None:
            try:
                self.journal.record_effect(
                    grant.effect_id,
                    grant.fence,
                    EffectState.PREPARED,
                    prepared_ref,
                )
            except JournalError:
                return (
                    EffectResult(
                        DispatchStatus.RECONCILIATION_REQUIRED,
                        grant.effect_id,
                        grant.fence,
                        completed.returncode,
                        stdout,
                        stderr,
                        None,
                    ),
                    prepared,
                )

            def validate_commit_authority(required_seconds: float) -> None:
                self._validate_grant(grant, minimum_validity_seconds=required_seconds)
                self.journal.record_effect(
                    grant.effect_id,
                    grant.fence,
                    EffectState.PREPARED,
                    prepared_ref,
                    minimum_lease_ttl=timedelta(seconds=required_seconds),
                )

            try:
                validation = result_committer(prepared, validate_commit_authority)
            except Exception:  # noqa: BLE001 - commit failures require reconciliation
                return (
                    EffectResult(
                        DispatchStatus.RECONCILIATION_REQUIRED,
                        grant.effect_id,
                        grant.fence,
                        completed.returncode,
                        stdout,
                        stderr,
                        None,
                    ),
                    prepared,
                )
        evidence = self._evidence_ref(
            grant,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            outcome=status.value,
        )
        if prepared_ref is not None:
            evidence = prepared_ref
        try:
            self.journal.record_effect(
                grant.effect_id, grant.fence, EffectState.COMPLETED, evidence
            )
        except JournalError:
            return (
                EffectResult(
                    DispatchStatus.RECONCILIATION_REQUIRED,
                    grant.effect_id,
                    grant.fence,
                    completed.returncode,
                    stdout,
                    stderr,
                    None,
                ),
                validation,
            )
        if status is DispatchStatus.DENIED:
            self._record_decision(
                BrokerDecision(
                    grant.request_digest,
                    False,
                    "worker-sandbox-denied",
                    self._clock(),
                    grant.capability,
                    grant.resource,
                    grant.run_id,
                    grant.run_revision,
                    self.policy.digest,
                )
            )
        return (
            EffectResult(
                status,
                grant.effect_id,
                grant.fence,
                completed.returncode,
                stdout,
                stderr,
                evidence,
            ),
            validation,
        )
