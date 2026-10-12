"""提示词库的数据结构与注册表。

对应阶段二交付物：**可复用的精细提示词模板（六大模块）**。

每个模块包含：
  · 角色设定（role）
  · 任务描述（task）
  · 精细提示（fine_prompt，生产使用，六/七/八段式结构约束）
  · 输出格式（output_format）
  · 质量红线（redlines）
  · 不确定标记要求（uncertainty_rules）
  · 受众适配（audience）
  · 推荐温度与路由任务类型

设计方法论（阶段二"五要素框架"）：
  精细提示 = 角色锁定 + 格式模板 + 质量红线 + 诚实边界 + 受众适配

说明：应用对外**只使用精细提示**。用于风险实证的"无约束提示"对照属于评测层的
内部消融机制（见 ai_tutor/eval/cases.py 的 plain_prompt 字段），不作为用户可见的模式。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: 精细提示的结构模式
STRUCTURE_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "six_step": {
        "label": "六段式（习题解析）",
        "sections": ["题型判断", "方法选择", "分步求解", "交叉验证", "易错点", "不确定标注"],
        "requirements": [
            "① 题型判断：给出题目类型与难度，并说明判定依据（如“0/0 型未定式”）",
            "② 方法选择：列出首选方法与备选方法，并说明选择理由",
            "③ 分步求解：逐步推导，标注所用定理或公式，禁止跳步",
            "④ 交叉验证：用另一种方法（如泰勒展开 vs 洛必达）验证答案一致",
            "⑤ 易错点：列出 2–3 个典型错误及其原因",
            "⑥ 不确定标注：标注争议点、适用边界、信息不足，并附 1–2 道同类拓展题",
        ],
    },
    "seven_layer": {
        "label": "七段式（知识框架）",
        "sections": ["知识分层", "关联标注", "考点星级", "对比表格", "常见误区", "深度控制", "复习周期建议"],
        "requirements": [
            "① 知识分层：按“概念 → 机制 → 细节 → 考点”四级组织",
            "② 关联标注：标注跨章节联系（如 TCP 与 IP 层、与拥塞控制的关系）",
            "③ 考点星级：每个知识点标注 ★★★ / ★★ / ★",
            "④ 对比表格：对易混概念给出对比表（如 TCP vs UDP、流控 vs 拥塞控制）",
            "⑤ 常见误区：列出 3–5 条学生典型错误观念并纠正",
            "⑥ 深度控制：明确区分大纲内与超纲内容，超纲统一标注【超纲，仅了解】",
            "⑦ 复习周期建议：给出按天推进的复习节奏建议",
        ],
    },
    "seven_diag": {
        "label": "七步诊断（错题归纳）",
        "sections": ["错误定位", "错误类型", "根因分析", "关联知识点", "同类练习", "预防措施", "主动追问"],
        "requirements": [
            "① 错误定位：精确到“第几步出错”，引用学生的原始步骤",
            "② 错误类型：五分类——概念 / 计算 / 审题 / 方法 / 盲区，并给判定理由",
            "③ 根因分析：说明为什么会出现这类错误，禁止只写“粗心”",
            "④ 关联知识点：列出需要回看的具体知识点",
            "⑤ 同类练习：给 2 道同类题，各附思路提示（不给完整答案）",
            "⑥ 预防措施：给出可执行的检查动作（如“算完后回代检验”）",
            "⑦ 主动追问：信息不足时（如学生未提供解答过程）必须先追问，不得猜测",
        ],
    },
    "eight_layer": {
        "label": "九段式（概念通俗讲解）",
        "sections": ["生活类比", "技术定义", "结构图解", "代码与逐行注释", "执行过程表",
                     "关键三要素", "初学者误区", "不确定标注"],
        "requirements": [
            "① 生活类比：用新颖贴切的生活场景类比，**禁止**使用“俄罗斯套娃”等俗套例子",
            "② 技术定义：给出严谨定义，术语准确",
            "③ 结构图解：用文字画出结构或流程（如调用栈、时序图）",
            "④ 代码与逐行注释：给出可运行示例代码，每行都要有注释",
            "⑤ 执行过程表：用表格逐层展开执行过程（含递推/回代或时序）",
            "⑥ 关键三要素：提炼最核心的 3 个要点",
            "⑦ 初学者误区：列出 2 个典型误区及其后果",
            "⑧ 不确定标注：说明有争议之处或实现差异",
        ],
    },
    "plan_diag": {
        "label": "两阶段计划（薄弱检测）",
        "sections": ["诊断题", "个性化计划", "执行规则"],
        "requirements": [
            "① 先出 5 道递进诊断题（概念→判别→计算→综合→应用），要求学生作答",
            "② 学生作答后再分析掌握程度，未作答不得给具体时间分配",
            "③ 标注薄弱点优先级（高 / 中 / 低）",
            "④ 按天安排：每日含内容 + 练习 + 自测三栏",
            "⑤ 薄弱点时间占比 ≥ 40%",
            "⑥ 含 1 次限时模拟自测，并给出每日达标标志",
            "⑦ 明确声明：未完成诊断不直接给最终计划",
        ],
    },
    "oral_loop": {
        "label": "逐轮闭环（口语背诵陪练）",
        "sections": ["练习场景", "本轮题面", "四维评分", "纠错方式", "难度调节", "总结规则"],
        "requirements": [
            "① 先设定练习场景与目标",
            "② 每轮只问一个问题，不一次抛出多个任务",
            "③ 四维评分：准确性 / 流畅度 / 完整度 / 逻辑性，各 25 分",
            "④ 纠错方式：先给正确版范答，再逐点解释差异（不直接否定学生）",
            "⑤ 自适应难度：本轮表现好则提升难度（限时、英文表述、追问）",
            "⑥ 5 轮后总结：总分 + 进步点 + 改进点",
            "⑦ 多版本答案宽容标注：同义表述按正确计分",
        ],
    },
}

#: 五要素框架（阶段二方法论，用于前端展示与文档生成）
FIVE_ELEMENTS: List[Dict[str, str]] = [
    {"element": "角色设定", "desc": "“你是一位大学课程助教”，锁定语气与专业度"},
    {"element": "输出格式", "desc": "编号段落 + 表格模板，保证结构可复用"},
    {"element": "质量约束", "desc": "“禁止跳步”“必须交叉验证”，减少幻觉与逻辑漏洞"},
    {"element": "不确定标记", "desc": "要求标注“超纲”“有争议”“信息不足”"},
    {"element": "受众适配", "desc": "“大二学生，已学完课程”，控制深度与语言"},
]


@dataclass
class ModuleSpec:
    id: str = "M0"
    title: str = ""
    pain_point: str = ""
    goal: str = ""
    role: str = ""
    task: str = ""
    audience: str = ""
    pattern: str = "six_step"
    output_format: str = ""
    redlines: List[str] = field(default_factory=list)
    uncertainty_rules: List[str] = field(default_factory=list)
    route_task: str = "general"
    temperature: float = 0.3
    json_schema: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, str]] = field(default_factory=list)

    # ------------------------------------------------------------ 提示词
    @property
    def structure(self) -> Dict[str, List[str]]:
        return STRUCTURE_PATTERNS.get(self.pattern, {"label": "", "sections": [], "requirements": []})

    def fine_prompt(self) -> str:
        ps = self.structure
        lines = [
            "【角色】" + self.role,
            "【受众】" + self.audience,
            "【任务】" + self.task,
            f"【输出格式】{ps.get('label', '')}，必须按以下编号段落输出，每段以【段名】开头，不得合并或省略：",
        ]
        for req in ps.get("requirements", []):
            lines.append("  " + req)
        if self.output_format:
            lines.append("【格式补充】" + self.output_format)
        if self.redlines:
            lines.append("【质量约束】")
            for r in self.redlines:
                lines.append("  - " + r)
        if self.uncertainty_rules:
            lines.append("【不确定标记要求】")
            for r in self.uncertainty_rules:
                lines.append("  - " + r)
        lines.append("【全局红线】禁止编造文献、数据、教材页码与政策条文；不确定时必须明确声明“未核实/无法确认”，"
                     "不得用模糊表述掩盖不确定；超出本科教学大纲的内容必须标注【超纲，仅了解】。")
        lines.append("【结构化输出】请先按上述分段给出完整讲解，最后附一个 JSON 对象（键名与上述段名一致），"
                     "便于程序归档与二次排版。")
        return "\n".join(lines)

    def prompt(self) -> str:
        """应用对外只使用精细提示。"""
        return self.fine_prompt()

    # ------------------------------------------------------------ 导出
    def to_dict(self, include_prompts: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        data["pattern_label"] = self.structure.get("label", "")
        data["sections"] = list(self.structure.get("sections", []))
        data["requirements"] = list(self.structure.get("requirements", []))
        if include_prompts:
            data["fine_prompt"] = self.fine_prompt()
        else:
            data.pop("json_schema", None)
        return data

    def to_markdown(self) -> str:
        ps = self.structure
        out = [
            f"### {self.id} · {self.title}",
            "",
            f"- **对应痛点**：{self.pain_point}",
            f"- **模块目标**：{self.goal}",
            f"- **角色设定**：{self.role}",
            f"- **受众适配**：{self.audience}",
            f"- **推荐路由任务**：`{self.route_task}`　**推荐温度**：{self.temperature}",
            f"- **结构模式**：{ps.get('label','')}",
            "",
            "**精细提示（模板原文）**",
            "",
            "```text",
            self.fine_prompt().strip(),
            "```",
            "",
        ]
        if self.redlines:
            out.append("**质量红线**")
            out.append("")
            out += [f"- {r}" for r in self.redlines]
            out.append("")
        if self.uncertainty_rules:
            out.append("**不确定标记要求**")
            out.append("")
            out += [f"- {r}" for r in self.uncertainty_rules]
            out.append("")
        if self.examples:
            out.append("**示例**")
            out.append("")
            for ex in self.examples:
                out.append(f"- 输入：`{ex.get('input','')}`")
                out.append(f"  - 期望要点：{ex.get('expect','')}")
            out.append("")
        return "\n".join(out)

    def schema_json(self) -> str:
        return json.dumps(self.json_schema, ensure_ascii=False, indent=2)
