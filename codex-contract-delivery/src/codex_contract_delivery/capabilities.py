"""Deny-by-default capability grants and fenced argv-only dispatch."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
class CapabilityRequest:
    source: str
    capability: str
    resource: str
    operation: str

    def __post_init__(self) -> None:
        for name in ("source", "capability", "resource", "operation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    def canonical_record(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "source": self.source,
                "capability": self.capability,
                "resource": self.resource,
                "operation": self.operation,
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
        }


_TOP_LEVEL_FIELDS = frozenset({"schema_version", "policies"})
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
            if not Path(executable_realpath).is_file() or not os.access(
                executable_realpath, os.X_OK
            ):
                raise PolicyInvalid("allowed executable is not executable")
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
            resource_pattern = _validate_resource_pattern(raw["resource_pattern"])
            path_pattern = resource_pattern.removesuffix("/**")
            if operation != "read" and _is_path_resource(path_pattern) and not roots:
                raise PolicyInvalid(
                    "filesystem mutation policies require at least one allowed write root"
                )
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
                    tuple(dict.fromkeys(environment)),
                    tuple(dict.fromkeys(roots)),
                )
            )
        record = {
            "schema_version": "1.0",
            "policies": [rule.canonical_record() for rule in rules],
        }
        return cls("1.0", tuple(rules), canonical_digest(record))


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
    executable_realpath: str
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
            "executable_realpath": self.executable_realpath,
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
        }

    def verify_digest(self) -> bool:
        return self.grant_id == canonical_digest(self._content())


@dataclass(frozen=True)
class BrokerDecision:
    request_digest: str
    allowed: bool
    reason_code: str
    observed_at: datetime


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


class CapabilityBroker:
    """Issue bound grants and execute only exact argv vectors under journal fencing."""

    def __init__(
        self,
        policy: CapabilityPolicy,
        journal: Journal,
        *,
        clock: Callable[[], datetime] | None = None,
        process_runner: ProcessRunner = subprocess.run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy
        self.journal = journal
        self._clock = clock or _utc_now
        self._process_runner = process_runner
        self._environment = dict(os.environ if environment is None else environment)
        self._issued: dict[str, Grant] = {}
        self._decisions: list[BrokerDecision] = []

    @property
    def decisions(self) -> tuple[BrokerDecision, ...]:
        return tuple(self._decisions)

    def _deny(self, request_digest: str, code: str, message: str) -> None:
        self._decisions.append(
            BrokerDecision(request_digest, False, code, self._clock())
        )
        raise CapabilityDenied(message)

    def authorize(self, request: CapabilityRequest, context: RunContext) -> Grant:
        request_digest = canonical_digest(request.canonical_record())
        if request.source == "extension" and request.operation != "read":
            self._deny(
                request_digest,
                "untrusted-source-mutation",
                "extension payloads cannot request mutating capabilities",
            )
        try:
            _validate_resource(request.resource)
        except CapabilityDenied as error:
            self._deny(request_digest, "unsafe-resource", str(error))
        candidates = [
            rule
            for rule in self.policy.rules
            if rule.capability == request.capability
            and rule.operation == request.operation
        ]
        if not candidates:
            self._deny(
                request_digest, "unknown-capability", "capability is not allowed"
            )
        actor_candidates = [
            rule for rule in candidates if rule.actor_class == context.actor_class
        ]
        if not actor_candidates:
            self._deny(request_digest, "actor-mismatch", "actor class is not allowed")
        approval_candidates = [
            rule
            for rule in actor_candidates
            if rule.approval_digest == context.approval_digest
        ]
        if not approval_candidates:
            self._deny(
                request_digest,
                "approval-mismatch",
                "approval digest does not match policy",
            )
        state_candidates = [
            rule
            for rule in approval_candidates
            if rule.required_run_state is context.state
        ]
        if not state_candidates:
            self._deny(
                request_digest, "state-mismatch", "run state does not match policy"
            )
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
            self._deny(request_digest, "resource-mismatch", reason)
        rule = matches[0]
        snapshot = self.journal.get_run(context.run_id)
        if (
            snapshot is None
            or snapshot.revision != context.revision
            or snapshot.state is not context.state
        ):
            self._deny(
                request_digest,
                "run-context-drift",
                "run context does not match journal",
            )
        resource = request.resource
        if _is_path_resource(resource):
            try:
                resource = _canonical_path(resource)
            except CapabilityDenied as error:
                self._deny(request_digest, "unsafe-resource", str(error))
        if (
            request.operation != "read"
            and _is_path_resource(resource)
            and not any(_within(resource, root) for root in rule.allowed_write_roots)
        ):
            self._deny(
                request_digest, "write-scope", "resource is outside allowed write roots"
            )
        try:
            lease = self.journal.acquire_attempt(
                context.run_id,
                context.effect_id,
                context.worker_id,
                timedelta(seconds=rule.timeout_seconds + 5),
            )
            lease.assert_dispatch_allowed()
        except ReconciliationRequired:
            self._deny(
                request_digest,
                "reconciliation-required",
                "effect requires reconciliation",
            )
        except JournalError as error:
            self._deny(
                request_digest,
                "journal-authority",
                f"journal denied authority: {type(error).__name__}",
            )
        issued_at = self._clock()
        content: dict[str, Any] = {
            "request_digest": request_digest,
            "policy_digest": self.policy.digest,
            "policy_id": rule.policy_id,
            "capability": request.capability,
            "operation": request.operation,
            "resource": resource,
            "actor_class": context.actor_class,
            "allowed_argv_prefix": rule.allowed_argv_prefix,
            "executable_realpath": rule.allowed_argv_prefix[0],
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
            "expires_at": issued_at + timedelta(seconds=rule.timeout_seconds),
        }
        provisional = Grant("", **content)
        grant = Grant(canonical_digest(provisional._content()), **content)
        self._issued[grant.grant_id] = grant
        self._decisions.append(
            BrokerDecision(request_digest, True, "authorized", issued_at)
        )
        return grant

    def _validate_grant(self, grant: Grant) -> None:
        if not isinstance(grant, Grant) or not grant.verify_digest():
            self._deny("invalid-grant", "grant-digest", "grant digest is invalid")
        if self._issued.get(grant.grant_id) != grant:
            self._deny(
                grant.request_digest,
                "grant-not-issued",
                "grant was not issued by this broker",
            )
        if grant.policy_digest != self.policy.digest:
            self._deny(
                grant.request_digest, "policy-drift", "capability policy changed"
            )
        now = self._clock()
        if now >= grant.expires_at:
            self._deny(grant.request_digest, "grant-expired", "grant expired")
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

    def _validate_argv(self, grant: Grant, argv: Sequence[str]) -> tuple[str, ...]:
        if isinstance(argv, str | bytes):
            self._deny(
                grant.request_digest, "argv-type", "argv must be a sequence of strings"
            )
        materialized = tuple(argv)
        if not materialized:
            self._deny(grant.request_digest, "argv-empty", "argv cannot be empty")
        if any(not isinstance(item, str) for item in materialized):
            self._deny(
                grant.request_digest, "argv-type", "every argv item must be a string"
            )
        if any(not _safe_argv_item(item) for item in materialized):
            self._deny(
                grant.request_digest,
                "argv-shell-syntax",
                "argv contains shell syntax or expansion",
            )
        prefix = grant.allowed_argv_prefix
        if materialized[: len(prefix)] != prefix:
            self._deny(
                grant.request_digest,
                "argv-prefix",
                "argv does not match the allowed prefix",
            )
        try:
            executable = str(Path(materialized[0]).resolve(strict=True))
        except OSError:
            self._deny(
                grant.request_digest, "unknown-executable", "executable is unavailable"
            )
        if executable != grant.executable_realpath or not os.access(
            executable, os.X_OK
        ):
            self._deny(
                grant.request_digest,
                "unknown-executable",
                "executable identity changed",
            )
        return materialized

    def _child_environment(self, grant: Grant) -> dict[str, str]:
        environment = {
            name: self._environment[name]
            for name in grant.allowed_environment_names
            if name in self._environment and not _is_sensitive_environment_name(name)
        }
        environment["CDD_IDEMPOTENCY_KEY"] = grant.effect_id
        environment["CDD_EFFECT_FENCE"] = str(grant.fence)
        return environment

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

    def _dispatch(
        self,
        grant: Grant,
        argv: Sequence[str],
        *,
        stdin_text: str | None = None,
        result_validator: ResultValidator | None = None,
    ) -> tuple[EffectResult, object | None]:
        self._validate_grant(grant)
        command = self._validate_argv(grant, argv)
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
        try:
            completed = self._process_runner(
                command,
                input=stdin_text,
                cwd=cwd,
                env=self._child_environment(grant),
                timeout=grant.timeout_seconds,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
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
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        validation: object | None = None
        try:
            if result_validator is not None:
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
            raise
        evidence = self._evidence_ref(
            grant,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            outcome="process-exited",
        )
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
        return (
            EffectResult(
                DispatchStatus.COMPLETED,
                grant.effect_id,
                grant.fence,
                completed.returncode,
                stdout,
                stderr,
                evidence,
            ),
            validation,
        )
