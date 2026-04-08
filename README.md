# DeepResearch AI

### Visit this link for better understanding [View](https://deepresearch-ai-a8ufkgv.gamma.site/)

A sophisticated AI-powered research report generation system built with LangGraph, leveraging a multi-agent architecture for automated research planning, web search, and structured report generation.

![Agent Workflow](langgraph.png)

## 🚀 Overview

DeepResearch AI automates the entire research process by implementing a complex agent workflow that handles everything from initial topic analysis to final report compilation. The system uses LangGraph for agent orchestration and integrates with OpenAI's GPT-4 for content generation and Tavily for web research.

## 🏗️ Agent Architecture

### 1. Report Planning Agent
The planning phase is handled by the `generate_report_plan` agent, which:
- Analyzes the user's topic using GPT-4
- Generates initial search queries for topic research
- Creates a structured report outline
- Defines which sections require web research

```python
async def generate_report_plan(state: ReportState):
    """Generate the overall plan for building the report"""
    # Generates search queries and section structure
    # Returns a list of Section objects with research requirements
```

### 2. Section Builder Agent
The section builder implements a parallel execution strategy with three main components:

#### a. Query Generation
```python
def generate_queries(state: SectionState):
    """Generate targeted search queries for each section"""
    # Creates specific search queries based on section topic
    # Returns a list of SearchQuery objects
```

#### b. Web Research
```python
async def search_web(state: SectionState):
    """Execute web searches and format results"""
    # Performs parallel web searches using Tavily API
    # Deduplicates and formats search results
```

#### c. Content Writing
```python
def write_section(state: SectionState):
    """Generate section content from research"""
    # Uses GPT-4 to write section content
    # Integrates web research results
```

### 3. Final Compilation Agent
Handles the final stages of report generation:
- Formats completed sections
- Generates introduction and conclusion
- Compiles the final report in markdown format

## 🔄 Workflow Process

1. **Topic Analysis & Planning**
   - Topic decomposition
   - Section structure planning
   - Research requirement identification

2. **Parallel Research & Writing**
   - Concurrent web searches
   - Section-specific content generation
   - Source integration and citation

3. **Report Assembly**
   - Content formatting
   - Section organization
   - Final compilation

## 🛠️ Technical Implementation

### Core Components

1. **LangGraph Integration**
   - Uses StateGraph for agent orchestration
   - Implements typed state management
   - Handles parallel execution flows

2. **Web Research System**
   ```python
   async def run_search_queries(
       search_queries: List[Union[str, SearchQuery]],
       num_results: int = 4,
       include_raw_content: bool = False
   ) -> List[Dict]
   ```
   - Asynchronous query execution
   - Result deduplication
   - Content formatting

3. **Content Generation**
   - GPT-4 integration for writing
   - Structured prompting system
   - Source-based content synthesis

### Data Models

1. **Section Model**
   ```python
   class Section(BaseModel):
       name: str         # Section name
       description: str  # Section overview
       research: bool    # Research flag
       content: str      # Section content
   ```

2. **Search Models**
   ```python
   class SearchQuery(BaseModel):
       search_query: str
   ```

## 🔌 Integration Points

1. **OpenAI Integration**
   - GPT-4 for content generation
   - Structured output parsing
   - Temperature control for consistency

2. **Tavily Search Integration**
   - Parallel search execution
   - Result filtering and ranking
   - Content extraction

3. **Streamlit Interface**
   - User input handling
   - Progress tracking
   - Report display and export

## 📊 Report Structure

The system generates reports following a consistent structure:

1. **Introduction**
   - Topic overview
   - Research scope
   - Generated without web research

2. **Main Body Sections**
   - Research-based content
   - Source integration
   - Real-world examples

3. **Conclusion**
   - Key findings summary
   - Structured insights
   - Future implications

## 🔍 Research Methodology

The system employs a sophisticated research methodology:

1. **Query Generation**
   - Topic-specific search terms
   - Technical term inclusion
   - Recent information targeting

2. **Source Processing**
   - Content deduplication
   - Relevance ranking
   - Token-based truncation

3. **Content Synthesis**
   - Source integration
   - Fact verification
   - Structured formatting

## 📈 Performance Considerations

- Parallel execution of web searches
- Asynchronous content generation
- Token optimization for GPT-4
- Result caching and deduplication

## 🔐 Security & API Management

- Secure API key storage
- Rate limiting implementation
- Error handling and recovery

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- OpenAI API key
- Tavily API key
- Supabase account

### Environment Variables

```bash
OPENAI_API_KEY=your_openai_api_key
TAVILY_API_KEY=your_tavily_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

### Installation

```bash
git clone https://github.com/yourusername/deepresearch.git
cd deepresearch
pip install -r requirements.txt
```

### Running the Application

```bash
streamlit run app.py
```

## 📝 Dependencies

- LangGraph: Agent orchestration
- Streamlit: Web interface
- OpenAI: Language model
- Tavily: Web search
- Supabase: Authentication and storage
- ReportLab: PDF generation

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
