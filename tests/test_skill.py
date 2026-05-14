from evolve.tools.skill import SkillRegistry


class TestSkillRegistry:
    """Skill 加载能力测试"""

    def test_load_single_skill(self, tmp_path):
        """测试加载单个 skill"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        skill_file = skill_dir / "test_skill" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
name: test_skill
description: 测试技能
---
# Test Skill

这是测试内容
""")

        registry = SkillRegistry(skill_dir)
        assert "test_skill" in registry.documents
        doc = registry.documents["test_skill"]
        assert doc.manifest.name == "test_skill"
        assert doc.manifest.description == "测试技能"

    def test_load_multiple_skills(self, tmp_path):
        """测试加载多个 skills"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        # 创建第一个 skill
        (skill_dir / "skill_a" / "SKILL.md").parent.mkdir()
        (skill_dir / "skill_a" / "SKILL.md").write_text("""---
name: skill_a
description: 技能A
---
Content A
""")

        # 创建第二个 skill
        (skill_dir / "skill_b" / "SKILL.md").parent.mkdir()
        (skill_dir / "skill_b" / "SKILL.md").write_text("""---
name: skill_b
description: 技能B
---
Content B
""")

        registry = SkillRegistry(skill_dir)
        assert len(registry.documents) == 2
        assert "skill_a" in registry.documents
        assert "skill_b" in registry.documents

    def test_parse_frontmatter(self, tmp_path):
        """测试解析 frontmatter"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        skill_file = skill_dir / "parse_test" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
name: parse_test
description: 测试解析
extra: 额外字段
---
# Body Content

正文内容
""")

        registry = SkillRegistry(skill_dir)
        doc = registry.documents["parse_test"]
        assert doc.manifest.name == "parse_test"
        assert doc.manifest.description == "测试解析"

    def test_parse_without_frontmatter(self, tmp_path):
        """测试没有 frontmatter 的情况"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        skill_file = skill_dir / "no_frontmatter" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""# No Frontmatter

纯内容
""")

        registry = SkillRegistry(skill_dir)
        assert "no_frontmatter" in registry.documents
        doc = registry.documents["no_frontmatter"]
        assert doc.manifest.name == "no_frontmatter"
        assert doc.manifest.description == "No description"

    def test_load_full_text(self, tmp_path):
        """测试加载完整文本内容"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        skill_file = skill_dir / "full_text" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
name: full_text
description: 完整文本测试
---
# Full Text

这里是正文
""")

        registry = SkillRegistry(skill_dir)
        full = registry.load_full_text("full_text")

        assert "<skill name=\"full_text\">" in full
        assert "# Full Text" in full
        assert "这里是正文" in full
        assert "</skill>" in full

    def test_load_full_text_unknown_skill(self, tmp_path):
        """测试加载未知 skill"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        registry = SkillRegistry(skill_dir)
        result = registry.load_full_text("unknown")

        assert "Error" in result
        assert "unknown" in result
        assert "Available skill" in result

    def test_describe_available(self, tmp_path):
        """测试描述可用 skills"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        (skill_dir / "alpha" / "SKILL.md").parent.mkdir()
        (skill_dir / "alpha" / "SKILL.md").write_text("""---
name: alpha
description: 第一个
---
""")

        (skill_dir / "beta" / "SKILL.md").parent.mkdir()
        (skill_dir / "beta" / "SKILL.md").write_text("""---
name: beta
description: 第二个
---
""")

        registry = SkillRegistry(skill_dir)
        desc = registry.describe_available()

        assert "- alpha:第一个" in desc
        assert "- beta:第二个" in desc

    def test_describe_available_empty(self, tmp_path):
        """测试没有可用 skills 时的描述"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        registry = SkillRegistry(skill_dir)
        desc = registry.describe_available()

        assert "(no skills available)" in desc

    def test_load_empty_directory(self, tmp_path):
        """测试加载空目录"""
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()

        registry = SkillRegistry(skill_dir)
        assert len(registry.documents) == 0

    def test_load_nonexistent_directory(self, tmp_path):
        """测试加载不存在的目录"""
        skill_dir = tmp_path / "nonexistent"

        registry = SkillRegistry(skill_dir)
        assert len(registry.documents) == 0
