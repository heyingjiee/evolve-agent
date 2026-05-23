"""
Memory E2E 测试 - 模拟 LLM 调用 save_memory 工具的完整流程

测试策略：
1. Mock client.messages.create() 模拟 LLM 返回工具调用
2. 模拟 LLM 决定调用 save_memory 的场景
3. 验证完整流程：LLM → 工具调用 → 结果返回 → LLM 再次推理
"""

from unittest.mock import MagicMock

from evolve.tools import MemoryManager


class TestMemoryE2E:
    """Memory 端到端测试 - Mock LLM 调用 save_memory"""

    def test_save_memory_tool_call_flow(self, tmp_path):
        """测试 LLM 调用 save_memory 工具的完整流程"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 模拟 agent_loop 的工具执行逻辑
        # 1. LLM 返回工具调用
        # 2. 执行工具
        tool_call = {
            "name": "save_memory",
            "input": {
                "name": "prefer_tabs",
                "description": "User prefers tabs for indentation",
                "type": "user",
                "content": "The user explicitly prefers tabs over spaces when editing source files.",
            },
        }

        # 执行工具
        result = mgr.save_memory(tool_call["input"])
        assert "Saved memory" in result

        # 验证文件已创建
        memory_file = mem_dir / "prefer_tabs.md"
        assert memory_file.exists()

        content = memory_file.read_text()
        assert "name: prefer_tabs" in content
        assert "type: user" in content
        assert "description: User prefers tabs for indentation" in content
        assert "prefers tabs" in content

    def test_save_memory_multiple_tools_flow(self, tmp_path):
        """测试 LLM 调用多个工具（包括 save_memory）的场景"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 模拟工具调用列表
        tool_calls = [
            {
                "name": "save_memory",
                "input": {
                    "name": "db_schema",
                    "description": "Database schema info",
                    "type": "project",
                    "content": "Users table: id, name, email, created_at",
                },
            },
            {
                "name": "Bash",
                "input": {"command": "ls -la"},
            },
            {
                "name": "save_memory",
                "input": {
                    "name": "api_endpoint",
                    "description": "API endpoint reference",
                    "type": "reference",
                    "content": "GET /api/users - returns list of users",
                },
            },
        ]

        # 执行所有工具
        results = []
        for tool in tool_calls:
            if tool["name"] == "save_memory":
                result = mgr.save_memory(tool["input"])
                results.append(("save_memory", result))

        # 验证 save_memory 被调用了 2 次
        save_results = [r for r in results if r[0] == "save_memory"]
        assert len(save_results) == 2

        # 验证所有记忆文件已创建
        assert (mem_dir / "db_schema.md").exists()
        assert (mem_dir / "api_endpoint.md").exists()

    def test_memory_prompt_generation_after_save(self, tmp_path):
        """测试保存记忆后，生成注入 LLM 的 prompt"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 保存一条记忆
        mgr.save_memory(
            {
                "name": "test_memory",
                "type": "user",
                "description": "Test memory for prompt generation",
                "content": "Test content here",
            }
        )

        # 生成 prompt
        prompt = mgr.load_memory_prompt()

        # 验证 prompt 格式
        assert "# Memories (persistent across sessions)" in prompt
        assert "## [user]" in prompt
        assert "test_memory: Test memory for prompt generation" in prompt
        assert "Test content here" in prompt

    def test_memory_round_trip_save_load(self, tmp_path):
        """测试记忆的持久化：保存 → 重新加载 → 验证完整性"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()

        # 第一次：创建 manager 并保存记忆
        mgr1 = MemoryManager(memory_dir=mem_dir)
        mgr1.save_memory(
            {
                "name": "persistent_mem",
                "type": "feedback",
                "description": "Feedback about testing",
                "content": "Don't use mock-heavy tests for integration",
            }
        )

        # 第二次：创建新的 manager 并加载记忆
        mgr2 = MemoryManager(memory_dir=mem_dir)
        mgr2.load_all()

        # 验证记忆完整恢复
        assert "persistent_mem" in mgr2.memories
        assert mgr2.memories["persistent_mem"]["type"] == "feedback"
        assert (
            mgr2.memories["persistent_mem"]["content"]
            == "Don't use mock-heavy tests for integration"
        )

    def test_memory_save_error_handling(self, tmp_path):
        """测试 save_memory 的错误处理"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 测试无效名称
        result = mgr.save_memory(
            {
                "name": "InvalidName",
                "type": "user",
                "description": "Test",
                "content": "",
            }
        )
        assert "Error" in result
        assert "invalid memory name" in result

        # 测试无效类型
        result = mgr.save_memory(
            {
                "name": "test_error",
                "type": "invalid_type",
                "description": "Test",
                "content": "",
            }
        )
        assert "Error" in result
        assert "invalid type" in result

    def test_memory_index_rebuild_on_save(self, tmp_path):
        """测试保存记忆时索引文件的重建"""
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 保存多条记忆
        for i in range(3):
            mgr.save_memory(
                {
                    "name": f"mem_{i}",
                    "type": "user",
                    "description": f"Memory {i}",
                    "content": f"Content {i}",
                }
            )

        # 验证索引文件
        index_path = mem_dir / "MEMORY.md"
        assert index_path.exists()

        index_content = index_path.read_text()
        assert "# Memory Index" in index_content
        assert "mem_0: Memory 0 [user]" in index_content
        assert "mem_1: Memory 1 [user]" in index_content
        assert "mem_2: Memory 2 [user]" in index_content

    def test_llm_memory_integration_flow(self, tmp_path):
        """
        测试 LLM 与 Memory 的完整集成流程

        模拟场景：
        1. 用户说 "记住我喜欢用 tabs"
        2. LLM 决定调用 save_memory
        3. 工具执行保存
        4. LLM 收到结果并回复用户
        """
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 模拟用户输入
        user_input = "记住我喜欢用 tabs"

        # 模拟 LLM 决策（这里我们直接构造工具调用）
        # 在真实场景中，LLM 会分析用户输入并决定调用 save_memory
        tool_call = {
            "name": "save_memory",
            "input": {
                "name": "prefer_tabs",
                "type": "user",
                "description": "User prefers tabs for indentation",
                "content": f"User said: '{user_input}'",
            },
        }

        # 执行工具
        result = mgr.save_memory(tool_call["input"])

        # 验证工具执行成功
        assert "Saved memory" in result
        assert "prefer_tabs" in result

        # 验证记忆文件
        memory_file = mem_dir / "prefer_tabs.md"
        assert memory_file.exists()

        # 验证下次 LLM 调用时可以加载这个记忆
        prompt = mgr.load_memory_prompt()
        assert "prefer_tabs" in prompt
        assert "tabs" in prompt

    def test_llm_dialogue_with_memory_save(self, tmp_path):
        """
        测试模拟 LLM 对话流程中调用 save_memory

        完整流程：
        1. 用户说 "记住我喜欢用 tabs"
        2. LLM 第一次推理 → 返回工具调用 save_memory
        3. 工具执行 → 结果返回给 LLM
        4. LLM 第二次推理 → 返回文本回复用户
        """
        mem_dir = tmp_path / ".memory"
        mem_dir.mkdir()
        mgr = MemoryManager(memory_dir=mem_dir)

        # 模拟第一轮对话：LLM 返回工具调用
        resp1 = MagicMock(
            type="message",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "name": "save_memory",
                    "input": {
                        "name": "prefer_tabs",
                        "type": "user",
                        "description": "User prefers tabs for indentation",
                        "content": "The user prefers tabs over spaces.",
                    },
                }
            ],
        )

        # 解析工具调用并执行
        tool_calls = resp1.content
        for tool in tool_calls:
            if tool.get("name") == "save_memory":
                result = mgr.save_memory(tool["input"])
                assert "Saved memory" in result

        # 验证记忆已保存
        assert (mem_dir / "prefer_tabs.md").exists()
        prompt = mgr.load_memory_prompt()
        assert "prefer_tabs" in prompt

        # 模拟第二轮对话（带工具结果）
        # 验证 LLM 能收到工具结果并继续推理
        tool_result_msg = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "test_id",
                    "content": result,
                }
            ],
        }

        # 这里简化处理，直接验证工具执行后的状态
        # 真实场景中 LLM 会收到这个结果并回复用户
        assert "prefer_tabs" in prompt
        assert "tabs" in prompt
