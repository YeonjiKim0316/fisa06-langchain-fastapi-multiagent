"""
Prompt templates for the DeepResearch AI system.
All templates use ChatPromptTemplate for LCEL compatibility.
Language is controlled via the {language_instruction} variable at invoke time.
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
    "The report structure should focus on breaking-down the user-provided topic "
    "and building a comprehensive report in markdown using the following format:\n\n"
    "1. Introduction (no web search needed)\n"
    "      - Brief overview of the topic area\n\n"
    "2. Main Body Sections:\n"
    "      - Each section should focus on a sub-topic of the user-provided topic\n"
    "      - Include any key concepts and definitions\n"
    "      - Provide real-world examples or case studies where applicable\n\n"
    "3. Conclusion (no web search needed)\n"
    "      - Aim for 1 structural element (either a list or table) that distills the main body sections\n"
    "      - Provide a concise summary of the report\n\n"
    "When generating the final response in markdown, if there are special characters in the text, "
    "such as the dollar symbol, ensure they are escaped properly for correct rendering "
    "e.g $25.5 should become \\$25.5"
)

# Report planning: generate search queries
REPORT_PLAN_QUERY_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical report writer, helping to plan a report.\n\n"
        "The report will be focused on the following topic:\n{topic}\n\n"
        "The report structure will follow these guidelines:\n{report_organization}\n\n"
        "Your goal is to generate {number_of_queries} search queries that will help gather "
        "comprehensive information for planning the report sections.\n\n"
        "The query should:\n"
        "1. Be related to the topic\n"
        "2. Help satisfy the requirements specified in the report organization\n\n"
        "Make the query specific enough to find high-quality, relevant sources while covering "
        "the depth and breadth needed for the report structure.\n"
        "{language_instruction}",
    ),
    ("human", "Generate search queries that will help with planning the sections of the report."),
])

# Report planning: generate section list
REPORT_PLAN_SECTION_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical report writer, helping to plan a report.\n\n"
        "Your goal is to generate the outline of the sections of the report.\n\n"
        "The overall topic of the report is:\n{topic}\n\n"
        "The report should follow this organizational structure:\n{report_organization}\n\n"
        "You should reflect on this additional context information from web searches "
        "to plan the main sections of the report:\n{search_context}\n\n"
        "Now, generate the sections of the report. Each section should have the following fields:\n"
        "- Name - Name for this section of the report.\n"
        "- Description - Brief overview of the main topics and concepts to be covered in this section.\n"
        "- Research - Whether to perform web search for this section of the report or not.\n"
        "- Content - The content of the section, which you will leave blank for now.\n\n"
        "Consider which sections require web search.\n"
        "For example, introduction and conclusion will not require research because they will "
        "distill information from other parts of the report.\n"
        "{language_instruction}",
    ),
    (
        "human",
        "Generate the sections of the report. Your response must include a 'sections' field "
        "containing a list of sections. Each section must have: name, description, plan, research, and content fields.",
    ),
])

# Section builder: generate search queries for a single section
REPORT_SECTION_QUERY_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Your goal is to generate targeted web search queries that will gather comprehensive "
        "information for writing a technical report section.\n\n"
        "Topic for this section:\n{section_topic}\n\n"
        "When generating {number_of_queries} search queries, ensure that they:\n"
        "1. Cover different aspects of the topic (e.g., core features, real-world applications, technical architecture)\n"
        "2. Include specific technical terms related to the topic\n"
        "3. Target recent information by including year markers where relevant (e.g., \"2026\")\n"
        "4. Look for comparisons or differentiators from similar technologies/approaches\n"
        "5. Search for both official documentation and practical implementation examples\n\n"
        "Your queries should be:\n"
        "- Specific enough to avoid generic results\n"
        "- Technical enough to capture detailed implementation information\n"
        "- Diverse enough to cover all aspects of the section plan\n"
        "- Focused on authoritative sources (documentation, technical blogs, academic papers)",
    ),
    ("human", "Generate search queries on the provided topic."),
])

# Section writer (research-backed sections)
SECTION_WRITER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical writer crafting one specific section of a technical report.\n\n"
        "Title for the section:\n{section_title}\n\n"
        "Topic for this section:\n{section_topic}\n\n"
        "Guidelines for writing:\n\n"
        "1. Technical Accuracy:\n"
        "- Include specific version numbers\n"
        "- Reference concrete metrics/benchmarks\n"
        "- Cite official documentation\n"
        "- Use technical terminology precisely\n\n"
        "2. Length and Style:\n"
        "- Strict 150-200 word limit\n"
        "- No marketing language\n"
        "- Technical focus\n"
        "- Write in simple, clear language do not use complex words unnecessarily\n"
        "- Start with your most important insight in **bold**\n"
        "- Use short paragraphs (2-3 sentences max)\n\n"
        "3. Structure:\n"
        "- Use ## for section title (Markdown format)\n"
        "- Only use ONE structural element IF it helps clarify your point:\n"
        "  * Either a focused table comparing 2-3 key items (using Markdown table syntax)\n"
        "  * Or a short list (3-5 items) using proper Markdown list syntax\n"
        "- End with ### Sources listing ONLY the sources you actually quoted or paraphrased above\n"
        "  * Copy the title and URL exactly as they appear in the provided source material\n"
        "  * Format: `- [title from context] : [URL from context]`\n"
        "  * NEVER invent, guess, or fabricate titles or URLs\n"
        "  * If no source was directly used, do NOT include a Sources section at all\n\n"
        "3. Writing Approach:\n"
        "- Include at least one specific example or case study if available\n"
        "- Use concrete details over general statements\n"
        "- Make every word count\n"
        "- No preamble prior to creating the section content\n\n"
        "4. Use this source material obtained from web searches to help write the section:\n{context}\n\n"
        "5. Quality Checks:\n"
        "- Format should be Markdown\n"
        "- Exactly 150-200 words (excluding title and sources)\n"
        "- Starts with bold insight\n"
        "- No preamble prior to creating the section content\n"
        "- If there are special characters such as the dollar symbol, "
        "escape them properly e.g $25.5 should become \\$25.5\n"
        "{language_instruction}",
    ),
    ("human", "Generate a report section based on the provided sources."),
])

# Final section writer (introduction / conclusion — no web search)
FINAL_SECTION_WRITER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical writer crafting a section that synthesizes "
        "information from the rest of the report.\n\n"
        "Title for the section:\n{section_title}\n\n"
        "Topic for this section:\n{section_topic}\n\n"
        "Available report content of already completed sections:\n{context}\n\n"
        "1. Section-Specific Approach:\n\n"
        "For Introduction:\n"
        "- Use # for report title (Markdown format)\n"
        "- 50-100 word limit\n"
        "- Write in simple and clear language\n"
        "- Focus on the core motivation for the report in 1-2 paragraphs\n"
        "- Include NO structural elements (no lists or tables)\n"
        "- No sources section needed\n\n"
        "For Conclusion/Summary:\n"
        "- Use ## for section title (Markdown format)\n"
        "- 100-150 word limit\n"
        "- For comparative reports: include a focused comparison table\n"
        "- For non-comparative reports: only use ONE structural element if it helps distill the points\n"
        "- End with specific next steps or implications\n"
        "- No sources section needed\n\n"
        "3. Writing Approach:\n"
        "- Use concrete details over general statements\n"
        "- Make every word count\n\n"
        "4. Quality Checks:\n"
        "- For introduction: 50-100 word limit, # for report title, no structural elements\n"
        "- For conclusion: 100-150 word limit, ## for section title, max one structural element\n"
        "- Markdown format\n"
        "- Do not include word count or any preamble in your response\n"
        "- If there are special characters such as the dollar symbol, "
        "escape them properly e.g $40.5 should become \\$40.5\n"
        "{language_instruction}",
    ),
    ("human", "Craft a report section based on the provided sources."),
])

