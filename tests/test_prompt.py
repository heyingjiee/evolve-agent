from unittest.mock import MagicMock

from evolve.prompt import SystemPromptBuilder


class TestSystemPromptBuilder:
    def test_init_with_tools(self, tmp_path):
        mock_tools = [{"name": "bash", "description": "Run shell command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}]
        builder = SystemPromptBuilder(tmp_path, mock_tools, model="claude-sonnet-4-6")
        assert builder.tools == mock_tools
        assert builder.workdir == tmp_path

    def test_build_tool_listing_with_tools(self, tmp_path):
        mock_tools = [{"name": "bash", "description": "Run shell command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}]
        builder = SystemPromptBuilder(tmp_path, mock_tools, model="claude-sonnet-4-6")
        result = builder._build_tool_listing()
        assert "# Available tools" in result
        assert "bash(command)" in result

    def test_build_skill_listing_with_skills(self, tmp_path):
        registry = MagicMock()
        registry.describe_available.return_value = "- skill1: Test skill"
        builder = SystemPromptBuilder(tmp_path, [], skill_registry=registry, model="claude-sonnet-4-6")
        result = builder._build_skill_listing()
        assert "# Available skills" in result
        assert "skill1" in result

    def test_build_skill_listing_without_registry(self, tmp_path):
        builder = SystemPromptBuilder(tmp_path, [], model="claude-sonnet-4-6")
        assert builder._build_skill_listing() == ""

    def test_build_agent_md_exists(self, tmp_path):
        (tmp_path / "AGENT.md").write_text("# Project Agent\n\nDo stuff.")
        builder = SystemPromptBuilder(tmp_path, [], model="claude-sonnet-4-6")
        result = builder._build_agent_md()
        assert "# AGENT.md instructions" in result
        assert "# Project Agent" in result

    def test_build_dynamic_context(self, tmp_path):
        builder = SystemPromptBuilder(tmp_path, [], model="claude-sonnet-4-6")
        result = builder._build_dynamic_context()
        assert "# Dynamic context" in result
        assert "claude-sonnet-4-6" in result
        assert str(tmp_path) in result

    def test_memory_section_included_in_output(self, tmp_path):
        memory_manager = MagicMock()
        memory_manager.load_memory_prompt.return_value = "# Custom Memory Section"
        builder = SystemPromptBuilder(tmp_path, [], memory_manager=memory_manager, model="claude-sonnet-4-6")
        result = builder.build()
        assert "# Custom Memory Section" in result
        memory_manager.load_memory_prompt.assert_called_once()
