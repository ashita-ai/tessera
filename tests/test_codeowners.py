"""Tests for the CODEOWNERS parser service."""

from uuid import UUID, uuid4

from tessera.services.codeowners import (
    _build_team_entries,
    _normalize_team_name,
    _pattern_matches,
    parse_codeowners,
    resolve_owner,
    suggest_owners,
    suggest_owners_bulk,
)

# ---------------------------------------------------------------------------
# parse_codeowners — GitHub format
# ---------------------------------------------------------------------------


class TestParseGitHubFormat:
    """Parsing standard GitHub CODEOWNERS files."""

    def test_basic_rules(self) -> None:
        content = """\
# Global owners
* @acme/platform-team

# Per-directory
/services/orders/    @acme/commerce-team
/services/payments/  @acme/commerce-team @acme/fintech-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 3

        assert rules[0].pattern == "*"
        assert rules[0].owners == ["@acme/platform-team"]
        assert rules[0].section is None
        assert rules[0].negation is False
        assert rules[0].line_number == 2

        assert rules[1].pattern == "/services/orders/"
        assert rules[1].owners == ["@acme/commerce-team"]

        assert rules[2].pattern == "/services/payments/"
        assert rules[2].owners == ["@acme/commerce-team", "@acme/fintech-team"]

    def test_comments_and_blank_lines_skipped(self) -> None:
        content = """\
# This is a comment

# Another comment

*.go @go-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 1
        assert rules[0].pattern == "*.go"

    def test_negation_pattern(self) -> None:
        content = """\
/docs/ @docs-team
!/docs/internal/ @docs-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 2
        assert rules[0].negation is False
        assert rules[0].pattern == "/docs/"
        assert rules[1].negation is True
        assert rules[1].pattern == "/docs/internal/"

    def test_no_owner_line(self) -> None:
        """A pattern with no owners explicitly unsets ownership."""
        content = """\
* @fallback-team
/vendor/
"""
        rules = parse_codeowners(content)
        assert len(rules) == 2
        assert rules[1].pattern == "/vendor/"
        assert rules[1].owners == []

    def test_email_owners(self) -> None:
        content = "*.js dev@example.com @frontend-team\n"
        rules = parse_codeowners(content)
        assert rules[0].owners == ["dev@example.com", "@frontend-team"]

    def test_empty_content(self) -> None:
        assert parse_codeowners("") == []

    def test_only_comments(self) -> None:
        assert parse_codeowners("# just a comment\n# another") == []

    def test_line_numbers_are_correct(self) -> None:
        content = "# comment\n\n*.py @py-team\n*.js @js-team\n"
        rules = parse_codeowners(content)
        assert rules[0].line_number == 3
        assert rules[1].line_number == 4


# ---------------------------------------------------------------------------
# parse_codeowners — GitLab sections
# ---------------------------------------------------------------------------


class TestParseGitLabSections:
    """Parsing GitLab CODEOWNERS with [Section] headers."""

    def test_basic_sections(self) -> None:
        content = """\
[Backend]
/services/ @backend-team

[Frontend]
/web/ @frontend-team
*.tsx @frontend-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 3

        assert rules[0].section == "Backend"
        assert rules[0].pattern == "/services/"
        assert rules[0].owners == ["@backend-team"]

        assert rules[1].section == "Frontend"
        assert rules[1].pattern == "/web/"
        assert rules[2].section == "Frontend"
        assert rules[2].pattern == "*.tsx"

    def test_optional_approval_section(self) -> None:
        """GitLab ``^[Section]`` marks optional approval."""
        content = """\
^[Docs]
/docs/ @docs-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 1
        assert rules[0].section == "Docs"

    def test_section_with_approval_count(self) -> None:
        """GitLab ``[Section][2]`` requires N approvals."""
        content = """\
[Security][2]
/auth/ @security-team
"""
        rules = parse_codeowners(content)
        assert len(rules) == 1
        assert rules[0].section == "Security"

    def test_rules_before_any_section(self) -> None:
        """Rules before the first section have section=None."""
        content = """\
* @fallback
[Backend]
/api/ @backend
"""
        rules = parse_codeowners(content)
        assert rules[0].section is None
        assert rules[1].section == "Backend"

    def test_mixed_github_and_gitlab(self) -> None:
        """A file can mix global rules with GitLab sections."""
        content = """\
# Global fallback
* @platform

[API]
/api/ @api-team

# This comment is inside the API section
/api/v2/ @api-team @v2-lead
"""
        rules = parse_codeowners(content)
        assert len(rules) == 3
        assert rules[0].section is None
        assert rules[1].section == "API"
        assert rules[2].section == "API"


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


class TestPatternMatching:
    """CODEOWNERS glob pattern matching."""

    def test_wildcard_matches_all(self) -> None:
        assert _pattern_matches("*", "anything.py") is True
        assert _pattern_matches("*", "src/deep/file.py") is True

    def test_extension_glob_basename(self) -> None:
        """``*.js`` matches any ``.js`` file regardless of directory."""
        assert _pattern_matches("*.js", "app.js") is True
        assert _pattern_matches("*.js", "src/components/App.js") is True
        assert _pattern_matches("*.js", "app.ts") is False

    def test_directory_pattern_trailing_slash(self) -> None:
        """Trailing slash matches everything under that directory."""
        assert _pattern_matches("docs/", "docs/readme.md") is True
        assert _pattern_matches("docs/", "docs/api/endpoints.md") is True
        assert _pattern_matches("docs/", "src/docs/file.md") is False

    def test_leading_slash_anchored(self) -> None:
        """/src/ is anchored to repo root."""
        assert _pattern_matches("/src/", "src/main.py") is True
        assert _pattern_matches("/src/", "lib/src/main.py") is False

    def test_nested_directory_pattern(self) -> None:
        assert _pattern_matches("services/orders/", "services/orders/api.yaml") is True
        assert _pattern_matches("services/orders/", "services/orders/v2/api.yaml") is True
        assert _pattern_matches("services/orders/", "services/payments/api.yaml") is False

    def test_double_star_any_depth(self) -> None:
        assert _pattern_matches("docs/**/*.md", "docs/readme.md") is True
        assert _pattern_matches("docs/**/*.md", "docs/api/endpoints.md") is True
        assert _pattern_matches("docs/**/*.md", "docs/api/v2/guide.md") is True
        assert _pattern_matches("docs/**/*.md", "src/readme.md") is False

    def test_question_mark_single_char(self) -> None:
        assert _pattern_matches("file?.txt", "file1.txt") is True
        assert _pattern_matches("file?.txt", "fileAB.txt") is False

    def test_character_class(self) -> None:
        assert _pattern_matches("*.[ch]", "main.c") is True
        assert _pattern_matches("*.[ch]", "main.h") is True
        assert _pattern_matches("*.[ch]", "main.o") is False

    def test_specific_file(self) -> None:
        assert _pattern_matches("Makefile", "Makefile") is True
        assert _pattern_matches("Makefile", "src/Makefile") is True
        assert _pattern_matches("/Makefile", "src/Makefile") is False


# ---------------------------------------------------------------------------
# Team name normalization
# ---------------------------------------------------------------------------


class TestNormalizeTeamName:
    """Normalizing CODEOWNERS owner strings for fuzzy matching."""

    def test_strip_org_prefix(self) -> None:
        assert _normalize_team_name("@acme/backend-team") == "backend-team"

    def test_strip_at_sign(self) -> None:
        assert _normalize_team_name("@backend-team") == "backend-team"

    def test_normalize_underscores(self) -> None:
        assert _normalize_team_name("backend_team") == "backend-team"

    def test_normalize_spaces(self) -> None:
        assert _normalize_team_name("Backend Team") == "backend-team"

    def test_mixed_separators(self) -> None:
        assert _normalize_team_name("@org/My_Cool--Team") == "my-cool-team"

    def test_plain_name(self) -> None:
        assert _normalize_team_name("platform") == "platform"


# ---------------------------------------------------------------------------
# Owner resolution
# ---------------------------------------------------------------------------


class TestResolveOwner:
    """Resolving CODEOWNERS owner strings to Tessera teams."""

    def setup_method(self) -> None:
        self.team_a_id = uuid4()
        self.team_b_id = uuid4()
        self.teams = _build_team_entries(
            [
                (self.team_a_id, "backend-team"),
                (self.team_b_id, "Frontend Team"),
            ]
        )

    def test_exact_match_with_org_prefix(self) -> None:
        tid, name, confidence = resolve_owner("@acme/backend-team", self.teams)
        assert tid == self.team_a_id
        assert name == "backend-team"
        assert confidence == "exact"

    def test_exact_match_normalized_spaces(self) -> None:
        tid, name, confidence = resolve_owner("@org/frontend-team", self.teams)
        assert tid == self.team_b_id
        assert name == "Frontend Team"
        assert confidence == "exact"

    def test_fuzzy_substring_match(self) -> None:
        """'backend' is a substring of 'backend-team'."""
        teams = _build_team_entries([(self.team_a_id, "backend-team")])
        tid, _, confidence = resolve_owner("@org/backend", teams)
        assert tid == self.team_a_id
        assert confidence == "fuzzy"

    def test_no_match(self) -> None:
        tid, name, confidence = resolve_owner("@acme/unknown-team", self.teams)
        assert tid is None
        assert name is None
        assert confidence is None

    def test_email_owner_skipped(self) -> None:
        """Email addresses are user references, not team references."""
        tid, name, confidence = resolve_owner("dev@example.com", self.teams)
        assert tid is None

    def test_ambiguous_substring_returns_none(self) -> None:
        """Multiple substring matches → no confident resolution."""
        teams = _build_team_entries(
            [
                (uuid4(), "backend-team-a"),
                (uuid4(), "backend-team-b"),
            ]
        )
        tid, _, _ = resolve_owner("@org/backend-team", teams)
        assert tid is None


# ---------------------------------------------------------------------------
# suggest_owners
# ---------------------------------------------------------------------------


class TestSuggestOwners:
    """End-to-end: parse → match → suggest."""

    def setup_method(self) -> None:
        self.commerce_id = uuid4()
        self.platform_id = uuid4()
        self.teams: list[tuple[UUID, str]] = [
            (self.commerce_id, "commerce-team"),
            (self.platform_id, "platform-team"),
        ]

    def test_last_matching_rule_wins(self) -> None:
        rules = parse_codeowners("""\
* @acme/platform-team
/services/orders/ @acme/commerce-team
""")
        suggestions = suggest_owners(rules, "services/orders/api.yaml", self.teams)
        assert len(suggestions) == 1
        assert suggestions[0].raw_owner == "@acme/commerce-team"
        assert suggestions[0].suggested_team_id == self.commerce_id
        assert suggestions[0].confidence == "exact"

    def test_fallback_to_global_rule(self) -> None:
        rules = parse_codeowners("* @acme/platform-team\n")
        suggestions = suggest_owners(rules, "random/file.py", self.teams)
        assert len(suggestions) == 1
        assert suggestions[0].suggested_team_id == self.platform_id

    def test_negation_cancels_match(self) -> None:
        rules = parse_codeowners("""\
/docs/ @acme/platform-team
!/docs/internal/ @acme/platform-team
""")
        suggestions = suggest_owners(rules, "docs/internal/secret.md", self.teams)
        assert suggestions == []

    def test_no_matching_rule(self) -> None:
        rules = parse_codeowners("/services/ @acme/commerce-team\n")
        suggestions = suggest_owners(rules, "unrelated/file.txt", self.teams)
        assert suggestions == []

    def test_multiple_owners_per_rule(self) -> None:
        rules = parse_codeowners("/services/ @acme/commerce-team @acme/platform-team\n")
        suggestions = suggest_owners(rules, "services/orders/api.yaml", self.teams)
        assert len(suggestions) == 2
        assert suggestions[0].suggested_team_id == self.commerce_id
        assert suggestions[1].suggested_team_id == self.platform_id

    def test_unresolved_owner(self) -> None:
        rules = parse_codeowners("/services/ @acme/mystery-team\n")
        suggestions = suggest_owners(rules, "services/file.py", self.teams)
        assert len(suggestions) == 1
        assert suggestions[0].suggested_team_id is None
        assert suggestions[0].raw_owner == "@acme/mystery-team"

    def test_no_teams_provided(self) -> None:
        rules = parse_codeowners("* @acme/any-team\n")
        suggestions = suggest_owners(rules, "file.py")
        assert len(suggestions) == 1
        assert suggestions[0].suggested_team_id is None

    def test_section_propagated(self) -> None:
        rules = parse_codeowners("""\
[Backend]
/api/ @acme/platform-team
""")
        suggestions = suggest_owners(rules, "api/routes.py", self.teams)
        assert len(suggestions) == 1
        assert suggestions[0].section == "Backend"

    def test_empty_owner_line_clears_ownership(self) -> None:
        """A pattern-only line (no owners) clears prior ownership."""
        rules = parse_codeowners("""\
* @acme/platform-team
/vendor/
""")
        suggestions = suggest_owners(rules, "vendor/lib.py", self.teams)
        # The /vendor/ rule has no owners, so no suggestions.
        assert suggestions == []


# ---------------------------------------------------------------------------
# suggest_owners_bulk
# ---------------------------------------------------------------------------


class TestSuggestOwnersBulk:
    """Bulk evaluation across multiple file paths."""

    def test_deduplicates_suggestions(self) -> None:
        team_id = uuid4()
        teams: list[tuple[UUID, str]] = [(team_id, "backend-team")]
        rules = parse_codeowners("/services/ @acme/backend-team\n")
        result = suggest_owners_bulk(
            rules,
            ["services/a.py", "services/b.py"],
            teams,
        )
        # Same pattern+owner → deduplicated to one suggestion.
        assert len(result.suggestions) == 1
        assert result.suggestions[0].suggested_team_id == team_id

    def test_unresolved_owners_collected(self) -> None:
        rules = parse_codeowners("/api/ @acme/unknown-team\n")
        result = suggest_owners_bulk(rules, ["api/routes.py"])
        assert "@acme/unknown-team" in result.unresolved_owners

    def test_empty_paths(self) -> None:
        rules = parse_codeowners("* @fallback\n")
        result = suggest_owners_bulk(rules, [])
        assert result.suggestions == []
        assert result.unresolved_owners == []

    def test_rules_preserved_in_result(self) -> None:
        rules = parse_codeowners("* @team\n")
        result = suggest_owners_bulk(rules, ["f.py"])
        assert result.rules is rules


# ---------------------------------------------------------------------------
# Malformed / edge-case files
# ---------------------------------------------------------------------------


class TestMalformedFiles:
    """Graceful handling of unusual CODEOWNERS content."""

    def test_windows_line_endings(self) -> None:
        content = "*.py @py-team\r\n*.js @js-team\r\n"
        rules = parse_codeowners(content)
        assert len(rules) == 2
        assert rules[0].owners == ["@py-team"]

    def test_tabs_as_separators(self) -> None:
        content = "*.go\t@go-team\n"
        rules = parse_codeowners(content)
        assert rules[0].pattern == "*.go"
        assert rules[0].owners == ["@go-team"]

    def test_multiple_spaces_between_tokens(self) -> None:
        content = "*.rs    @rust-team    @systems-team\n"
        rules = parse_codeowners(content)
        assert rules[0].owners == ["@rust-team", "@systems-team"]

    def test_inline_comment_not_stripped(self) -> None:
        """CODEOWNERS does not support inline comments — '#' after tokens is
        treated as an owner (matches real GitHub behavior)."""
        content = "*.py @py-team # this is not a comment\n"
        rules = parse_codeowners(content)
        # '@py-team', '#', 'this', 'is', 'not', 'a', 'comment' are all owners.
        assert len(rules[0].owners) == 7

    def test_unicode_section_name(self) -> None:
        content = "[Équipe Backend]\n/api/ @backend\n"
        rules = parse_codeowners(content)
        assert rules[0].section == "Équipe Backend"

    def test_deeply_nested_pattern(self) -> None:
        content = "/a/b/c/d/e/ @deep-team\n"
        rules = parse_codeowners(content)
        suggestions = suggest_owners(rules, "a/b/c/d/e/file.py")
        assert len(suggestions) == 1


# ---------------------------------------------------------------------------
# _glob_to_regex — character class and mixed-operator coverage
# ---------------------------------------------------------------------------


class TestGlobToRegexBranches:
    """Tests that exercise _glob_to_regex branches unreachable through fnmatch.

    _pattern_matches only routes through _glob_to_regex when the pattern
    contains ``**``, so we combine ``**`` with each operator to hit every branch.
    """

    def test_character_class_with_doublestar(self) -> None:
        """[ch] class inside a ** pattern routes through _glob_to_regex."""
        assert _pattern_matches("src/**/*.[ch]", "src/lib/main.c") is True
        assert _pattern_matches("src/**/*.[ch]", "src/lib/main.h") is True
        assert _pattern_matches("src/**/*.[ch]", "src/lib/main.o") is False

    def test_negated_character_class(self) -> None:
        """[!...] negation class inside a ** pattern."""
        assert _pattern_matches("src/**/*.[!o]", "src/lib/main.c") is True
        assert _pattern_matches("src/**/*.[!o]", "src/lib/main.o") is False

    def test_character_class_with_leading_bracket(self) -> None:
        """A class whose first char is ``]`` — []] matches a literal ``]``."""
        # Pattern: match files named "x]" two+ dirs deep via **.
        assert _pattern_matches("a/**/x[]]", "a/b/x]") is True
        assert _pattern_matches("a/**/x[]]", "a/b/xz") is False

    def test_question_mark_with_doublestar(self) -> None:
        """? single-char match via _glob_to_regex (needs **)."""
        assert _pattern_matches("docs/**/file?.md", "docs/api/file1.md") is True
        assert _pattern_matches("docs/**/file?.md", "docs/api/fileAB.md") is False

    def test_single_star_with_doublestar(self) -> None:
        """Single * (match non-slash) combined with ** in same pattern."""
        assert _pattern_matches("src/**/*.test.js", "src/a/b/foo.test.js") is True
        assert _pattern_matches("src/**/*.test.js", "src/a/b/foo.test.ts") is False

    def test_doublestar_at_end(self) -> None:
        """``**`` at end of pattern matches everything remaining."""
        assert _pattern_matches("vendor/**", "vendor/lib.py") is True
        assert _pattern_matches("vendor/**", "vendor/deep/nested/file.py") is True
        assert _pattern_matches("vendor/**", "other/lib.py") is False

    def test_literal_chars_escaped(self) -> None:
        """Literal dots and other regex-special chars are escaped."""
        assert _pattern_matches("src/**/config.json", "src/app/config.json") is True
        assert _pattern_matches("src/**/config.json", "src/app/configXjson") is False


# ---------------------------------------------------------------------------
# _build_team_entries
# ---------------------------------------------------------------------------


class TestBuildTeamEntries:
    """Direct tests for the team entry builder."""

    def test_builds_normalized_entries(self) -> None:
        tid = uuid4()
        entries = _build_team_entries([(tid, "My Cool Team")])
        assert len(entries) == 1
        assert entries[0].team_id == tid
        assert entries[0].raw_name == "My Cool Team"
        assert entries[0].normalized == "my-cool-team"

    def test_empty_input(self) -> None:
        assert _build_team_entries([]) == []

    def test_preserves_order(self) -> None:
        ids = [uuid4() for _ in range(3)]
        names = ["alpha", "beta", "gamma"]
        entries = _build_team_entries(list(zip(ids, names)))
        assert [e.raw_name for e in entries] == names


# ---------------------------------------------------------------------------
# resolve_owner — additional edge cases
# ---------------------------------------------------------------------------


class TestResolveOwnerEdgeCases:
    """Edge cases not covered by TestResolveOwner."""

    def test_at_prefixed_owner_without_org(self) -> None:
        """@team-name (no org/) should still resolve."""
        tid = uuid4()
        teams = _build_team_entries([(tid, "backend-team")])
        resolved_id, _, confidence = resolve_owner("@backend-team", teams)
        assert resolved_id == tid
        assert confidence == "exact"

    def test_reverse_substring_match(self) -> None:
        """Team name is a substring of the owner string → fuzzy match."""
        tid = uuid4()
        teams = _build_team_entries([(tid, "api")])
        resolved_id, _, confidence = resolve_owner("@org/api-team", teams)
        assert resolved_id == tid
        assert confidence == "fuzzy"

    def test_empty_teams_list(self) -> None:
        tid, name, confidence = resolve_owner("@org/anything", [])
        assert tid is None
        assert name is None
        assert confidence is None

    def test_at_sign_with_slash_is_not_email(self) -> None:
        """@org/user contains '@' and '/' — should NOT be treated as email."""
        tid = uuid4()
        teams = _build_team_entries([(tid, "user")])
        resolved_id, _, _ = resolve_owner("@org/user", teams)
        assert resolved_id == tid


# ---------------------------------------------------------------------------
# suggest_owners_bulk — additional scenarios
# ---------------------------------------------------------------------------


class TestSuggestOwnersBulkEdgeCases:
    """Additional bulk evaluation scenarios."""

    def test_multiple_distinct_patterns_collected(self) -> None:
        """Different paths matching different rules produce distinct suggestions."""
        team_a = uuid4()
        team_b = uuid4()
        teams: list[tuple[UUID, str]] = [
            (team_a, "api-team"),
            (team_b, "web-team"),
        ]
        rules = parse_codeowners("/api/ @org/api-team\n/web/ @org/web-team\n")
        result = suggest_owners_bulk(rules, ["api/routes.py", "web/index.tsx"], teams)
        assert len(result.suggestions) == 2
        owners = {s.raw_owner for s in result.suggestions}
        assert owners == {"@org/api-team", "@org/web-team"}
        assert result.unresolved_owners == []

    def test_mixed_resolved_and_unresolved(self) -> None:
        tid = uuid4()
        teams: list[tuple[UUID, str]] = [(tid, "known-team")]
        rules = parse_codeowners("/a/ @org/known-team\n/b/ @org/mystery-team\n")
        result = suggest_owners_bulk(rules, ["a/f.py", "b/f.py"], teams)
        assert len(result.suggestions) == 2
        resolved = [s for s in result.suggestions if s.suggested_team_id is not None]
        assert len(resolved) == 1
        assert resolved[0].suggested_team_id == tid
        assert "@org/mystery-team" in result.unresolved_owners

    def test_unresolved_owners_are_sorted(self) -> None:
        rules = parse_codeowners("/a/ @z-team\n/b/ @a-team\n")
        result = suggest_owners_bulk(rules, ["a/f.py", "b/f.py"])
        assert result.unresolved_owners == ["@a-team", "@z-team"]


# ---------------------------------------------------------------------------
# Pattern matching — additional edge cases
# ---------------------------------------------------------------------------


class TestPatternMatchingEdgeCases:
    """Edge cases for CODEOWNERS glob matching."""

    def test_root_anchored_specific_file(self) -> None:
        """/Makefile matches only at root."""
        assert _pattern_matches("/Makefile", "Makefile") is True
        assert _pattern_matches("/Makefile", "sub/Makefile") is False

    def test_doublestar_slash_prefix(self) -> None:
        """**/foo matches foo at any depth."""
        assert _pattern_matches("**/foo.py", "foo.py") is True
        assert _pattern_matches("**/foo.py", "a/foo.py") is True
        assert _pattern_matches("**/foo.py", "a/b/c/foo.py") is True

    def test_middle_doublestar(self) -> None:
        """a/**/z matches a/z and a/b/c/z."""
        assert _pattern_matches("a/**/z.txt", "a/z.txt") is True
        assert _pattern_matches("a/**/z.txt", "a/b/z.txt") is True
        assert _pattern_matches("a/**/z.txt", "a/b/c/z.txt") is True
        assert _pattern_matches("a/**/z.txt", "b/c/z.txt") is False

    def test_bare_directory_no_slash(self) -> None:
        """A pattern like 'docs' (no slash) matches basename."""
        assert _pattern_matches("docs", "docs") is True
        assert _pattern_matches("docs", "src/docs") is True
