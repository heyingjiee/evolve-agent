import os
from unittest.mock import patch

import pytest

from evolve.prompt import SystemPromptBuilder


class TestSystemPromptBuilder:
    """SystemPromptBuilder 测试"""

    @pytest.fixture
    def temp_workdir(self, tmp_path):
        """创建临时工作目录"""
        return tmp_path

    @pytest.fixture
    def mock_tools(self):
        """模拟工具列表"""
        return [
            {
                "name": "bash",
                "description": "Run shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read file contents",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        ]

    def test_init_with_tools(self, temp_workdir, mock_tools):
        """测试初始化时传入工具列表"""
        builder = SystemPromptBuilder(temp_workdir, mock_tools)
        assert builder.tools == mock_tools
        assert builder.workdir == temp_workdir

    def test_init_without_tools(self, temp_workdir):
        """测试初始化时不传工具列表"""
        builder = SystemPromptBuilder(temp_workdir)
        assert builder.tools == []
        assert builder.workdir == temp_workdir

    def test_init_with_none_tools(self, temp_workdir):
        """测试初始化时传入 None"""
        builder = SystemPromptBuilder(temp_workdir, None)
        assert builder.tools == []

    def test_build_core(self, temp_workdir):
        """测试构建核心提示词"""
        builder = SystemPromptBuilder(temp_workdir)
        core = builder._build_core()
        assert str(temp_workdir) in core
        assert "coding agent" in core

    def test_build_tool_listing_with_tools(self, temp_workdir, mock_tools):
        """测试工具列表构建"""
        builder = SystemPromptBuilder(temp_workdir, mock_tools)
        result = builder._build_tool_listing()
        assert "# Available tools" in result
        assert "bash(command)" in result
        assert "read_file(path)" in result
        assert "Run shell command" in result

    def test_build_tool_listing_without_tools(self, temp_workdir):
        """测试空工具列表"""
        builder = SystemPromptBuilder(temp_workdir, [])
        result = builder._build_tool_listing()
        assert result == ""

    def test_build_skill_listing_no_skills(self, temp_workdir):
        """测试无 skills 情况"""
        builder = SystemPromptBuilder(temp_workdir)
        with patch("prompt.tools.SKILL_REGISTRY") as mock_registry:
            mock_registry.describe_available.return_value = ""
            result = builder._build_skill_listing()
            assert result == ""

    def test_build_skill_listing_with_skills(self, temp_workdir):
        """测试有 skills 情况"""
        builder = SystemPromptBuilder(temp_workdir)
        with patch("prompt.tools.SKILL_REGISTRY") as mock_registry:
            mock_registry.describe_available.return_value = "\n- skill1: Test skill"
            result = builder._build_skill_listing()
            assert "# Available skills" in result
            assert "skill1" in result

    def test_build_agent_md_no_file(self, temp_workdir):
        """测试 AGENT.md 不存在"""
        builder = SystemPromptBuilder(temp_workdir)
        result = builder._build_agent_md()
        assert result == ""

    def test_build_agent_md_exists(self, temp_workdir):
        """测试 AGENT.md 存在"""
        agent_md = temp_workdir / "AGENT.md"
        agent_md.write_text("# Project Agent\n\nDo stuff.")
        builder = SystemPromptBuilder(temp_workdir)
        result = builder._build_agent_md()
        assert "# AGENT.md instructions" in result
        assert "## From project root (AGENT.md)" in result
        assert "# Project Agent" in result

    def test_build_dynamic_context_missing_model(self, temp_workdir):
        """测试 MODEL_ID 环境变量缺失"""
        builder = SystemPromptBuilder(temp_workdir)
        with pytest.raises(KeyError):
            builder._build_dynamic_context()

    def test_build_dynamic_context(self, temp_workdir):
        """测试动态上下文构建"""
        builder = SystemPromptBuilder(temp_workdir)
        with patch.dict(os.environ, {"MODEL_ID": "claude-sonnet-4-6"}):
            result = builder._build_dynamic_context()
            assert "# Dynamic context" in result
            assert "claude-sonnet-4-6" in result
            assert str(temp_workdir) in result

    def test_build_includes_dynamic_boundary(self, temp_workdir):
        """测试包含动态分界标识"""
        builder = SystemPromptBuilder(temp_workdir, [])
        with patch.dict(os.environ, {"MODEL_ID": "claude-sonnet-4-6"}):
            result = builder.build()
            assert "=== DYNAMIC_BOUNDARY ===" in result

    def test_build_full_prompt(self, temp_workdir, mock_tools):
        """测试完整 prompt 构建"""
        builder = SystemPromptBuilder(temp_workdir, mock_tools)
        with patch.dict(os.environ, {"MODEL_ID": "claude-sonnet-4-6"}):
            with patch("prompt.tools.SKILL_REGISTRY") as mock_registry:
                mock_registry.describe_available.return_value = ""
                result = builder.build()
                # 验证各部分都存在
                assert "coding agent" in result
                assert "# Available tools" in result
                assert "=== DYNAMIC_BOUNDARY ===" in result
                assert "# Dynamic context" in result


class TestSystemPromptBuilderEdgeCases:
    """边界情况测试"""

    def test_agents_md_with_special_characters(self, tmp_path):
        """测试 AGENT.md 包含特殊字符"""
        agent_md = tmp_path / "AGENT.md"
        agent_md.write_text("# Special Chars\n\n> quote\n- list item")
        builder = SystemPromptBuilder(tmp_path)
        result = builder._build_agent_md()
        assert "# Special Chars" in result
        assert "> quote" in result

    def test_tool_listing_handles_missing_properties(self, tmp_path):
        """测试工具 schema 缺少 properties 的情况"""
        builder = SystemPromptBuilder(
            tmp_path,
            [{"name": "test", "description": "test"}],  # 缺少 input_schema
        )
        result = builder._build_tool_listing()
        assert "test()" in result  # 参数为空

    def test_tool_listing_handles_empty_properties(self, tmp_path):
        """测试工具 schema 的 properties 为空"""
        builder = SystemPromptBuilder(
            tmp_path,
            [
                {
                    "name": "empty_tool",
                    "description": "No params",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        )
        result = builder._build_tool_listing()
        assert "empty_tool()" in result

    def test_build_dynamic_context_platform(self, tmp_path):
        """测试平台信息"""
        builder = SystemPromptBuilder(tmp_path)
        with patch.dict(os.environ, {"MODEL_ID": "test"}):
            result = builder._build_dynamic_context()
            assert "Platform:" in result


class TestSystemPromptBuilderMemorySection:
    """Memory 部分测试"""

    def test_memory_section_always_called(self, tmp_path):
        """测试 memory section 总是被调用"""
        builder = SystemPromptBuilder(tmp_path, [])
        with patch("prompt.memory_mgr.load_memory_prompt") as mock_load:
            mock_load.return_value = "# Memories"
            with patch.dict(os.environ, {"MODEL_ID": "test"}):
                builder.build()
            mock_load.assert_called_once()

    def test_memory_section_included_in_output(self, tmp_path):
        """测试 memory section 包含在输出中"""
        builder = SystemPromptBuilder(tmp_path, [])
        with patch("prompt.memory_mgr.load_memory_prompt") as mock_load:
            mock_load.return_value = "# Custom Memory Section"
            with patch.dict(os.environ, {"MODEL_ID": "test"}):
                with patch("prompt.tools.SKILL_REGISTRY"):
                    result = builder.build()
            assert "# Custom Memory Section" in result
