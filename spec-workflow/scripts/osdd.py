#!/usr/bin/env python3
"""OpenSpec/Superpowers 确定性 workflow gate。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASS = 0
FAIL = 1
USAGE = 2

SUPERPOWER_SKILLS = {
    "brainstorming": "superpowers:brainstorming",
    "writing-plans": "superpowers:writing-plans",
    "subagent-driven-development": "superpowers:subagent-driven-development",
    "test-driven-development": "superpowers:test-driven-development",
}

PROPOSAL_MARKER = "<!-- spec-workflow: superpowers=brainstorming -->"
DESIGN_MARKER = "<!-- spec-workflow: superpowers=brainstorming -->"
TASKS_MARKER = "<!-- spec-workflow: superpowers=writing-plans -->"
PENPOT_STATUSES = {"linked", "import-ready", "not-applicable"}
DESIGN_REVIEW_STATUSES = {"pending", "changes-requested", "approved"}
AUDIT_VERSION = "v1"
BUSINESS_EXTENSIONS = {
    ".go", ".java", ".kt", ".kts", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".vue", ".svelte", ".rb", ".php", ".rs", ".cs", ".sql",
}
UI_HINT_RE = re.compile(r"(frontend|src/.+\.(tsx|jsx|vue|svelte|css|scss)$|app/.+\.(tsx|jsx)$|pages/.+\.(tsx|jsx)$|components/)", re.I)
GOVERNANCE_TEST_FILES = {
    "tests/test_spec_workflow_gate.py",
}


@dataclass
class CheckResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def emit(result: CheckResult | dict[str, Any], args: argparse.Namespace, default_label: str = "result") -> int:
    if isinstance(result, CheckResult):
        payload = {
            "ok": result.ok,
            "errors": result.errors,
            "warnings": result.warnings,
            **result.data,
        }
        code = PASS if result.ok else FAIL
    else:
        payload = result
        code = PASS if payload.get("ok", True) else FAIL
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        ok = payload.get("ok", True)
        print(f"{default_label}: {'pass' if ok else 'fail'}")
        for key, value in payload.items():
            if key in {"ok", "errors", "warnings"}:
                continue
            if isinstance(value, (dict, list)):
                print(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
            else:
                print(f"{key}: {value}")
        for warning in payload.get("warnings", []):
            print(f"warning: {warning}", file=sys.stderr)
        for error in payload.get("errors", []):
            print(f"error: {error}", file=sys.stderr)
    return code


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def check_command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def write_file_if_missing(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def copy_asset_if_missing(asset_name: str, target_path: Path) -> bool:
    source = find_skill_root() / "assets" / asset_name
    if not source.exists():
        raise FileNotFoundError(f"asset not found: {source}")
    return write_file_if_missing(target_path, source.read_text(encoding="utf-8"))


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / ".git").exists() or (path / "openspec").exists():
            return path
    return current


def find_skill_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[1]


def safe_change_name(change: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", change or ""):
        raise ValueError("change must contain only letters, numbers, dot, underscore, or hyphen and not start with punctuation")
    if ".." in change or "/" in change or "\\" in change:
        raise ValueError("change must be a single safe directory name")
    return change


def find_change_dir(change: str, repo_root: Path | None = None) -> Path:
    return (repo_root or find_repo_root()) / "openspec" / "changes" / safe_change_name(change)


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = read_text(path)
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    result: dict[str, str] = {}
    for raw in text[3:end].splitlines():
        if ":" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def parse_frontmatter_status(path: Path) -> str:
    return parse_frontmatter(path).get("status", "missing" if not path.exists() else "unknown")


def detect_project_types(repo_root: Path) -> list[str]:
    mapping = [
        ("package.json", "node"),
        ("go.mod", "go"),
        ("pom.xml", "java"),
        ("build.gradle", "java-kotlin"),
        ("build.gradle.kts", "java-kotlin"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
    ]
    found: list[str] = []
    for marker, kind in mapping:
        if list(repo_root.rglob(marker)):
            if kind not in found:
                found.append(kind)
    return found


def detect_changed_files(repo_root: Path) -> list[str]:
    commands = [
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    files: list[str] = []
    if not (repo_root / ".git").exists() or not check_command_exists("git"):
        return files
    for cmd in commands:
        cp = run(cmd, repo_root)
        if cp.returncode == 0:
            files.extend(cp.stdout.splitlines())
    return sorted(set(file for file in files if file))


def is_ui_change(change_dir: Path, changed_files: list[str]) -> bool:
    if (change_dir / "artifacts" / "prototype.html").exists() or (change_dir / "artifacts" / "design-review.md").exists():
        return True
    return any(UI_HINT_RE.search(f) for f in changed_files)


def detect_ui_level(change_dir: Path, changed_files: list[str]) -> str:
    meta = parse_frontmatter(change_dir / "artifacts" / "design-review.md")
    explicit = meta.get("ui_level") or parse_frontmatter(change_dir / "artifacts" / "penpot.md").get("ui_level")
    if explicit in {"none", "minor", "major"}:
        return explicit
    text = "\n".join(read_text(change_dir / name) for name in ("proposal.md", "design.md", "tasks.md")).lower()
    if "ui-level: major" in text or "ui level: major" in text or "ui / ux design" in text:
        return "major"
    if "ui-level: minor" in text or "ui level: minor" in text:
        return "minor"
    if (change_dir / "artifacts" / "prototype.html").exists() or (change_dir / "artifacts" / "penpot.md").exists():
        return "major"
    if is_ui_change(change_dir, changed_files):
        return "unknown"
    return "none"


def detect_superpowers() -> dict[str, bool]:
    candidates: list[Path] = []
    for env_name in ("SUPERPOWERS_HOME", "SUPERPOWERS_SKILL_PATH"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).expanduser())
    home = Path.home()
    candidates.extend([
        home / ".skills",
        home / ".agents" / "skills",
        home / ".agents" / "skills" / "superpowers",
        Path.cwd() / ".agents" / "skills",
        Path.cwd() / ".agents" / "skills" / "superpowers",
        home / ".codex" / "skills",
        Path.cwd() / ".codex" / "skills",
        home / ".codex" / "plugins" / "cache" / "openai-curated-remote" / "superpowers",
    ])
    text_cache: dict[Path, str] = {}

    def has_skill(slug: str) -> bool:
        for root in candidates:
            if not root.exists():
                continue
            possible = [
                root / slug / "SKILL.md",
                root / "skills" / slug / "SKILL.md",
                root / "5.1.4" / "skills" / slug / "SKILL.md",
            ]
            if any(p.exists() for p in possible):
                return True
            for md in list(root.glob(f"**/{slug}/SKILL.md"))[:5]:
                if md.exists():
                    return True
            for md in list(root.glob("**/SKILL.md"))[:250]:
                if md not in text_cache:
                    text_cache[md] = read_text(md)[:800]
                if slug in text_cache[md]:
                    return True
        if check_command_exists("superpowers"):
            cp = run(["superpowers", "list"])
            return cp.returncode == 0 and slug in cp.stdout
        return False

    found = {slug: has_skill(slug) for slug in SUPERPOWER_SKILLS}
    found["superpowers"] = any(found.values()) or check_command_exists("superpowers")
    return found


def check_superpowers_skills(result: CheckResult, required: list[str] | None = None) -> dict[str, bool]:
    found = detect_superpowers()
    for slug in (required or list(SUPERPOWER_SKILLS)):
        if not found.get(slug):
            result.fail(f"Superpowers {slug} missing")
    return found


def check_codegraph() -> bool:
    if check_command_exists("codegraph"):
        return True
    return (Path.cwd() / ".codegraph").exists()


def check_lsp_for_project_types(project_types: list[str]) -> dict[str, bool]:
    checks: dict[str, list[str]] = {
        "go": ["gopls"],
        "node": ["typescript-language-server", "tsserver"],
        "python": ["pyright"],
        "java": ["jdtls", "javac", "mvn", "gradle"],
        "java-kotlin": ["jdtls", "javac", "mvn", "gradle", "kotlin-language-server"],
    }
    return {kind: any(check_command_exists(cmd) for cmd in checks.get(kind, [])) for kind in project_types}


def has_section(text: str, names: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"^#+\s+.*{re.escape(name.lower())}", lowered, re.M) or name.lower() in lowered for name in names)


def has_checklist(text: str) -> bool:
    return bool(re.search(r"- \[[ xX]\]", text))


def has_delta_specs(change_dir: Path) -> bool:
    specs = change_dir / "specs"
    return specs.exists() and any(p.name.endswith(".md") for p in specs.rglob("*.md"))


def penpot_status(change_dir: Path) -> str:
    status = parse_frontmatter_status(change_dir / "artifacts" / "penpot.md")
    return status if status in PENPOT_STATUSES else ("invalid" if status not in {"missing", "unknown"} else status)


def code_review_blocking(change_dir: Path) -> int | None:
    path = change_dir / "artifacts" / "code-review.md"
    if not path.exists():
        return None
    fm = parse_frontmatter(path)
    try:
        return int(fm.get("blocking_findings", "0"))
    except ValueError:
        return 1


def validate_superpowers_audit(path: Path, expected_skill: str, target: str, required_sections: list[str]) -> list[str]:
    errors: list[str] = []
    text = read_text(path)
    label = str(path)
    if not path.exists():
        return [f"missing {label}"]
    fm = parse_frontmatter(path)
    if fm.get("spec_workflow_audit") != AUDIT_VERSION:
        errors.append(f"{label} missing spec_workflow_audit: {AUDIT_VERSION}")
    if fm.get("skill") != expected_skill:
        errors.append(f"{label} must declare skill: {expected_skill}")
    if fm.get("target") != target:
        errors.append(f"{label} must declare target: {target}")
    if fm.get("status") != "completed":
        errors.append(f"{label} must declare status: completed")
    if fm.get("transcript_captured") != "true":
        errors.append(f"{label} must declare transcript_captured: true")
    lower = text.lower()
    for bad in ("todo", "placeholder", "fill in", "lorem ipsum"):
        if bad in lower:
            errors.append(f"{label} contains placeholder text: {bad}")
    for section in required_sections:
        if not has_section(text, [section]):
            errors.append(f"{label} missing section {section}")
    if expected_skill not in text:
        errors.append(f"{label} body must name {expected_skill}")
    if not re.search(r"(?im)^(user|assistant|codex|human|agent):\s+\S", text):
        errors.append(f"{label} must include raw interaction transcript lines")
    if len(re.findall(r"(?m)^##\s+", text)) < len(required_sections):
        errors.append(f"{label} does not contain enough audit sections")
    if len(text.strip()) < 700:
        errors.append(f"{label} is too short to be credible workflow evidence")
    return errors


def validate_workflow_evidence(
    path: Path,
    expected_kind: str,
    target: str,
    required_sections: list[str],
    expected_skill: str | None = None,
    min_length: int = 500,
) -> list[str]:
    errors: list[str] = []
    text = read_text(path)
    label = str(path)
    if not path.exists():
        return [f"missing {label}"]
    fm = parse_frontmatter(path)
    if fm.get("spec_workflow_evidence") != AUDIT_VERSION:
        errors.append(f"{label} missing spec_workflow_evidence: {AUDIT_VERSION}")
    if fm.get("kind") != expected_kind:
        errors.append(f"{label} must declare kind: {expected_kind}")
    if fm.get("target") != target:
        errors.append(f"{label} must declare target: {target}")
    if expected_skill and fm.get("skill") != expected_skill:
        errors.append(f"{label} must declare skill: {expected_skill}")
    if fm.get("status") != "completed":
        errors.append(f"{label} must declare status: completed")
    if fm.get("transcript_captured") != "true":
        errors.append(f"{label} must declare transcript_captured: true")
    lower = text.lower()
    for bad in ("todo", "placeholder", "fill in", "lorem ipsum"):
        if bad in lower:
            errors.append(f"{label} contains placeholder text: {bad}")
    for section in required_sections:
        if not has_section(text, [section]):
            errors.append(f"{label} missing section {section}")
    if not re.search(r"(?im)^(user|assistant|codex|human|agent|\$|[+])[: ]\s*\S", text):
        errors.append(f"{label} must include raw transcript or command lines")
    if len(text.strip()) < min_length:
        errors.append(f"{label} is too short to be credible workflow evidence")
    return errors


def check_command_evidence(change_dir: Path, phase: str) -> list[str]:
    path = change_dir / "artifacts" / "workflow-commands.md"
    errors = validate_workflow_evidence(
        path,
        "openspec-cli",
        "workflow-commands",
        ["Required command invocation", "Raw command transcript", "Commands run", "Results"],
    )
    text = read_text(path)
    required_tokens = ["/opsx:propose"]
    if phase in {"before-apply", "after-apply", "ci"}:
        required_tokens.append("gate")
        required_tokens.append("--phase planning")
    if phase in {"after-apply", "ci"}:
        required_tokens.extend(["/opsx:apply", "--phase before-apply"])
    for token in required_tokens:
        if token not in text:
            errors.append(f"{path} missing command evidence token: {token}")
    return errors


def check_retrieval_evidence(change_dir: Path) -> list[str]:
    return validate_workflow_evidence(
        change_dir / "artifacts" / "retrieval.md",
        "codegraph-lsp",
        "implementation-retrieval",
        ["Required retrieval invocation", "Raw interaction transcript", "CodeGraph or LSP entrypoints", "Symbols references or tests found", "Scope decisions"],
    )


def check_code_review_evidence(change_dir: Path) -> list[str]:
    return validate_workflow_evidence(
        change_dir / "artifacts" / "code-review.md",
        "skill-invocation",
        "code-review",
        ["Required skill invocation", "Raw interaction transcript", "Scope reviewed", "Findings", "Blocking findings", "Tests and validation reviewed"],
        expected_skill="code-review-and-quality",
    )


def check_superpowers_planning_audits(change_dir: Path) -> list[str]:
    base = change_dir / "artifacts" / "superpowers"
    checks = [
        (base / "brainstorm-proposal.md", "superpowers:brainstorming", "proposal.md", ["Required skill invocation", "Raw interaction transcript", "Explored options", "Decisions", "Resulting updates"]),
        (base / "brainstorm-design.md", "superpowers:brainstorming", "design.md", ["Required skill invocation", "Raw interaction transcript", "Explored options", "Trade-offs", "Decisions", "Resulting updates"]),
        (base / "write-plan-tasks.md", "superpowers:writing-plans", "tasks.md", ["Required skill invocation", "Raw interaction transcript", "Plan structure", "Task ordering rationale", "Validation steps", "Resulting updates"]),
    ]
    errors: list[str] = []
    for path, skill, target, sections in checks:
        errors.extend(validate_superpowers_audit(path, skill, target, sections))
    return errors


def check_implementation_audit(change_dir: Path) -> list[str]:
    return validate_superpowers_audit(
        change_dir / "artifacts" / "superpowers" / "subagent-implementation.md",
        "superpowers:subagent-driven-development",
        "implementation",
        ["Required skill invocation", "Raw interaction transcript", "Implementation slices", "Retrieval entrypoints", "Completion evidence"],
    )


def check_tdd_audit(change_dir: Path) -> list[str]:
    return validate_superpowers_audit(
        change_dir / "artifacts" / "superpowers" / "tdd-log.md",
        "superpowers:test-driven-development",
        "behavior-changing code",
        ["Required skill invocation", "Raw interaction transcript", "Failing test", "Implementation", "Passing test", "Validation commands"],
    )


def check_planning_gate(change_dir: Path) -> CheckResult:
    result = CheckResult(data={"phase": "planning", "change": change_dir.name})
    proposal = change_dir / "proposal.md"
    design = change_dir / "design.md"
    tasks = change_dir / "tasks.md"
    artifacts = change_dir / "artifacts"
    for path in (proposal, design, tasks):
        if not path.exists():
            result.fail(f"missing {path.relative_to(change_dir)}")
    if not has_delta_specs(change_dir):
        result.fail("missing openspec delta specs under specs/")
    proposal_text = read_text(proposal)
    design_text = read_text(design)
    tasks_text = read_text(tasks)
    for section in ("Goals", "Non-goals", "Impact", "Open Questions"):
        if not has_section(proposal_text, [section]):
            result.fail(f"proposal.md missing {section}")
    if not has_section(design_text, ["Technical Design", "技术设计"]):
        result.fail("design.md missing Technical Design")
    if not has_checklist(tasks_text):
        result.fail("tasks.md missing checklist")
    required_artifacts = {
        "artifacts/superpowers/brainstorm-proposal.md": artifacts / "superpowers" / "brainstorm-proposal.md",
        "artifacts/superpowers/brainstorm-design.md": artifacts / "superpowers" / "brainstorm-design.md",
        "artifacts/superpowers/write-plan-tasks.md": artifacts / "superpowers" / "write-plan-tasks.md",
    }
    for label, path in required_artifacts.items():
        if not path.exists():
            result.fail(f"missing {label}")
    for error in check_superpowers_planning_audits(change_dir):
        result.fail(error)
    for error in check_command_evidence(change_dir, "planning"):
        result.fail(error)
    if PROPOSAL_MARKER not in proposal_text:
        result.fail("proposal.md missing brainstorming marker")
    if DESIGN_MARKER not in design_text:
        result.fail("design.md missing brainstorming marker")
    if TASKS_MARKER not in tasks_text:
        result.fail("tasks.md missing writing-plans marker")
    ui_level = detect_ui_level(change_dir, [])
    result.data["ui_level"] = ui_level
    if ui_level == "major":
        if not has_section(design_text, ["UI / UX Design"]):
            result.fail("major UI change requires UI / UX Design section")
        for label in ("prototype.html", "penpot.md", "design-review.md"):
            if not (artifacts / label).exists():
                result.fail(f"major UI change missing artifacts/{label}")
        if not re.search(r"design review|设计 review|设计评审", tasks_text, re.I):
            result.fail("major UI tasks must include design review before implementation")
    return result


def validation_skip_reason(change_dir: Path) -> bool:
    text = read_text(change_dir / "artifacts" / "validation.md")
    return "LSP skip reason" in text or "lsp skip reason" in text.lower()


def penpot_not_applicable_reason(change_dir: Path) -> bool:
    tasks = read_text(change_dir / "tasks.md").lower()
    penpot = read_text(change_dir / "artifacts" / "penpot.md").lower()
    patterns = (
        "penpot not-applicable reason",
        "penpot not applicable reason",
        "penpot reason",
        "not-applicable reason",
        "not applicable reason",
        "penpot 不适用原因",
        "penpot 不适用",
    )
    return any(pattern in tasks or pattern in penpot for pattern in patterns)


def check_before_apply_gate(change_dir: Path, repo_root: Path | None = None, require_local_tools: bool = True) -> CheckResult:
    repo_root = repo_root or find_repo_root()
    result = check_planning_gate(change_dir)
    result.data["phase"] = "before-apply"
    found = (
        check_superpowers_skills(result, ["subagent-driven-development", "test-driven-development"])
        if require_local_tools
        else detect_superpowers()
    )
    result.data["superpowers"] = found
    if not (change_dir / "artifacts" / "superpowers" / "subagent-implementation.md").exists():
        result.fail("missing artifacts/superpowers/subagent-implementation.md")
    for error in check_implementation_audit(change_dir):
        result.fail(error)
    for error in check_command_evidence(change_dir, "before-apply"):
        result.fail(error)
    for error in check_retrieval_evidence(change_dir):
        result.fail(error)
    if require_local_tools and not check_codegraph():
        result.fail("CodeGraph missing; install/index codegraph or record a supported retrieval setup")
    project_types = detect_project_types(repo_root)
    lsp = check_lsp_for_project_types(project_types)
    result.data["project_types"] = project_types
    result.data["lsp"] = lsp
    if any(not ok for ok in lsp.values()) and not validation_skip_reason(change_dir):
        result.fail("LSP missing for detected project type; add LSP or write LSP skip reason to artifacts/validation.md")
    ui_level = result.data.get("ui_level") or detect_ui_level(change_dir, [])
    if ui_level in {"minor", "major", "unknown"}:
        if not (change_dir / "artifacts" / "prototype.html").exists():
            result.fail("UI change missing artifacts/prototype.html")
        review_status = parse_frontmatter_status(change_dir / "artifacts" / "design-review.md")
        result.data["design_review_status"] = review_status
        if review_status != "approved":
            result.fail("design-review.md status must be approved by a human before implementation")
    if ui_level == "major":
        ps = penpot_status(change_dir)
        result.data["penpot_status"] = ps
        if ps not in {"linked", "import-ready"}:
            result.fail("major UI change requires penpot.md status linked or import-ready")
    if ui_level == "minor":
        ps = penpot_status(change_dir)
        result.data["penpot_status"] = ps
        if ps == "not-applicable" and not penpot_not_applicable_reason(change_dir):
            result.fail("minor UI change with penpot.md status not-applicable requires a reason in tasks.md or penpot.md")
    return result


def task_completion_ok(text: str) -> bool:
    checks = re.findall(r"- \[([ xX])\].*", text)
    return bool(checks) and all(c.lower() == "x" for c in checks)


def check_after_apply_gate(change_dir: Path) -> CheckResult:
    result = CheckResult(data={"phase": "after-apply", "change": change_dir.name})
    tasks_text = read_text(change_dir / "tasks.md")
    if not task_completion_ok(tasks_text):
        result.fail("tasks.md implementation checklist is not fully complete")
    validation = read_text(change_dir / "artifacts" / "validation.md")
    validation_l = validation.lower()
    for word in ("test", "lint", "typecheck"):
        if word not in validation_l and word not in tasks_text.lower():
            result.fail(f"missing validation evidence for {word}")
    subagent = change_dir / "artifacts" / "superpowers" / "subagent-implementation.md"
    tdd = change_dir / "artifacts" / "superpowers" / "tdd-log.md"
    if not subagent.exists():
        result.fail("missing artifacts/superpowers/subagent-implementation.md")
    if not tdd.exists():
        result.fail("missing artifacts/superpowers/tdd-log.md")
    for error in check_tdd_audit(change_dir):
        result.fail(error)
    tdd_text = read_text(tdd)
    for required in ("Failing test", "Implementation", "Passing test", "Validation commands"):
        if required.lower() not in tdd_text.lower():
            result.fail(f"tdd-log.md missing {required}")
    ui_level = detect_ui_level(change_dir, [])
    if ui_level in {"minor", "major", "unknown"}:
        if "Screenshot or visual validation".lower() not in tdd_text.lower() and not (change_dir / "artifacts" / "screenshots").exists() and "visual" not in validation_l:
            result.fail("UI change missing screenshot or visual validation evidence")
    blocking = code_review_blocking(change_dir)
    result.data["blocking_findings"] = blocking
    if blocking is None:
        result.fail("missing artifacts/code-review.md")
    elif blocking > 0:
        result.fail("code-review.md has unresolved blocking findings")
    for error in check_command_evidence(change_dir, "after-apply"):
        result.fail(error)
    for error in check_retrieval_evidence(change_dir):
        result.fail(error)
    for error in check_code_review_evidence(change_dir):
        result.fail(error)
    return result


def changed_open_spec_changes(changed_files: list[str]) -> list[str]:
    names: set[str] = set()
    for file in changed_files:
        parts = Path(file).parts
        if len(parts) < 4 or parts[0:2] != ("openspec", "changes"):
            continue
        change_name = parts[2]
        if change_name == "archive":
            continue
        names.add(change_name)
    return sorted(names)


def production_changed_files(changed_files: list[str]) -> list[str]:
    result = []
    for file in changed_files:
        path = Path(file)
        if file in GOVERNANCE_TEST_FILES:
            continue
        if file.startswith(("openspec/", ".github/", "docs/", "requirements/")):
            continue
        if path.suffix in BUSINESS_EXTENSIONS:
            result.append(file)
    return result


def check_ci_gate(repo_root: Path, changed_files: list[str], explicit_change: str | None = None) -> CheckResult:
    result = CheckResult(data={"phase": "ci", "changed_files": changed_files})
    changes = [explicit_change] if explicit_change else changed_open_spec_changes(changed_files)
    production_files = production_changed_files(changed_files)
    if not changes and (production_files or any(UI_HINT_RE.search(f) for f in changed_files)):
        result.fail("business or UI files changed without an associated openspec/changes/<change>/ entry")
        return result
    for change in changes:
        change_dir = find_change_dir(change, repo_root)
        before = check_before_apply_gate(change_dir, repo_root, require_local_tools=False)
        after = check_after_apply_gate(change_dir)
        if not before.ok:
            result.fail(f"{change}: before-apply gate failed: {'; '.join(before.errors)}")
        if production_files and not (change_dir / "artifacts" / "superpowers" / "tdd-log.md").exists():
            result.fail(f"{change}: production code changed but tdd-log.md is missing")
        if not (change_dir / "artifacts" / "code-review.md").exists():
            result.fail(f"{change}: code-review.md missing")
        blocking = code_review_blocking(change_dir)
        if blocking and blocking > 0:
            result.fail(f"{change}: code-review.md has blocking findings")
        if not after.ok:
            result.fail(f"{change}: after-apply gate failed: {'; '.join(after.errors)}")
    if not changed_files:
        result.warn("no changed files detected; CI gate checked no changes")
    return result


def status_payload(change_dir: Path, repo_root: Path) -> dict[str, Any]:
    artifacts = change_dir / "artifacts"
    changed = detect_changed_files(repo_root)
    proposal = read_text(change_dir / "proposal.md")
    design = read_text(change_dir / "design.md")
    tasks = read_text(change_dir / "tasks.md")
    superpowers = detect_superpowers()
    audit = {
        "brainstorm-proposal.md": (artifacts / "superpowers" / "brainstorm-proposal.md").exists(),
        "brainstorm-design.md": (artifacts / "superpowers" / "brainstorm-design.md").exists(),
        "write-plan-tasks.md": (artifacts / "superpowers" / "write-plan-tasks.md").exists(),
        "subagent-implementation.md": (artifacts / "superpowers" / "subagent-implementation.md").exists(),
        "tdd-log.md": (artifacts / "superpowers" / "tdd-log.md").exists(),
    }
    markers = {
        "proposal.md brainstorming marker": PROPOSAL_MARKER in proposal,
        "design.md brainstorming marker": DESIGN_MARKER in design,
        "tasks.md writing-plans marker": TASKS_MARKER in tasks,
    }
    planning = check_planning_gate(change_dir)
    before = check_before_apply_gate(change_dir, repo_root) if change_dir.exists() else CheckResult(ok=False, errors=["change missing"])
    return {
        "ok": change_dir.exists(),
        "change": change_dir.name,
        "change_exists": change_dir.exists(),
        "proposal.md": (change_dir / "proposal.md").exists(),
        "design.md": (change_dir / "design.md").exists(),
        "tasks.md": (change_dir / "tasks.md").exists(),
        "delta_specs": has_delta_specs(change_dir),
        "ui_level": detect_ui_level(change_dir, changed),
        "prototype.html": (artifacts / "prototype.html").exists(),
        "penpot.md": {"exists": (artifacts / "penpot.md").exists(), "status": penpot_status(change_dir)},
        "design-review.md": {"exists": (artifacts / "design-review.md").exists(), "status": parse_frontmatter_status(artifacts / "design-review.md")},
        "code-review.md": {"exists": (artifacts / "code-review.md").exists(), "blocking_findings": code_review_blocking(change_dir)},
        "superpowers": superpowers,
        "audit": audit,
        "markers": markers,
        "implementation_allowed": before.ok,
        "failed_gates": [name for name, gate in (("planning", planning), ("before-apply", before)) if not gate.ok],
        "errors": planning.errors + before.errors,
        "warnings": planning.warnings + before.warnings,
        "next_suggested_action": "rerun autopilot and let Codex execute assistant_actions",
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    result = CheckResult(data={"repo_root": str(repo), "checks": {}})
    checks = result.data["checks"]
    for cmd in ("python3", "git"):
        checks[cmd] = check_command_exists(cmd)
        if not checks[cmd]:
            result.fail(f"{cmd} missing")
    checks["openspec_or_opsx"] = check_command_exists("openspec") or check_command_exists("opsx")
    if not checks["openspec_or_opsx"]:
        result.fail("openspec or opsx command missing")
    sp = detect_superpowers()
    checks["Superpowers"] = sp.get("superpowers", False)
    print_map = {
        "Superpowers brainstorming": "brainstorming",
        "Superpowers writing-plans": "writing-plans",
        "Superpowers subagent-driven-development": "subagent-driven-development",
        "Superpowers test-driven-development": "test-driven-development",
    }
    for label, slug in print_map.items():
        checks[label] = sp.get(slug, False)
        if not checks[label]:
            result.fail(f"{label} missing")
    project_types = detect_project_types(repo)
    checks["project_types"] = project_types
    checks["codegraph"] = check_codegraph()
    if not checks["codegraph"]:
        result.fail("codegraph missing")
    checks["lsp"] = check_lsp_for_project_types(project_types)
    checks["node"] = check_command_exists("node")
    checks["package_manager"] = any(check_command_exists(c) for c in ("npm", "pnpm", "yarn"))
    checks["playwright"] = check_command_exists("playwright") or (repo / "node_modules" / ".bin" / "playwright").exists()
    if args.install:
        install_attempts = []
        if (repo / "package.json").exists():
            for lock, cmd in (("pnpm-lock.yaml", ["pnpm", "install"]), ("yarn.lock", ["yarn", "install", "--frozen-lockfile"]), ("package-lock.json", ["npm", "ci"])):
                if (repo / lock).exists() and check_command_exists(cmd[0]):
                    print("+ " + " ".join(cmd))
                    install_attempts.append(" ".join(cmd))
                    cp = run(cmd, repo)
                    if cp.returncode != 0:
                        result.fail(f"install failed: {' '.join(cmd)}\n{cp.stderr}")
                    break
            if check_command_exists("npx"):
                cmd = ["npx", "playwright", "install"]
                print("+ " + " ".join(cmd))
                install_attempts.append(" ".join(cmd))
                cp = run(cmd, repo)
                if cp.returncode != 0:
                    result.warn(f"playwright install failed: {cp.stderr.strip()}")
        result.data["install_attempts"] = install_attempts
    return emit(result, args, "doctor")


def cmd_init(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    created, skipped = init_repo_files(repo)
    result = CheckResult(data={"created": created, "skipped_existing": skipped, "repo_root": str(repo)})
    if args.install:
        doctor_args = argparse.Namespace(json=args.json, install=True)
        code = cmd_doctor(doctor_args)
        if code != 0:
            result.fail("doctor --install failed")
    return emit(result, args, "init")


def init_repo_files(repo: Path) -> tuple[list[str], list[str]]:
    created: list[str] = []
    skipped: list[str] = []
    targets = {
        repo / ".github" / "workflows" / "spec-workflow-gate.yml": read_text(find_skill_root() / "assets" / "github-workflow.template.yml"),
        repo / ".github" / "codex" / "prompts" / "spec-workflow-review.md": read_text(find_skill_root() / "assets" / "codex-review-prompt.template.md"),
        repo / ".github" / "spec-workflow" / "osdd.py": read_text(Path(__file__).resolve()),
    }
    for path, content in targets.items():
        if write_file_if_missing(path, content):
            created.append(str(path.relative_to(repo)))
        else:
            skipped.append(str(path.relative_to(repo)))
    return created, skipped


def cmd_new(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    change_dir, created, ui_level = scaffold_change(repo, args.change, args.ui, args.ui_level)
    result = CheckResult(data={"change": args.change, "change_dir": str(change_dir), "ui_level": ui_level, "created": created, "fullstack": args.fullstack})
    return emit(result, args, "new")


def scaffold_change(repo: Path, change: str, ui: bool = False, ui_level: str = "none") -> tuple[Path, list[str], str]:
    change_dir = find_change_dir(change, repo)
    artifacts = change_dir / "artifacts"
    (artifacts / "superpowers").mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for asset, rel in (
        ("workflow-commands.template.md", "artifacts/workflow-commands.md"),
        ("retrieval.template.md", "artifacts/retrieval.md"),
    ):
        target = change_dir / rel
        if copy_asset_if_missing(asset, target):
            created.append(rel)
    ui_level = "major" if ui else ui_level
    if ui_level in {"minor", "major"}:
        for asset, rel in (
            ("prototype.template.html", "artifacts/prototype.html"),
            ("penpot.template.md", "artifacts/penpot.md"),
            ("design-review.template.md", "artifacts/design-review.md"),
        ):
            target = change_dir / rel
            if copy_asset_if_missing(asset, target):
                created.append(rel)
    return change_dir, created, ui_level


def autopilot_payload(args: argparse.Namespace) -> dict[str, Any]:
    repo = find_repo_root()
    init_created: list[str] = []
    init_skipped: list[str] = []
    if not args.no_init:
        init_created, init_skipped = init_repo_files(repo)
    change_dir, scaffold_created, requested_ui_level = scaffold_change(repo, args.change, args.ui, args.ui_level)
    changed = detect_changed_files(repo)
    detected_ui_level = detect_ui_level(change_dir, changed)
    ui_level = requested_ui_level if requested_ui_level != "none" else detected_ui_level
    planning = check_planning_gate(change_dir)
    before = check_before_apply_gate(change_dir, repo) if change_dir.exists() else CheckResult(ok=False, errors=["change missing"])
    after = check_after_apply_gate(change_dir) if change_dir.exists() else CheckResult(ok=False, errors=["change missing"])
    assistant_actions: list[str]
    human_actions: list[str] = []
    stage: str
    blocked_by: list[str]

    if not planning.ok:
        stage = "planning"
        assistant_actions = [
            f"Codex 调用 `/opsx:propose {args.change}`；如果当前运行时没有 slash command 能力，必须报告能力缺失，不能手写替代流程。",
            "Codex 加载 `superpowers:brainstorming`，通过真实 brainstorming 流程产出 `proposal.md` 和 `artifacts/superpowers/brainstorm-proposal.md`。",
            "Codex 再次加载 `superpowers:brainstorming`，通过真实 brainstorming 流程产出 `design.md` 和 `artifacts/superpowers/brainstorm-design.md`。",
            "Codex 加载 `superpowers:writing-plans`，通过真实 writing-plans 流程产出 `tasks.md` 和 `artifacts/superpowers/write-plan-tasks.md`。",
            "Codex 写入 delta specs 与 `artifacts/workflow-commands.md` 的真实命令 transcript，然后运行 planning gate。",
        ]
        blocked_by = planning.errors
    elif not before.ok:
        stage = "before-apply"
        review_status = parse_frontmatter_status(change_dir / "artifacts" / "design-review.md")
        if ui_level in {"minor", "major", "unknown"} and review_status != "approved":
            human_actions.append("人工评审 `artifacts/design-review.md`；只有真实批准后才能把 frontmatter `status` 改为 `approved`。")
        assistant_actions = [
            "Codex 加载 `references/codegraph-lsp.md`，优先使用 CodeGraph/LSP 收集实施入口和影响面。",
            "Codex 加载 `superpowers:subagent-driven-development` 编排实施 slices，并写入真实 `artifacts/superpowers/subagent-implementation.md`。",
            "Codex 加载 `superpowers:test-driven-development`，为每个行为变更 slice 准备先失败再通过的测试计划。",
            "Codex 写入 `artifacts/retrieval.md` 与更新 `artifacts/workflow-commands.md` 的真实 transcript，然后运行 before-apply gate。",
        ]
        blocked_by = before.errors
    elif not after.ok:
        stage = "implementation"
        assistant_actions = [
            f"Codex 调用 `/opsx:apply {args.change}`；如果当前运行时没有 slash command 能力，必须报告能力缺失，不能手写替代流程。",
            "Codex 按 `superpowers:subagent-driven-development` 分 slice 实施。",
            "Codex 按 `superpowers:test-driven-development` 执行 RED/GREEN/REFACTOR，并写入真实 `artifacts/superpowers/tdd-log.md`。",
            "Codex 运行测试、lint、typecheck、必要的视觉验证，写入 `artifacts/validation.md`。",
            "Codex 加载 `code-review-and-quality` 做阻塞审查，写入 `artifacts/code-review.md`，然后运行 after-apply 与 CI gate。",
        ]
        blocked_by = after.errors
    else:
        stage = "ready"
        assistant_actions = [
            f"Codex 调用 `/opsx:verify {args.change}`、`/opsx:sync`，并在合并或归档前运行 `gate --phase ci`。",
            f"Codex 在完成发布/合并后调用 `/opsx:archive {args.change}`。",
        ]
        blocked_by = []

    return {
        "ok": True,
        "mode": "autopilot",
        "repo_root": str(repo),
        "change": args.change,
        "change_dir": str(change_dir),
        "ready": stage == "ready",
        "stage": stage,
        "ui_level": ui_level,
        "created": {
            "init": init_created,
            "change_scaffold": scaffold_created,
        },
        "skipped_existing": {
            "init": init_skipped,
        },
        "gates": {
            "planning": {"ok": planning.ok, "errors": planning.errors},
            "before_apply": {"ok": before.ok, "errors": before.errors},
            "after_apply": {"ok": after.ok, "errors": after.errors},
        },
        "assistant_actions": assistant_actions,
        "human_actions": human_actions,
        "blocked_by": blocked_by,
        "contract": "Codex must execute assistant_actions itself and rerun autopilot after each stage; ask the user only for human_actions or missing product decisions.",
    }


def cmd_autopilot(args: argparse.Namespace) -> int:
    return emit(autopilot_payload(args), args, "autopilot")


def append_missing_checklist(path: Path, checklist: str) -> bool:
    if not path.exists():
        return False
    text = read_text(path)
    additions = []
    for line in checklist.splitlines():
        if line.strip() and line not in text:
            additions.append(line)
    if additions:
        path.write_text(text.rstrip() + "\n\n" + "\n".join(additions) + "\n", encoding="utf-8")
        return True
    return False


def cmd_review(args: argparse.Namespace) -> int:
    change_dir = find_change_dir(args.change)
    artifacts = change_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    if copy_asset_if_missing("design-review.template.md", artifacts / "design-review.md"):
        created.append("artifacts/design-review.md")
    if copy_asset_if_missing("code-review.template.md", artifacts / "code-review.md"):
        created.append("artifacts/code-review.md")
    missing_audit = [name for name in ("brainstorm-proposal.md", "brainstorm-design.md", "write-plan-tasks.md") if not (artifacts / "superpowers" / name).exists()]
    result = CheckResult(data={"created": created, "missing_superpowers_audit": missing_audit})
    if missing_audit:
        result.warn("Missing Superpowers planning artifacts. Run proposal/design/tasks through required Superpowers skills first.")
    return emit(result, args, "review")


def cmd_status(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    change_dir = find_change_dir(args.change, repo)
    return emit(status_payload(change_dir, repo), args, "status")


def cmd_gate(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    phase = args.phase
    if args.changed:
        result = check_ci_gate(repo, detect_changed_files(repo), None)
    else:
        if not args.change:
            print("error: gate requires <change> unless --changed is used", file=sys.stderr)
            return USAGE
        change_dir = find_change_dir(args.change, repo)
        if phase == "planning":
            result = check_planning_gate(change_dir)
        elif phase == "before-apply":
            result = check_before_apply_gate(change_dir, repo)
        elif phase == "after-apply":
            result = check_after_apply_gate(change_dir)
        elif phase == "ci":
            result = check_ci_gate(repo, detect_changed_files(repo), args.change)
        else:
            print(f"error: unknown phase {phase}", file=sys.stderr)
            return USAGE
    return emit(result, args, "gate")


def selftest_audit(skill: str, target: str, title: str, sections: list[str]) -> str:
    body = [
        "---",
        f"spec_workflow_audit: {AUDIT_VERSION}",
        f"skill: {skill}",
        f"target: {target}",
        "status: completed",
        "transcript_captured: true",
        "created_at: 2026-01-01T00:00:00Z",
        "---",
        "",
        f"# {title}",
        "",
        "## Required skill invocation",
        "",
        f"Required skill: `{skill}`. The skill was loaded before authoring `{target}` and controlled this phase.",
        "",
        "## Raw interaction transcript",
        "",
        "```text",
        "User: Build the OpenSpec artifact through the required Superpowers workflow and keep evidence.",
        f"Assistant: Loaded {skill}, explored alternatives, selected the smallest compliant path, and updated {target}.",
        "User: Do not hand-write marker-only files to satisfy the gate.",
        "Assistant: Recorded this transcript and the resulting decisions before running osdd.py gate.",
        "```",
        "",
    ]
    for section in sections:
        body.extend([
            f"## {section}",
            "",
            f"Evidence for {section}: the workflow considered constraints, rejected shortcut-by-artifact, and recorded the decision that updates `{target}`.",
            "",
        ])
    body.extend([
        "## Resulting updates",
        "",
        f"`{target}` was updated only after the required skill flow produced this audit evidence.",
        "",
    ])
    return "\n".join(body)


def selftest_evidence(kind: str, target: str, title: str, sections: list[str], extra: str = "", skill: str | None = None) -> str:
    body = [
        "---",
        f"spec_workflow_evidence: {AUDIT_VERSION}",
        f"kind: {kind}",
    ]
    if skill:
        body.append(f"skill: {skill}")
    body.extend([
        f"target: {target}",
        "status: completed",
        "transcript_captured: true",
        "created_at: 2026-01-01T00:00:00Z",
        "---",
        "",
        f"# {title}",
        "",
        "## Required command invocation" if kind == "openspec-cli" else "## Required retrieval invocation" if kind == "codegraph-lsp" else "## Required skill invocation",
        "",
        "The required workflow step was executed before this gate. This evidence records the concrete invocation rather than a marker-only artifact.",
        "",
        "## Raw command transcript" if kind == "openspec-cli" else "## Raw interaction transcript",
        "",
        "```text",
        "$ /opsx:propose sample-change",
        "$ python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate sample-change --phase planning",
        "$ python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate sample-change --phase before-apply",
        "$ /opsx:apply sample-change",
        "User: Use the required workflow instead of writing artifacts after the fact.",
        "Assistant: Recorded command, retrieval, and skill evidence before claiming the gate is satisfied.",
        "```",
        "",
    ])
    for section in sections:
        body.extend([
            f"## {section}",
            "",
            f"Evidence for {section}: this step used concrete invocations, captured transcript, and recorded outcomes for `{target}`.",
            "",
        ])
    if extra:
        body.extend([extra, ""])
    return "\n".join(body)


def cmd_selftest(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="spec-workflow-selftest-") as tmp:
        root = Path(tmp)
        run(["git", "init"], root) if check_command_exists("git") else None
        os.chdir(root)
        auto_args = argparse.Namespace(change="auto-change", ui=True, ui_level="none", fullstack=True, no_init=False, json=True)
        auto_payload = autopilot_payload(auto_args)
        auto_change_dir = find_change_dir("auto-change", root)
        autopilot_created_scaffold = (
            (root / ".github" / "workflows" / "spec-workflow-gate.yml").exists()
            and (auto_change_dir / "artifacts" / "workflow-commands.md").exists()
            and (auto_change_dir / "artifacts" / "design-review.md").exists()
        )
        autopilot_routes_to_assistant = bool(auto_payload.get("assistant_actions")) and auto_payload.get("human_actions") == []
        autopilot_keeps_evidence_pending = "status: pending" in read_text(auto_change_dir / "artifacts" / "workflow-commands.md")
        change_dir = find_change_dir("sample-change", root)
        (change_dir / "artifacts" / "superpowers").mkdir(parents=True, exist_ok=True)
        for asset, rel in (
            ("prototype.template.html", "artifacts/prototype.html"),
            ("penpot.template.md", "artifacts/penpot.md"),
            ("design-review.template.md", "artifacts/design-review.md"),
        ):
            copy_asset_if_missing(asset, change_dir / rel)
        fail_gate = check_planning_gate(change_dir)
        if fail_gate.ok:
            return emit(CheckResult(ok=False, errors=["planning gate unexpectedly passed without artifacts"]), args, "selftest")
        (change_dir / "specs" / "sample").mkdir(parents=True, exist_ok=True)
        write_file_if_missing(change_dir / "specs" / "sample" / "spec.md", "# Sample Spec\n\n## ADDED Requirements\n\n### Requirement: Sample\n\n#### Scenario: Works\n- Given a user\n- When action runs\n- Then result appears\n")
        write_file_if_missing(change_dir / "proposal.md", f"# Proposal\n\n{PROPOSAL_MARKER}\n\n## Goals\n\n- Do it.\n\n## Non-goals\n\n- Skip unrelated work.\n\n## Impact\n\n- Full stack impact.\n\n## Open Questions\n\n- None.\n")
        write_file_if_missing(change_dir / "design.md", f"# Design\n\n{DESIGN_MARKER}\n\n## Technical Design\n\nUse minimal components.\n\n## UI / UX Design\n\nCover states.\n")
        write_file_if_missing(change_dir / "tasks.md", f"# Tasks\n\n{TASKS_MARKER}\n\n- [ ] Design review before implementation\n- [ ] Implementation\n")
        sp = change_dir / "artifacts" / "superpowers"
        sp.mkdir(parents=True, exist_ok=True)
        for name in ("brainstorm-proposal.md", "brainstorm-design.md", "write-plan-tasks.md", "subagent-implementation.md"):
            write_file_if_missing(sp / name, "# Audit\n")
        marker_only_audit = check_planning_gate(change_dir)
        for name, content in {
            "brainstorm-proposal.md": selftest_audit("superpowers:brainstorming", "proposal.md", "Superpowers Brainstorm Audit", ["Explored options", "Decisions"]),
            "brainstorm-design.md": selftest_audit("superpowers:brainstorming", "design.md", "Superpowers Brainstorm Audit", ["Explored options", "Trade-offs", "Decisions"]),
            "write-plan-tasks.md": selftest_audit("superpowers:writing-plans", "tasks.md", "Superpowers Writing Plans Audit", ["Plan structure", "Task ordering rationale", "Validation steps"]),
            "subagent-implementation.md": selftest_audit("superpowers:subagent-driven-development", "implementation", "Subagent Implementation Audit", ["Implementation slices", "Retrieval entrypoints", "Completion evidence"]),
        }.items():
            (sp / name).write_text(content, encoding="utf-8")
        missing_command_evidence = check_planning_gate(change_dir)
        (change_dir / "artifacts" / "workflow-commands.md").write_text(
            selftest_evidence("openspec-cli", "workflow-commands", "Workflow Commands Evidence", ["Commands run", "Results"]),
            encoding="utf-8",
        )
        (change_dir / "artifacts" / "retrieval.md").write_text(
            selftest_evidence("codegraph-lsp", "implementation-retrieval", "Retrieval Evidence", ["CodeGraph or LSP entrypoints", "Symbols references or tests found", "Scope decisions"]),
            encoding="utf-8",
        )
        pass_planning = check_planning_gate(change_dir)
        auto_before_payload = autopilot_payload(argparse.Namespace(change="sample-change", ui=True, ui_level="none", fullstack=True, no_init=True, json=True))
        autopilot_requests_human_design_review = auto_before_payload.get("stage") == "before-apply" and bool(auto_before_payload.get("human_actions"))
        before = check_before_apply_gate(change_dir, root)
        after = check_after_apply_gate(change_dir)
        (change_dir / "src").mkdir(parents=True, exist_ok=True)
        write_file_if_missing(change_dir / "src" / "feature.ts", "export const x = 1;\n")
        production_without_change = check_ci_gate(root, ["src/feature.ts"], None)
        archive_paths = [
            "openspec/changes/archive/2026-07-11-example/proposal.md",
            "openspec/changes/archive/2026-07-11-example/artifacts/validation.md",
        ]
        archive_paths_ignored = changed_open_spec_changes(archive_paths) == []
        governance_tests_not_production = production_changed_files(["tests/test_spec_workflow_gate.py"]) == []
        penpot_text = read_text(change_dir / "artifacts" / "penpot.md")
        (change_dir / "artifacts" / "penpot.md").write_text(penpot_text.replace("status: import-ready", "status: not-applicable"), encoding="utf-8")
        penpot_major = check_before_apply_gate(change_dir, root)
        (change_dir / "artifacts" / "penpot.md").write_text(penpot_text, encoding="utf-8")
        (change_dir / "tasks.md").write_text(f"# Tasks\n\n{TASKS_MARKER}\n\n- [x] Design review before implementation\n- [x] Implementation\n", encoding="utf-8")
        write_file_if_missing(change_dir / "artifacts" / "validation.md", "test: passed\nlint: passed\ntypecheck: passed\nvisual validation: passed\n")
        write_file_if_missing(sp / "tdd-log.md", selftest_audit("superpowers:test-driven-development", "behavior-changing code", "TDD Log", ["Failing test", "Implementation", "Passing test", "Validation commands", "Screenshot or visual validation"]))
        write_file_if_missing(
            change_dir / "artifacts" / "code-review.md",
            selftest_evidence(
                "skill-invocation",
                "code-review",
                "Code Review",
                ["Scope reviewed", "Findings", "Blocking findings", "Tests and validation reviewed"],
                extra="blocking_findings: 1\n",
                skill="code-review-and-quality",
            ).replace("status: completed", "status: completed\nblocking_findings: 1"),
        )
        blocking_review = check_after_apply_gate(change_dir)
        ok = (
            (not fail_gate.ok)
            and (not marker_only_audit.ok)
            and (not missing_command_evidence.ok)
            and pass_planning.ok
            and (not before.ok)
            and (not after.ok)
            and (not production_without_change.ok)
            and archive_paths_ignored
            and governance_tests_not_production
            and (not penpot_major.ok)
            and (not blocking_review.ok)
            and autopilot_created_scaffold
            and autopilot_routes_to_assistant
            and autopilot_keeps_evidence_pending
            and autopilot_requests_human_design_review
        )
        result = CheckResult(ok=ok, data={
            "planning_missing_artifacts_failed": not fail_gate.ok,
            "marker_only_audit_failed": not marker_only_audit.ok,
            "missing_command_evidence_failed": not missing_command_evidence.ok,
            "planning_after_artifacts_passed": pass_planning.ok,
            "before_apply_unapproved_design_failed": not before.ok,
            "after_apply_missing_tdd_or_review_failed": not after.ok,
            "ci_production_without_change_failed": not production_without_change.ok,
            "ci_archive_paths_ignored": archive_paths_ignored,
            "gate_governance_tests_not_production": governance_tests_not_production,
            "major_ui_penpot_not_applicable_failed": not penpot_major.ok,
            "blocking_code_review_failed": not blocking_review.ok,
            "autopilot_created_scaffold": autopilot_created_scaffold,
            "autopilot_routes_to_assistant": autopilot_routes_to_assistant,
            "autopilot_keeps_evidence_pending": autopilot_keeps_evidence_pending,
            "autopilot_requests_human_design_review": autopilot_requests_human_design_review,
            "tmp": tmp,
        })
        if not archive_paths_ignored:
            result.fail("CI change detection treated archive paths as an active change")
        if not governance_tests_not_production:
            result.fail("CI gate treated spec-workflow governance tests as production files")
        if not ok:
            result.errors.extend(marker_only_audit.errors + pass_planning.errors + before.errors + after.errors + production_without_change.errors + penpot_major.errors + blocking_review.errors)
        return emit(result, args, "selftest")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenSpec/Superpowers 确定性 workflow gate")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--install", action="store_true")
    doctor.add_argument("--json", action="store_true")
    init = sub.add_parser("init")
    init.add_argument("--install", action="store_true")
    init.add_argument("--json", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("change")
    status.add_argument("--json", action="store_true")
    new = sub.add_parser("new")
    new.add_argument("change")
    new.add_argument("--ui", action="store_true")
    new.add_argument("--ui-level", choices=["none", "minor", "major"], default="none")
    new.add_argument("--fullstack", action="store_true")
    new.add_argument("--json", action="store_true")
    autopilot = sub.add_parser("autopilot")
    autopilot.add_argument("change")
    autopilot.add_argument("--ui", action="store_true")
    autopilot.add_argument("--ui-level", choices=["none", "minor", "major"], default="none")
    autopilot.add_argument("--fullstack", action="store_true")
    autopilot.add_argument("--no-init", action="store_true")
    autopilot.add_argument("--json", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("change")
    review.add_argument("--json", action="store_true")
    gate = sub.add_parser("gate")
    gate.add_argument("change", nargs="?")
    gate.add_argument("--changed", action="store_true")
    gate.add_argument("--phase", choices=["planning", "before-apply", "after-apply", "ci"], default="planning")
    gate.add_argument("--json", action="store_true")
    selftest = sub.add_parser("selftest")
    selftest.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    try:
        parser = build_parser()
        args = parser.parse_args()
        return {
            "doctor": cmd_doctor,
            "init": cmd_init,
            "status": cmd_status,
            "new": cmd_new,
            "autopilot": cmd_autopilot,
            "review": cmd_review,
            "gate": cmd_gate,
            "selftest": cmd_selftest,
        }[args.command](args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return USAGE
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return FAIL


if __name__ == "__main__":
    sys.exit(main())
