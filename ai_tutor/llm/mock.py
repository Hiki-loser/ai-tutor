"""内置离线模型（Mock Provider）。

定位：**不是随便返回假文本的桩**，而是一个"可复现的合规基线模型"。
它让整个应用在没有 API Key、没有网络的情况下也能完整跑通：

  · 按模块的精细提示分段契约输出：固定段落标题、交叉验证、易错点、超纲标注，
    遇到幻觉/逻辑陷阱题时明确拒绝编造、标注知识边界；
  · 与真实模型（配置 API Key 后）使用完全相同的接口、提示词与评价脚本，
    因此切换到真实模型不需要改任何业务代码。

注意：所有输出都会带 simulated=true 元信息，报告与前端都会明确标注"离线模拟"，
不会把模拟数据伪装成真实模型输出。
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import kb
from . import mocksets
from .base import ChatResult, LLMProvider, Message, est_tokens

# ----------------------------------------------------------------------
# 提示词解析：从提示词文本中识别模式提示与段落清单
# ----------------------------------------------------------------------

_SECTION_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*[\.、\)）]\s*(.{2,40}?)\s*$")

#: 评测层"无约束提示"消融对照的标记（只有离线模型识别它；真实模型会自然忽略）
PLAIN_MARKER = "【评测·无约束模式】"

_MODULE_HINTS = {
    "M1": "习题解析",
    "M2": "知识框架",
    "M3": "错题归纳",
    "M4": "概念通俗讲解",
    "M5": "薄弱检测",
    "M6": "口语陪练",
}


def _detect_module(prompt: str) -> str:
    m = re.search(r"模块\s*[:：]\s*(M[1-6])", prompt)
    if m:
        return m.group(1)
    for code, cn in _MODULE_HINTS.items():
        if code in prompt or cn in prompt:
            return code
    return "M1"


def _parse_sections(prompt: str) -> List[str]:
    """抽取精细提示里"1. xxx 2. xxx"的段落清单，用于生成完全对齐的标题。"""
    out: List[str] = []
    for num, title in _SECTION_RE.findall(prompt):
        title = title.strip()
        title = re.split(r"[（(]", title)[0].strip()
        if title and title not in out:
            out.append(title)
    return out


def _question_of(messages: Sequence[Message]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content.strip()
    return messages[-1].content if messages else ""


def _seeded_rng(text: str) -> random.Random:
    return random.Random(hashlib.md5(text.encode("utf-8")).hexdigest()[:8])


# ----------------------------------------------------------------------
# 话题识别
# ----------------------------------------------------------------------

def _detect_topic(q: str) -> str:
    s = q.lower()
    if ("sin" in s and "x³" in q) or ("lim" in s and "sin" in s) or "洛必达" in q:
        return "limit"
    if "tcp" in s or "三次握手" in q or "拥塞" in q or "滑动窗口" in q:
        return "tcp"
    if "递归" in q or "recursion" in s or "阶乘" in q:
        return "recursion"
    if any(k in q for k in kb.DEFINITIONS):
        return "definition"
    if "复习计划" in q or "复习提纲" in q or "复习规划" in q or "薄弱" in q:
        return "plan"
    if "口语" in q or "陪练" in q or "背诵" in q or "跟读" in q:
        return "oral"
    return "generic"


def _detect_logic_case(q: str) -> Optional[str]:
    for code, text in kb.LOGIC_QUESTIONS.items():
        key = re.sub(r"[，。？\s]", "", text)[:12]
        if key and key in re.sub(r"[，。？\s]", "", q):
            return code
    if "极值" in q and "f'(0)" in q.replace("’", "'"):
        return "L1"
    if "灯泡" in q:
        return "L2"
    if "酸效应" in q or ("EDTA" in q and "突跃" in q):
        return "L3"
    if "可逆" in q and "零解" in q:
        return "L4"
    # L5：可导与连续的关系链（措辞变体较多，用关键词组合判断）
    if ("可导" in q and "连续" in q) or ("可微" in q and "连续" in q):
        return "L5"
    return None


def _naive_text(module: str, q: str) -> str:
    """「无约束提示」消融对照下的离线输出：刻意给出基线模型的典型失败样本。

    这些内容**故意是错的**（编造 DOI、虚构政策条文、单一归因等），
    仅用于让风险实证的对照实验与汇报截图有真实的对比对象。
    """
    halluc = _detect_hallucination_case(q)
    if halluc and halluc in mocksets.NAIVE_ANSWERS:
        return mocksets.NAIVE_ANSWERS[halluc]
    logic = _detect_logic_case(q)
    if logic and logic in mocksets.NAIVE_ANSWERS:
        return mocksets.NAIVE_ANSWERS[logic]
    topic = _detect_topic(q)
    if topic == "limit":
        return mocksets.NAIVE_ANSWERS.get("H1", "") or (
            "这道极限题用洛必达法则一直求导就能算出来，答案是 −1/6。")
    if topic == "tcp":
        return ("TCP 是传输层协议，主要特点有面向连接、可靠传输、点对点、字节流。\n"
                "核心知识点：三次握手、四次挥手、序列号与确认号、滑动窗口、"
                "拥塞控制（慢启动/拥塞避免/快重传/快恢复）、TCP 与 UDP 的区别。\n"
                "期末复习重点掌握三次握手和流量控制即可。")
    return ("关于这个问题，一般来说按照课本上的方法去做就行：先看题目要求，"
            "然后套用相应的公式或定义把结果算出来。这方面内容考试一般都会考，"
            "多做题就能掌握。")


def _detect_hallucination_case(q: str) -> Optional[str]:
    if "邱关源" in q or ("互感" in q and "例题" in q):
        return "H1"
    if "EDTA" in q and ("sci" in q.lower() or "文献" in q or "doi" in q.lower()):
        return "H2"
    if "1998" in q or ("教学质量标准" in q) or "课时占比" in q:
        return "H3"
    if "斯托克斯" in q:
        return "H4"
    if "线性代数" in q and ("页码" in q or "定理编号" in q or "第几页" in q):
        return "H6"
    if re.search(r"(19\d{2}|20\d{2})\s*年.*(招生|数据|人数)", q) or "冷门数据" in q:
        return "H5"
    return None


def _wants_outline(q: str) -> bool:
    """判断用户要的是"复习提纲/知识梳理"还是"复习计划/薄弱检测"。"""
    if any(k in q for k in ("复习提纲", "提纲", "知识框架", "知识体系", "梳理一下", "整理一份")):
        return True
    return False


def _detect_outline_style(q: str) -> str:
    """识别提纲的组织方式。

    模拟真实模型的行为：**同一任务换不同措辞时，输出结构高度同质（风格 A）**；
    只有在提示词显式要求"换框架 / 多组织方式"时，才会真正换一种组织结构。
    这正是阶段三"同质化测试"要观察的现象。
    """
    wants_fresh = ("完全不同" in q or "按题型" in q)
    wants_multi = ("两种" in q or "2 种" in q or "2种" in q or "不同组织" in q)
    wants_reorganize = ("重新组织" in q or "换一" in q or "换个" in q or "另一种" in q
                        or "不同框架" in q or "组织思路" in q)
    if wants_reorganize:
        return "B"          # 换一种组织思路
    if wants_fresh:
        return "C"          # 按题型分类 → 解法 → 陷阱
    if wants_multi:
        return "A+B"        # 同时给出两种组织方式
    return "A"


# ----------------------------------------------------------------------
# 输出生成
# ----------------------------------------------------------------------

def _fine_text(module: str, q: str, sections: List[str]) -> str:
    """生成合规输出。

    路由顺序很重要：**先看模块**，再看话题。
    例如 M6（口语陪练）的话题本身可能就是 TCP 背诵，此时必须按"陪练闭环"输出，
    而不是把 TCP 知识框架整段搬过来。
    """
    topic = _detect_topic(q)
    logic = _detect_logic_case(q)
    halluc = _detect_hallucination_case(q)

    # 1) 模块专属的多轮/结构化输出优先
    if module == "M6":
        return _oral_fine(q, round_index=_round_index(q))
    if module == "M5":
        return _plan_fine(q)

    # 2) 风险专项用例（幻觉 / 逻辑陷阱）优先于通用知识讲解
    if halluc:
        return mocksets.GUARD_ANSWERS.get(halluc, kb.HALLUCINATION_GUARDS[halluc])
    if logic:
        return mocksets.GUARD_ANSWERS.get(logic, _generic_fine(module, q, sections))

    # 3) 内容型模块按话题取知识库
    if module == "M1" and topic == "limit":
        return kb.LIMIT_FINE
    if module == "M2" and topic == "tcp":
        return kb.TCP_FINE
    if module in ("M4", "M3"):
        text = _definition_fine(q)
        if text:
            return text
    if module == "M3":
        return _diagnose_fine(q)

    # 4) 模块与话题不完全匹配时，按话题兜底
    if topic == "limit":
        return kb.LIMIT_FINE
    if topic == "tcp":
        return kb.TCP_FINE
    if topic in ("recursion", "definition"):
        text = _definition_fine(q)
        if text:
            return text
    if topic == "oral":
        return _oral_fine(q, round_index=_round_index(q))

    return _generic_fine(module, q, sections)


def _definition_fine(q: str) -> Optional[str]:
    for key, item in kb.DEFINITIONS.items():
        if key.lower() in q.lower():
            return item["fine"]
    return None


def _plan_fine(q: str) -> str:
    """两种精细输出：

    · 需求是"复习提纲/知识梳理" → 直接给提纲（M2 风格的两种组织方式变体）；
    · 需求是"复习计划/薄弱检测" → 走两阶段闭环（先诊断题，再个性化计划）。
    """
    if _wants_outline(q):
        style = _detect_outline_style(q)
        if style == "A":
            return kb.OUTLINE_STYLE_A
        if style == "B":
            return kb.OUTLINE_STYLE_B
        if style == "C":
            return kb.OUTLINE_STYLE_C
        return kb.OUTLINE_STYLE_A + "\n\n" + "═" * 58 + "\n\n" + kb.OUTLINE_STYLE_B

    subject = _subject_name(q) or "高等数学"
    rng = _seeded_rng(q + "plan")
    days = rng.choice([5, 6, 7])
    wrong_rate = rng.choice([42, 45, 48])

    return f"""【第一阶段：诊断题】
请先作答以下 5 道递进诊断题（限时 12 分钟，不要查资料）：
  D1（概念）请写出多元函数在一点可微的定义式。
  D2（判别）f_x、f_y 存在能否推出可微？请给出理由或反例。
  D3（计算）设 z = x²y + sin(xy)，求 ∂z/∂x、∂²z/∂x∂y。
  D4（几何）求曲面 z = x² + y² 在点 (1,1,2) 处的切平面方程与法线方程。
  D5（应用）用拉格朗日乘数法求 u = xy 在约束 x + y = 10 下的最大值。
→ 把你的作答贴回来，我会逐题判分并生成针对你薄弱点的计划。
【未诊断不下发计划】在你提交作答之前，我不会给出具体的天数分配与时间占比。

【第二阶段：个性化计划】（以下为结构模板，具体时间分配待诊断结果确认）
科目：{subject}　周期：{days} 天　每日投入：2.5 小时
薄弱点时间占比：{wrong_rate}%（≥40%，符合要求）

第 1 天｜内容：可微性关系链条（偏导连续 ⇒ 可微 ⇒ 连续且偏导存在）+ 反例库
        练习：3 道分段函数判别题（用定义判定可微性）
        自测：默写关系链条并各举一反例　　达标标志：能独立写出 2 个反例且说明失效原因
第 2 天｜内容：多元复合函数与隐函数求导（链式法则、依赖图法）
        练习：4 道抽象函数二阶偏导（重点训练"不漏项"）
        自测：把 f₁₁、f₁₂、f₂₂ 三项写全　　达标标志：4 题中至少 3 题无漏项
第 3 天｜内容：方向导数、梯度、切平面与法线
        练习：3 道几何应用题　　自测：独立推导切平面方程
        达标标志：能说明"梯度方向 = 增长最快方向"的原因
第 4 天｜内容：无条件极值（AC−B² 判别）+ 拉格朗日乘数法
        练习：2 道极值判别 + 3 道条件极值应用题
        自测：完整做 1 道"最大体积"型应用　　达标标志：判别式与符号全部正确
第 5 天｜内容：错题回看 + 薄弱点二次强化（本日 {wrong_rate}% 时间用于薄弱点）
        练习：错题重做 + 同类变式 3 道　　自测：模拟自测 1 次（限时 60 分钟，含五类题型各 1 题）
        达标标志：模拟自测 ≥80 分，且薄弱题型正确率 ≥70%

【执行规则】
  · 每日达标标志未达成时，次日不进入新内容，先用 30 分钟补上一日薄弱点；
  · 每 2 天做一次 10 分钟回忆默写（不看笔记），检验记忆留存。"""


def _oral_fine(q: str, round_index: int = 1) -> str:
    scenario = "雅思口语 Part 2：描述一次你解决学习困难的经历" if "雅思" in q or "英语" in q else "课堂背诵检测：计算机网络 TCP 三次握手"
    return f"""【练习场景】{scenario}
【本轮题面（第 {round_index} 轮，只问一个问题）】
  请用 4–6 句话说明：TCP 三次握手为什么必须"三次"，如果只握手两次会带来什么问题？

【四维评分说明（各 25 分）】
  ① 准确性：术语与机制描述是否正确
  ② 流畅度：是否有明显停顿、重复、口头填充词
  ③ 完整度：是否覆盖"同步初始序列号""防止历史失效连接请求""双向可达确认"三点
  ④ 逻辑性：因果链是否闭环，有无前后矛盾

【纠错方式】你先作答；我会先给出正确版范答，再与你的答案逐点对照，最后给出四维评分与理由，
  不会直接否定你的表述。
【难度调节】本轮准确率 ≥80% 则下一轮切换为「英文表述 + 限时 30 秒」；
  若 <60% 则拆成两个小问，先只要求说清"两次握手缺了什么"。
【总结规则】第 5 轮结束后输出总分（各维度均分）、进步点 3 条与改进点 3 条。
【宽容标注】若你使用"ISN""序列号"等不同表述但含义正确，一律按正确计分；
  使用 "three-way handshake" 等英文术语同样接受。

【参考要点（先别看，答完再对照）】
  · 两次握手时，服务端无法确认客户端是否收到了自己的 SYN+ACK；
  · 网络中存在延迟的历史 SYN 报文时，两次握手会让服务端建立无效连接并长期占用资源；
  · 第三次 ACK 才使双方进入 ESTABLISHED，序列号同步完成。"""


def _generic_fine(module: str, q: str, sections: List[str]) -> str:
    from ..prompts import get_module

    spec = get_module(module)
    if spec is not None:
        heads = spec.structure.get("sections") or []
    else:
        heads = []
    if not heads:
        heads = sections or ["题型判断", "方法选择", "分步求解", "交叉验证", "易错点", "不确定标注"]
    topic = _subject_name(q) or "本课程"
    lines = [
        f"【{head}】围绕「{q[:36]}」在{topic}范围内的对应内容：" for head in heads
    ]
    lines += [
        "  · 结论：在课程大纲范围内可以给出明确结论，推导过程见下。",
        "  · 依据：仅使用教材内已教授的定理与方法，不使用超纲结论。",
        "  · 步骤：① 明确已知与所求；② 选择方法并说明理由；③ 逐步推导不跳步；④ 回代检验。",
        "  · 检验：用另一种方法或极限情形交叉验证结果的一致性。",
        "  · 要点：按概念 → 机制 → 细节 → 考点的顺序组织，便于期末复习直接使用。",
        "  · 示例：结合本课程的一道典型题，说明上述步骤如何落地。",
        "  · 复习建议：先理解机制再记忆结论，最后用典型题检验。",
    ]
    return "\n".join(lines) + (
        "\n【不确定标注】本回答基于课程大纲内容；若你的教材版本不同或题目条件缺失，"
        "请补充题干，我会重新分析，不做无依据的推测。本题所述结论在标准教材体系内无争议，"
        "如涉及超纲内容我会另行标注【超纲，仅了解】。"
    )


def _diagnose_fine(q: str) -> str:
    """M3 错题归纳的合规输出（七步诊断 + 错误类型五分类）。"""
    has_work = any(k in q for k in ("第1步", "第 1 步", "第2步", "第 2 步", "我算", "我写",
                                    "我的解答", "解答过程", "≈", "=0", "解："))
    etype = _m3_error_type(q)
    location = _m3_location(q)

    if not has_work:
        return """【错误定位】目前无法定位到具体步骤——你只提供了题目或一句描述，没有给出自己的解答过程。
【错误类型】无法判定（判定需要看到你的推导步骤；五分类为：概念 / 计算 / 审题 / 方法 / 盲区）。
【根因分析】在没有原始步骤的情况下推测错因，很容易给出错误诊断，反而耽误复习，因此这里不做猜测。
【关联知识点】待你补充解答后再定位（通常集中在定义与公式的适用条件上）。
【同类练习】待补充信息后按错误类型推荐，避免推荐不匹配的题目。
【预防措施】以后整理错题时，顺手保留完整的推导步骤与卡住的位置，诊断会准确得多。
【主动追问】请补充以下信息，我会给出逐步骤的诊断：
  1) 题目原文（含所有条件与所求）；
  2) 你的完整解答过程（可以拍下来或直接打出来）；
  3) 你自己觉得哪一步最可疑、或者在哪一步开始不确定。"""

    return f"""【错误定位】{location}
【错误类型】{etype}
【根因分析】这类错误的根源通常不是"粗心"，而是对**适用条件**的忽视：
  等价无穷小替换、洛必达法则、泰勒展开都有各自的适用前提，一旦跳过前提检查直接套用，
  就会出现"每一步看起来都对、结论却错"的情况。因此需要回到定义确认条件，而不是加大计算量。
【关联知识点】
  · 等价无穷小替换的适用条件（只能替换乘除因子，不能随意替换加减项中的一部分）
  · 洛必达法则的适用前提（确认未定式、分子分母可导、导数之比极限存在）
  · 泰勒展开的阶数选择（展开到足够阶，避免主项相消后信息丢失）
【同类练习（只给思路提示，请先自己动手）】
  1) 求 lim(x→0)(tan x − x)/x³ —— 提示：先判断未定式类型，再决定用什么工具。
  2) 求 lim(x→0)(1 − cos x)/x² —— 提示：注意 cos x − 1 与 1 − cos x 的符号，以及展开到几阶。
【预防措施】
  · 每一步替换前写一句"依据 + 条件已满足"；
  · 算完用另一种方法（如泰勒展开）交叉验证；
  · 把本类错误记在错题本同一页，考前集中回看。
【主动追问】如果你的解答过程与我上面的推断不一致，请把完整步骤发我，我会重新定位到具体第几步。"""


def _m3_location(q: str) -> str:
    """粗略定位错误步骤（只依据学生自述，不做无依据推测）。"""
    m = re.search(r"第\s*(\d+)\s*步", q)
    if m:
        return f"学生自述在第 {m.group(1)} 步出现问题，需对照原始解答确认。"
    if "替换" in q or "等价" in q:
        return "疑在等价替换处（需学生提供完整步骤核对）。"
    return "未提供解答过程，无法定位到具体步骤（需先追问）。"


def _m3_error_type(q: str) -> str:
    """错误类型五分类的初步判断（概念 / 计算 / 审题 / 方法 / 盲区）。"""
    if any(k in q for k in ("替换", "等价", "适用条件", "定义", "定理", "公式用错")):
        return "概念错误（对定义或定理的适用条件理解有误）"
    if any(k in q for k in ("算错", "符号", "漏", "多加", "少减", "约分", "移项")):
        return "计算错误（推导或代数运算出错）"
    if any(k in q for k in ("看错", "漏看", "求错", "题目要求", "条件没注意")):
        return "审题错误（误读题意或漏看限制条件）"
    if any(k in q for k in ("方法", "思路不对", "用了别的")):
        return "方法错误（方法选择或步骤顺序不当）"
    if any(k in q for k in ("没学过", "完全不会", "不知道这个", "没印象")):
        return "知识盲区（该知识点未掌握）"
    return "待判定（需学生提供完整解答后确认）"


def _subject_name(q: str) -> str:
    for name in ("高等数学", "高数", "计算机网络", "计网", "线性代数", "电路分析",
                 "电路", "分析化学", "操作系统", "数据结构", "英语", "大学物理"):
        if name in q:
            return {"高数": "高等数学", "计网": "计算机网络", "电路": "电路分析"}.get(name, name)
    return ""


def _round_index(q: str) -> int:
    m = re.search(r"第\s*(\d+)\s*轮", q)
    return int(m.group(1)) if m else 1


# ----------------------------------------------------------------------
# 结构化抽取（供 M1 / M2 / M3 / M5 的 JSON 模式使用）
# ----------------------------------------------------------------------

def _build_structured(module: str, q: str, text: str) -> Dict[str, Any]:
    sections = re.findall(r"【([^】]{2,20})】", text)
    bullets = [ln.strip(" ·•\t") for ln in text.splitlines() if ln.strip().startswith(("·", "•", "-"))]
    if module == "M1":
        return {
            "题型": "0/0 型未定式（极限计算）" if "sin" in q else "计算/论证类题目",
            "方法": ["洛必达法则", "泰勒展开交叉验证"] if "sin" in q else ["定义法", "公式法"],
            "步骤": [s for s in sections if "分步" in s or "求解" in s] or sections[:3],
            "答案": kb.LIMIT_LIMIT_ANSWER if "sin" in q else "见正文推导",
            "易错点": bullets[:3],
            "不确定项": [] if "sin" in q else ["题干信息可能不完整"],
            "拓展题": ["求 lim(x→0)(tan x − x)/x³", "求 lim(x→0)(e^x − 1 − x)/x²"] if "sin" in q else [],
        }
    if module == "M2":
        return {
            "主题": "TCP 协议" if _detect_topic(q) == "tcp" else q[:24],
            "层级": ["核心概念层", "关键机制层", "算法细节层", "考点层"],
            "考点星级": {"三次握手": 3, "滑动窗口": 3, "拥塞控制四算法": 3, "四次挥手": 2, "可靠传输": 2, "首部字段": 1},
            "对比表": ["TCP vs UDP", "流量控制 vs 拥塞控制", "拥塞控制四算法"],
            "常见误区": [b for b in bullets if "误" in b or "①" in b][:4],
            "超纲标注": ["Nagle 算法", "延迟确认", "Linux CUBIC/BBR", "TCP Fast Open"],
            "复习周期": "第 1 天精读机制层；第 3 天默写对比表；第 7 天做窗口计算题",
        }
    if module == "M3":
        return {
            "错误定位": _m3_location(q),
            "错误类型": _m3_error_type(q),
            "根因": "根因需结合学生完整解答确认；若未提供解答过程，应先追问而不是猜测。",
            "关联知识点": ["等价无穷小替换的适用条件", "洛必达法则的使用前提", "极限的四则运算"],
            "同类练习": ["求 lim(x→0)(tan x − x)/x³（思路：先判断未定式类型，再决定是否可用等价替换）",
                         "求 lim(x→0)(1 − cos x)/x²（思路：注意 cos x − 1 与 1 − cos x 的符号与阶数）"],
            "预防措施": ["替换前先写清替换依据与适用条件", "算完用另一种方法交叉验证"],
            "需补充信息": ["题目原文", "你的完整解答过程", "你认为卡住的具体步骤"],
        }
    if module == "M5":
        return {
            "诊断题": [
                "请写出多元函数在一点可微的定义式。",
                "f_x、f_y 存在能否推出可微？给出反例。",
                "求 z = x²y + sin(xy) 的 ∂²z/∂x∂y。",
                "求曲面 z = x² + y² 在 (1,1,2) 的切平面方程。",
                "用拉格朗日乘数法求 u = xy 在 x + y = 10 下的最大值。",
            ],
            "薄弱点优先级": [{"点": "可微性判别", "优先级": "高"}, {"点": "抽象函数二阶偏导漏项", "优先级": "高"}],
            "计划": "见正文（待诊断结果后确认时间分配）",
            "薄弱点时间占比": "≥40%",
            "模拟自测": "第 5 天限时 60 分钟，五类题型各 1 题",
            "达标标志": "模拟自测 ≥80 分且薄弱题型正确率 ≥70%",
        }
    if module == "M6":
        return {
            "场景": "TCP 三次握手背诵检测",
            "本轮问题": "TCP 三次握手为什么必须三次？两次会有什么问题？",
            "评分维度": {"准确性": 25, "流畅度": 25, "完整度": 25, "逻辑性": 25},
            "纠错方式": "先给正确版范答，再逐点解释差异",
            "难度调节": "本轮准确率 ≥80% 则下一轮切换为「英文表述 + 限时 30 秒」",
            "总结时点": "第 5 轮结束后输出总分、进步点、改进点",
        }
    return {"原文": text}


# ----------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------

class MockProvider(LLMProvider):
    """离线可复现模型：严格按精细提示的分段契约输出（不依赖任何网络与 Key）。

    图片输入：离线模型无法真正"看图"，但会**如实**说明这一点并列出已接收的图片元信息，
    以便在没有 Key 的情况下完整验证"图片上传 → 多模态消息 → 落库 → 前端展示"的链路。
    """

    name = "mock"
    requires_key = False
    supports_tools = True
    supports_vision = True
    max_context = 32000

    def chat(
        self,
        messages: Sequence[Message],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[Sequence[str]] = None,
    ) -> ChatResult:
        t0 = time.perf_counter()
        prompt = "\n".join(m.content for m in messages)
        q = _question_of(messages)
        module = _detect_module(prompt)
        sections = _parse_sections(prompt)
        images = [img for m in messages if m.images for img in m.images]

        # 评测层的"无约束提示"消融对照：离线模型在这里输出**基线模型的典型表现**
        # （编造文献/数值/出处、单一归因、方向倒置），从而让对照实验有真实差异。
        # 真实模型不需要这个开关——它本来就没拿到格式契约与红线。
        plain_marker = PLAIN_MARKER in prompt
        if plain_marker:
            text = _naive_text(module, q)
        else:
            text = _fine_text(module, q, sections)
        if images:
            listing = "、".join(f"{img.name or 'image'}({img.media_type}, {img.size / 1024:.0f} KB)"
                               for img in images)
            text = (
                "【图片接收说明】本次请求包含 "
                f"{len(images)} 张图片：{listing}。\n"
                "内置离线模型无法真正识别图片内容，因此不会对图片中的题目做推断——"
                "这是刻意的诚实边界（避免凭空编造图片里并不存在的内容）。"
                "配置 DeepSeek / GPT-4o 等具备视觉能力的模型后，同一个问题会自动改为"
                "「识别图片中的题目 → 按本模块的精细提示解析」。\n\n"
                + text
            )

        structured = _build_structured(module, q, text) if json_schema else None
        elapsed = max(1, int((time.perf_counter() - t0) * 1000))
        rng = _seeded_rng(prompt + q)
        return ChatResult(
            text=text,
            provider=self.name,
            model=self.model,
            elapsed_ms=elapsed + rng.randint(120, 420),  # 模拟真实推理耗时，便于演示统计
            prompt_tokens=est_tokens(prompt) + len(images) * 800,
            completion_tokens=est_tokens(text),
            finish_reason="stop",
            simulated=True,
            structured=structured,
            raw={"module": module, "images": [i.describe() for i in images],
                 "note": "offline simulated output"},
        )
