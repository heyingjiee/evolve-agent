import pytest

from evolve.tools import MEMORY_TYPES, MemoryManager


class TestMemoryManager:
    """MemoryManager 测试"""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """创建临时 memory 目录"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        return mem_dir

    @pytest.fixture
    def mgr(self, temp_memory_dir):
        """创建带有临时目录的 MemoryManager"""
        return MemoryManager(memory_dir=temp_memory_dir)

    def test_load_all_empty(self, mgr):
        """测试空目录加载"""
        mgr.load_all()
        assert mgr.memories == {}

    def test_load_all_with_memory_files(self, mgr, temp_memory_dir):
        """测试加载已有的记忆文件"""
        # 创建一个记忆文件
        content = """---
name: test_user
description: Test user preference
type: user
---
Test content here
"""
        (temp_memory_dir / "test_user.md").write_text(content)

        mgr.load_all()
        assert "test_user" in mgr.memories
        assert mgr.memories["test_user"]["type"] == "user"
        assert mgr.memories["test_user"]["description"] == "Test user preference"
        assert mgr.memories["test_user"]["content"] == "Test content here"

    def test_load_all_skips_memory_md(self, mgr, temp_memory_dir):
        """测试跳过 MEMORY.md 索引文件"""
        (temp_memory_dir / "MEMORY.md").write_text("# Memory Index\ntest: desc [type]")
        (temp_memory_dir / "real_memory.md").write_text(
            "---\nname: real_memory\ndescription: Real memory\ntype: user\n---\ncontent"
        )

        mgr.load_all()
        assert "real_memory" in mgr.memories
        assert "MEMORY.md" not in mgr.memories

    def test_save_memory_valid(self, mgr, temp_memory_dir):
        """测试保存有效记忆"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "test_memory",
            "type": "user",
            "description": "Test memory description",
            "content": "Test content",
        }

        result = mgr.save_memory(memory)

        assert "Saved memory" in result
        file_path = temp_memory_dir / "test_memory.md"
        assert file_path.exists()

        text = file_path.read_text()
        assert "name: test_memory" in text
        assert "type: user" in text
        assert "description: Test memory description" in text
        assert "Test content" in text

    def test_save_memory_invalid_name(self, mgr):
        """测试无效名称被拒绝"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "InvalidName",
            "type": "user",
            "description": "Test",
            "content": "",
        }

        result = mgr.save_memory(memory)
        assert "Error" in result
        assert "invalid memory name" in result

    def test_save_memory_invalid_name_no_underscore(self, mgr):
        """测试名称必须包含下划线"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "invalidname",
            "type": "user",
            "description": "Test",
            "content": "",
        }

        result = mgr.save_memory(memory)
        assert "Error" in result
        assert "invalid memory name" in result

    def test_save_memory_invalid_type(self, mgr):
        """测试无效类型被拒绝"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "test_memory",
            "type": "invalid",
            "description": "Test",
            "content": "",
        }

        result = mgr.save_memory(memory)
        assert "Error" in result
        assert "invalid type" in result

    def test_save_memory_empty_description(self, mgr):
        """测试空描述被拒绝"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "test_memory",
            "type": "user",
            "description": "",
            "content": "",
        }

        result = mgr.save_memory(memory)
        assert "Error" in result
        assert "invalid memory description" in result

    def test_save_memory_all_types(self, mgr, temp_memory_dir):
        """测试所有合法类型都能保存"""
        from evolve.tools import Memory

        for mem_type in MEMORY_TYPES:
            name = f"test_{mem_type}"
            memory: Memory = {
                "name": name,
                "type": mem_type,
                "description": f"Test {mem_type}",
                "content": f"Content for {mem_type}",
            }

            result = mgr.save_memory(memory)
            assert "Saved memory" in result
            assert name in mgr.memories
            assert mgr.memories[name]["type"] == mem_type

    def test_save_memory_empty_content(self, mgr, temp_memory_dir):
        """测试空内容可以保存"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "test_em",
            "type": "user",
            "description": "Test",
            "content": "",
        }

        result = mgr.save_memory(memory)
        assert "Saved memory" in result

    def test_load_memory_prompt(self, mgr, temp_memory_dir):
        """测试生成 memory prompt"""
        # 添加几个记忆
        for i, mem_type in enumerate(["user", "feedback"]):
            content = f"""---
name: test_{mem_type}_{i}
description: Test {mem_type} description {i}
type: {mem_type}
---
Test content {i}
"""
            (temp_memory_dir / f"test_{mem_type}_{i}.md").write_text(content)

        mgr.load_all()
        prompt = mgr.load_memory_prompt()

        assert "# Memories (persistent across sessions)" in prompt
        assert "## [user]" in prompt
        assert "## [feedback]" in prompt
        assert "test_user_0: Test user description 0" in prompt
        assert "Test content 0" in prompt

    def test_rebuild_index(self, mgr, temp_memory_dir):
        """测试索引重建"""
        # 先保存一些记忆
        from evolve.tools import Memory

        memory: Memory = {
            "name": "idx_mem",
            "type": "user",
            "description": "Test",
            "content": "",
        }
        mgr.save_memory(memory)

        index_path = temp_memory_dir / "MEMORY.md"
        assert index_path.exists()

        index_content = index_path.read_text()
        assert "# Memory Index" in index_content
        assert "idx_mem: Test [user]" in index_content

    def test_parse_frontmatter_valid(self, mgr):
        """测试解析有效的 frontmatter"""
        text = """---
name: parse_test
description: Parse test description
type: user
---
This is the content
"""
        result = mgr._parse_frontmatter(text)

        assert result is not None
        assert result["name"] == "parse_test"
        assert result["description"] == "Parse test description"
        assert result["type"] == "user"
        assert result["content"] == "This is the content"

    def test_parse_frontmatter_invalid(self, mgr):
        """测试解析无效 frontmatter"""
        text = "No frontmatter here"
        result = mgr._parse_frontmatter(text)
        assert result is None

    def test_parse_frontmatter_multiline_content(self, mgr):
        """测试解析多行内容"""
        text = """---
name: multiline_test
description: Test
type: feedback
---
Line 1
Line 2

Line 4
"""
        result = mgr._parse_frontmatter(text)

        assert result is not None
        assert result["content"] == "Line 1\nLine 2\n\nLine 4"

    def test_update_memory(self, mgr, temp_memory_dir):
        """测试更新已存在的记忆"""
        from evolve.tools import Memory

        memory: Memory = {
            "name": "update_test",
            "type": "user",
            "description": "Original description",
            "content": "Original content",
        }
        mgr.save_memory(memory)

        # 更新
        updated: Memory = {
            "name": "update_test",
            "type": "user",
            "description": "Updated description",
            "content": "Updated content",
        }
        mgr.save_memory(updated)

        assert mgr.memories["update_test"]["description"] == "Updated description"
        assert mgr.memories["update_test"]["content"] == "Updated content"

        # 验证文件也被更新
        file_path = temp_memory_dir / "update_test.md"
        file_text = file_path.read_text()
        assert "Updated description" in file_text
        assert "Updated content" in file_text


class TestMemorySchema:
    """memory_schema 测试"""

    def test_memory_schema_structure(self):
        """测试 schema 结构正确"""
        from evolve.tools import memory_schema

        assert memory_schema["name"] == "save_memory"
        assert "input_schema" in memory_schema
        assert memory_schema["input_schema"]["type"] == "object"

        props = memory_schema["input_schema"]["properties"]
        assert "name" in props
        assert "description" in props
        assert "type" in props
        assert "content" in props

        # 验证 type enum
        assert props["type"]["enum"] == list(MEMORY_TYPES)

        # 验证 required
        assert set(memory_schema["input_schema"]["required"]) == {"name", "description", "type", "content"}


class TestMemoryTypes:
    """MEMORY_TYPES 常量测试"""

    def test_memory_types_contains_expected(self):
        """测试包含所有预期类型"""
        from evolve.tools import MEMORY_TYPES

        assert "user" in MEMORY_TYPES
        assert "feedback" in MEMORY_TYPES
        assert "project" in MEMORY_TYPES
        assert "reference" in MEMORY_TYPES
        assert len(MEMORY_TYPES) == 4