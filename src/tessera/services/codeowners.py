"""CODEOWNERS file parser with team ownership suggestion.

Parses GitHub and GitLab CODEOWNERS formats and resolves owners
against existing Tessera teams using fuzzy name matching.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class CodeownersRule:
    """A single ownership rule parsed from a CODEOWNERS file.

    Attributes:
        pattern: The glob pattern from the CODEOWNERS file.
        owners: Raw owner strings (e.g. ``@acme/backend-team``, ``user@example.com``).
        section: GitLab section name if the rule appeared under a ``[Section]`` header,
            otherwise ``None``.
        negation: ``True`` when the pattern starts with ``!`` (excludes matching paths).
        line_number: 1-based line number in the source file.
    """

    pattern: str
    owners: list[str]
    section: str | None = None
    negation: bool = False
    line_number: int = 0


@dataclass
class TeamSuggestion:
    """A suggested Tessera team mapping for a file path.

    Attributes:
        path_pattern: The CODEOWNERS glob pattern that matched.
        raw_owner: The original owner string from the CODEOWNERS file.
        suggested_team_id: The resolved Tessera team UUID, or ``None`` if no match.
        suggested_team_name: The resolved Tessera team name, or ``None``.
        confidence: Match confidence — ``"exact"`` for normalized-equal names,
            ``"fuzzy"`` for substring/partial matches.
        section: GitLab section the rule belongs to, if any.
    """

    path_pattern: str
    raw_owner: str
    suggested_team_id: UUID | None = None
    suggested_team_name: str | None = None
    confidence: str | None = None
    section: str | None = None


@dataclass
class CodeownersParseResult:
    """Full result of parsing a CODEOWNERS file and resolving teams.

    Attributes:
        rules: All parsed ownership rules.
        suggestions: Per-owner team suggestions for a specific file (populated
            by :func:`suggest_owners`).
        unresolved_owners: Owner strings that could not be matched to any
            Tessera team.
    """

    rules: list[CodeownersRule] = field(default_factory=list)
    suggestions: list[TeamSuggestion] = field(default_factory=list)
    unresolved_owners: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GitLab section header pattern: [SectionName] or [SectionName][number]
# Optional leading ^ for optional approval sections.
# ---------------------------------------------------------------------------
_GITLAB_SECTION_RE = re.compile(r"^\^?\[(?P<name>[^\]]+)\](?:\[\d+\])?\s*$")


def parse_codeowners(content: str) -> list[CodeownersRule]:
    """Parse a CODEOWNERS file into a list of ownership rules.

    Supports both GitHub and GitLab formats:

    * **GitHub**: ``<pattern> <owner1> <owner2> ...``
    * **GitLab**: Same line format, but rules may appear under section headers
      (``[SectionName]``).

    Lines starting with ``#`` are comments. Blank lines are skipped.
    Negation patterns (``!pattern``) are preserved with ``negation=True``.

    Args:
        content: The raw text content of a CODEOWNERS file.

    Returns:
        A list of :class:`CodeownersRule` in file order.
    """
    rules: list[CodeownersRule] = []
    current_section: str | None = None

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()

        # Skip blanks and comments.
        if not line or line.startswith("#"):
            continue

        # Check for a GitLab section header.
        section_match = _GITLAB_SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("name")
            continue

        # Split into tokens — pattern is always the first token, rest are owners.
        tokens = line.split()
        if len(tokens) < 2:
            # A line with only a pattern and no owners clears ownership in GitHub
            # format. We still record it so downstream consumers can see the
            # explicit "no owner" declaration.
            pattern = tokens[0]
            owners: list[str] = []
        else:
            pattern = tokens[0]
            owners = tokens[1:]

        negation = pattern.startswith("!")
        if negation:
            pattern = pattern[1:]

        rules.append(
            CodeownersRule(
                pattern=pattern,
                owners=owners,
                section=current_section,
                negation=negation,
                line_number=line_number,
            )
        )

    return rules


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


def _pattern_matches(pattern: str, file_path: str) -> bool:
    """Test whether a CODEOWNERS glob *pattern* matches *file_path*.

    CODEOWNERS globs follow these conventions:

    * A pattern without a ``/`` matches any file whose **basename** matches
      (GitHub behaviour: ``*.js`` matches ``src/app.js``).
    * A pattern starting with ``/`` is anchored to the repo root
      (``/docs/`` matches ``docs/readme.md``).
    * A pattern containing ``/`` (other than a leading one) matches relative to
      the repo root.
    * A trailing ``/`` means "everything under this directory".
    * ``**`` matches across directory boundaries.
    """
    anchored = pattern.startswith("/")
    normalized_pattern = pattern.lstrip("/")

    # Trailing slash → match everything under that directory.
    if normalized_pattern.endswith("/"):
        normalized_pattern += "**"

    # A pattern with no directory separator AND not anchored matches any path
    # whose basename matches (like .gitignore's basename-only rule).
    if "/" not in normalized_pattern and not anchored:
        basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        return fnmatch.fnmatch(basename, normalized_pattern)

    # fnmatch doesn't natively support `**` across directories, so we convert
    # to a regex when the pattern contains `**`.
    if "**" in normalized_pattern:
        regex = _glob_to_regex(normalized_pattern)
        return bool(re.match(regex, file_path))

    return fnmatch.fnmatch(file_path, normalized_pattern)


def _glob_to_regex(pattern: str) -> str:
    """Convert a CODEOWNERS glob pattern to a regex string.

    Handles ``*``, ``**``, ``?``, and character classes ``[…]``.
    """
    i = 0
    n = len(pattern)
    result: list[str] = []

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # `**` — match everything including `/`.
                i += 2
                if i < n and pattern[i] == "/":
                    # `**/` — match zero or more directory levels.
                    i += 1
                    result.append("(?:.*/)?")
                else:
                    # `**` at end of pattern — match anything remaining.
                    result.append(".*")
                continue
            else:
                # Single `*` — match anything except `/`.
                result.append("[^/]*")
        elif c == "?":
            result.append("[^/]")
        elif c == "[":
            # Pass character classes through — find the closing `]`.
            j = i + 1
            negate = False
            if j < n and pattern[j] == "!":
                negate = True
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            # Glob uses [!...] for negation; regex uses [^...].
            class_body = pattern[i + 1 : j + 1]
            if negate:
                class_body = "^" + class_body[1:]
            result.append("[" + class_body)
            i = j
        else:
            result.append(re.escape(c))
        i += 1

    return "^" + "".join(result) + "$"


# ---------------------------------------------------------------------------
# Team resolution
# ---------------------------------------------------------------------------


def _normalize_team_name(name: str) -> str:
    """Normalize a team name for fuzzy comparison.

    Strips org prefixes (``@org/``), converts to lowercase, and replaces
    hyphens, underscores, and spaces with a single canonical separator.
    """
    # Strip leading '@'.
    if name.startswith("@"):
        name = name[1:]

    # Strip org prefix (everything before the first `/`).
    if "/" in name:
        name = name.rsplit("/", 1)[-1]

    return re.sub(r"[-_\s]+", "-", name.strip().lower())


@dataclass(frozen=True)
class _TeamEntry:
    """Internal representation of a Tessera team for matching."""

    team_id: UUID
    raw_name: str
    normalized: str


def resolve_owner(
    raw_owner: str,
    teams: list[_TeamEntry],
) -> tuple[UUID | None, str | None, str | None]:
    """Resolve a CODEOWNERS owner string to a Tessera team.

    Returns ``(team_id, team_name, confidence)`` or ``(None, None, None)``.
    """
    # Email addresses are user references, not team references — skip.
    if "@" in raw_owner and "/" not in raw_owner and not raw_owner.startswith("@"):
        return None, None, None

    normalized_owner = _normalize_team_name(raw_owner)

    # Pass 1: exact normalized match.
    for team in teams:
        if team.normalized == normalized_owner:
            return team.team_id, team.raw_name, "exact"

    # Pass 2: substring / containment match (either direction).
    candidates: list[_TeamEntry] = []
    for team in teams:
        if normalized_owner in team.normalized or team.normalized in normalized_owner:
            candidates.append(team)

    if len(candidates) == 1:
        t = candidates[0]
        return t.team_id, t.raw_name, "fuzzy"

    return None, None, None


def _build_team_entries(
    teams: list[tuple[UUID, str]],
) -> list[_TeamEntry]:
    """Build normalised team entries from ``(id, name)`` pairs."""
    return [
        _TeamEntry(team_id=tid, raw_name=name, normalized=_normalize_team_name(name))
        for tid, name in teams
    ]


# ---------------------------------------------------------------------------
# Public API: suggest_owners
# ---------------------------------------------------------------------------


def suggest_owners(
    rules: list[CodeownersRule],
    file_path: str,
    teams: list[tuple[UUID, str]] | None = None,
) -> list[TeamSuggestion]:
    """Given parsed CODEOWNERS rules and a file path, return ranked team suggestions.

    CODEOWNERS semantics: the **last** matching rule wins.  Negation rules
    remove a prior match.  This function evaluates all rules in order and
    returns suggestions for the final effective match.

    Args:
        rules: Parsed rules from :func:`parse_codeowners`.
        file_path: Repository-root-relative path to evaluate
            (e.g. ``"services/orders/api.yaml"``).
        teams: Optional list of ``(team_id, team_name)`` tuples representing
            existing Tessera teams.  Used to resolve owner strings to team IDs.

    Returns:
        A list of :class:`TeamSuggestion`, one per owner in the winning rule.
        Empty if no rule matches.
    """
    team_entries = _build_team_entries(teams or [])

    # CODEOWNERS: last matching non-negated rule wins.
    # A negation rule cancels a prior match.
    effective_rule: CodeownersRule | None = None

    for rule in rules:
        if _pattern_matches(rule.pattern, file_path):
            if rule.negation:
                effective_rule = None
            else:
                effective_rule = rule

    if effective_rule is None:
        return []

    suggestions: list[TeamSuggestion] = []
    for owner in effective_rule.owners:
        team_id, team_name, confidence = resolve_owner(owner, team_entries)
        suggestions.append(
            TeamSuggestion(
                path_pattern=effective_rule.pattern,
                raw_owner=owner,
                suggested_team_id=team_id,
                suggested_team_name=team_name,
                confidence=confidence,
                section=effective_rule.section,
            )
        )

    return suggestions


def suggest_owners_bulk(
    rules: list[CodeownersRule],
    file_paths: list[str],
    teams: list[tuple[UUID, str]] | None = None,
) -> CodeownersParseResult:
    """Evaluate multiple file paths and aggregate team suggestions.

    Convenience wrapper that calls :func:`suggest_owners` for each path and
    collects unique suggestions and unresolved owners.

    Args:
        rules: Parsed CODEOWNERS rules.
        file_paths: Repository-root-relative file paths to evaluate.
        teams: Tessera teams for resolution.

    Returns:
        A :class:`CodeownersParseResult` with deduplicated suggestions and
        unresolved owners.
    """
    all_suggestions: list[TeamSuggestion] = []
    seen_keys: set[tuple[str, str]] = set()
    unresolved: set[str] = set()

    for path in file_paths:
        for suggestion in suggest_owners(rules, path, teams):
            key = (suggestion.path_pattern, suggestion.raw_owner)
            if key not in seen_keys:
                seen_keys.add(key)
                all_suggestions.append(suggestion)
                if suggestion.suggested_team_id is None:
                    unresolved.add(suggestion.raw_owner)

    return CodeownersParseResult(
        rules=rules,
        suggestions=all_suggestions,
        unresolved_owners=sorted(unresolved),
    )
