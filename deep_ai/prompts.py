"""
DeepResearch AI 시스템용 프롬프트 템플릿.
모든 템플릿은 LCEL 호환을 위해 ChatPromptTemplate을 사용합니다.
언어는 호출 시 {language_instruction} 변수로 제어됩니다.
"""
from langchain_core.prompts import ChatPromptTemplate

# Language instruction appended to the system message of writing nodes.
# Empty string for English (no extra instruction needed).
LANGUAGE_INSTRUCTION: dict[str, str] = {
    "한국어": "\n\n**언어 지침: 모든 내용을 반드시 한국어로 작성하세요. 고유명사·기술 용어는 영어 병기 허용.**",
    "English": "",
}

# Default report structure injected as {report_organization} in planning prompts.
DEFAULT_REPORT_STRUCTURE = (
    "보고서 구조는 사용자 제공 주제를 분해하고 다음 형식을 사용하여 마크다운으로 종합 보고서를 작성하는 데 중점을 두어야 합니다:\n\n"
    "1. 서론 (웹 검색 불필요)\n"
    "      - 주제 영역에 대한 간단한 개요\n\n"
    "2. 본문 섹션:\n"
    "      - 각 섹션은 사용자 제공 주제의 하위 주제에 초점을 맞추어야 합니다\n"
    "      - 핵심 개념과 정의를 포함해야 합니다\n"
    "      - 적용 가능한 경우 실제 사례나 사례 연구를 제공합니다\n\n"
    "3. 결론 (웹 검색 불필요)\n"
    "      - 주요 본문 섹션을 요약하는 하나의 구조적 요소(목록 또는 표)를 목표로 합니다\n"
    "      - 보고서의 간결한 요약을 제공합니다\n\n"
    "최종 응답을 마크다운으로 생성할 때 달러 기호와 같은 특수 문자가 텍스트에 포함되어 있으면 올바른 렌더링을 위해 적절히 이스케이프해야 합니다. 예: $25.5는 \\$25.5가 되어야 합니다"
)

# Report planning: generate search queries
REPORT_PLAN_QUERY_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 보고서 계획을 돕는 전문 기술 보고서 작성자입니다.\n\n"
        "보고서는 다음 주제에 중점을 둡니다:\n{topic}\n\n"
        "보고서 구조는 다음 지침을 따릅니다:\n{report_organization}\n\n"
        "당신의 목표는 보고서 섹션 계획을 수집하는 데 도움이 되는 {number_of_queries}개의 검색 쿼리를 생성하는 것입니다.\n\n"
        "쿼리는 다음을 만족해야 합니다:\n"
        "1. 주제와 관련되어야 합니다\n"
        "2. 보고서 구조에 지정된 요구 사항을 충족하는 데 도움이 되어야 합니다\n\n"
        "쿼리를 충분히 구체적으로 만들어 고품질의 관련 소스를 찾을 수 있도록 하고 \n"
        "보고서 구조에 필요한 깊이와 폭을 다루어야 합니다.\n"
        "{language_instruction}",
    ),
    ("human", "보고서 섹션 계획에 도움이 될 검색 쿼리를 생성하세요."),
])

# Report planning: generate section list
REPORT_PLAN_SECTION_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 보고서 계획을 돕는 전문 기술 보고서 작성자입니다.\n\n"
        "목표는 보고서 섹션 개요를 생성하는 것입니다.\n\n"
        "보고서의 전체 주제는 다음과 같습니다:\n{topic}\n\n"
        "보고서는 이 조직 구조를 따라야 합니다:\n{report_organization}\n\n"
        "보고서 주요 섹션을 계획하기 위해 웹 검색에서 얻은 다음 추가 컨텍스트 정보를 반영해야 합니다:\n{search_context}\n\n"
        "이제 보고서 섹션을 생성하세요. 각 섹션에는 다음 필드가 있어야 합니다:\n"
        "- Name - 이 섹션의 이름\n"
        "- Description - 이 섹션에서 다룰 주요 주제와 개념의 간략 개요\n"
        "- Research - 이 섹션에 대해 웹 검색을 수행할지 여부\n"
        "- Content - 이 섹션의 내용. 지금은 비워둡니다.\n\n"
        "어떤 섹션이 연구가 필요한지 고려하세요.\n"
        "예: 서론과 결론은 보고서의 다른 부분에서 정보를 요약하므로 검색이 필요하지 않습니다.\n"
        "{language_instruction}",
    ),
    (
        "human",
        "보고서 섹션을 생성하세요. 응답에는 'sections' 필드가 포함되어야 하며 목록이 포함되어야 합니다. "
        "각 섹션에는 name, description, plan, research, content 필드가 있어야 합니다.",
    ),
])

# Section builder: generate search queries for a single section
REPORT_SECTION_QUERY_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신의 목표는 기술 보고서 섹션 작성을 위해 포괄적인 정보를 수집할 "
        "타겟 웹 검색 쿼리를 생성하는 것입니다.\n\n"
        "이 섹션의 주제:\n{section_topic}\n\n"
        "{number_of_queries}개의 검색 쿼리를 생성할 때 다음을 보장해야 합니다:\n"
        "1. 주제의 다양한 측면을 다룹니다(예: 핵심 기능, 실제 적용 사례, 기술 아키텍처)\n"
        "2. 주제와 관련된 구체적인 기술 용어를 포함합니다\n"
        "3. 관련이 있을 때 연도 표기(예: \"2024\")를 포함하여 최신 정보를 겨냥합니다\n"
        "4. 유사 기술/접근 방식과의 비교 또는 차별점을 찾습니다\n"
        "5. 공식 문서와 실무 구현 예제를 모두 검색합니다\n\n"
        "쿼리는 다음과 같아야 합니다:\n"
        "- 일반적인 결과를 피할 만큼 충분히 구체적이어야 합니다\n"
        "- 상세한 구현 정보를 포착할 만큼 기술적이어야 합니다\n"
        "- 섹션 계획의 모든 측면을 다룰 만큼 다양해야 합니다\n"
        "- 권위 있는 소스(문서, 기술 블로그, 학술 논문)에 집중합니다",
    ),
    ("human", "제공된 주제로 검색 쿼리를 생성하세요."),
])

# Section writer (research-backed sections)
SECTION_WRITER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 기술 보고서의 특정 섹션을 작성하는 전문 기술 작가입니다.\n\n"
        "섹션 제목:\n{section_title}\n\n"
        "이 섹션의 주제:\n{section_topic}\n\n"
        "작성 지침:\n\n"
        "1. 기술적 정확성:\n"
        "- 구체적인 버전 번호를 포함하세요\n"
        "- 구체적인 지표/벤치마크를 참조하세요\n"
        "- 공식 문서를 인용하세요\n"
        "- 기술 용어를 정확하게 사용하세요\n\n"
        "2. 길이 및 스타일:\n"
        "- 엄격히 150-200 단어 제한\n"
        "- 마케팅 언어 금지\n"
        "- 기술 중심\n"
        "- 불필요하게 복잡한 단어를 사용하지 말고 간단하고 명확한 언어로 작성하세요\n"
        "- 가장 중요한 통찰을 **굵게** 시작하세요\n"
        "- 짧은 단락 사용(최대 2-3문장)\n\n"
        "3. 구조:\n"
        "- 섹션 제목에 ## 사용(마크다운 형식)\n"
        "- 명확성을 높이는 경우에만 하나의 구조적 요소 사용:\n"
        "  * 2-3개의 핵심 항목을 비교하는 집중된 표(마크다운 테이블 문법)\n"
        "  * 또는 적절한 마크다운 목록 구문을 사용하는 짧은 목록(3-5개 항목)\n"
        "- ### Sources로 끝내고 실제로 인용하거나 바꿔 쓴 소스만 나열하세요\n"
        "  * 제공된 소스 자료에서 제목과 URL을 정확히 복사하세요\n"
        "  * 형식: `- [context의 제목] : [context의 URL]`\n"
        "  * 제목이나 URL을 발명, 추측하거나 만들지 마세요\n"
        "  * 직접 사용하지 않은 경우 Sources 섹션을 포함하지 마세요\n\n"
        "3. 작성 접근:\n"
        "- 가능한 경우 최소 하나의 구체적 예시 또는 사례 연구를 포함하세요\n"
        "- 일반적인 진술보다 구체적인 세부 정보를 사용하세요\n"
        "- 단어 하나하나가 중요하도록 작성하세요\n"
        "- 섹션 내용 생성 전에 서론 금지\n\n"
        "4. 이 섹션을 작성하는 데 도움이 되는 웹 검색에서 얻은 자료를 사용하세요:\n{context}\n\n"
        "5. 품질 검사:\n"
        "- 형식은 마크다운이어야 합니다\n"
        "- 제목과 출처를 제외하고 정확히 150-200 단어여야 합니다\n"
        "- 굵은 통찰로 시작하세요\n"
        "- 사전 설명 없이 바로 내용 생성\n"
        "- 특수 문자가 포함된 경우 달러 기호 등은 \\$25.5처럼 올바르게 이스케이프하세요\n"
        "{language_instruction}",
    ),
    ("human", "제공된 소스를 기반으로 보고서 섹션을 생성하세요."),
])

# Final section writer (introduction / conclusion — no web search)
FINAL_SECTION_WRITER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 보고서의 나머지 내용을 종합하는 섹션을 작성하는 전문 기술 작가입니다.\n\n"
        "섹션 제목:\n{section_title}\n\n"
        "이 섹션의 주제:\n{section_topic}\n\n"
        "이미 완료된 섹션의 사용 가능한 보고서 내용:\n{context}\n\n"
        "1. 섹션별 접근:\n\n"
        "서론의 경우:\n"
        "- 보고서 제목에 # 사용(마크다운 형식)\n"
        "- 50-100 단어 제한\n"
        "- 간단하고 명확한 언어로 작성\n"
        "- 1-2단락에서 보고서의 핵심 동기에 집중\n"
        "- 구조적 요소 사용 금지(목록 또는 표 없음)\n"
        "- 출처 섹션 필요 없음\n\n"
        "결론/요약의 경우:\n"
        "- 섹션 제목에 ## 사용(마크다운 형식)\n"
        "- 100-150 단어 제한\n"
        "- 비교 보고서의 경우: 집중 비교 표 포함\n"
        "- 비교 보고서가 아닌 경우: 내용을 요약하는 데 도움이 된다면 최대 하나의 구조적 요소만 사용\n"
        "- 구체적인 다음 단계 또는 시사점으로 마무리\n"
        "- 출처 섹션 필요 없음\n\n"
        "3. 작성 접근:\n"
        "- 일반적인 진술보다 구체적인 세부 정보를 사용하세요\n"
        "- 단어 하나하나가 중요하도록 작성하세요\n\n"
        "4. 품질 검사:\n"
        "- 서론: 50-100 단어 제한, # 사용, 구조적 요소 없음\n"
        "- 결론: 100-150 단어 제한, ## 사용, 최대 하나의 구조적 요소\n"
        "- 마크다운 형식\n"
        "- 단어 수나 사전 설명을 포함하지 마세요\n"
        "- 특수 문자가 포함된 경우 달러 기호 등은 \\$40.5처럼 올바르게 이스케이프하세요\n"
        "{language_instruction}",
    ),
    ("human", "제공된 소스를 기반으로 보고서 섹션을 작성하세요."),
])
