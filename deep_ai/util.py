from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
import asyncio
from dataclasses import asdict, dataclass
from typing import Dict, Any, List, Union
# from dotenv import load_dotenv
import os

# load_dotenv()

# TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# os.environ['TAVILY_API_KEY'] = TAVILY_API_KEY

# just to handle objects created from LLM reponses
@dataclass
class SearchQuery:
    search_query: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Create a function to get tavily client on demand
def get_tavily_search():
    import os
    api_key = os.environ.get("TAVILY_API_KEY")
    try:
        if api_key:
            return TavilySearchAPIWrapper(tavily_api_key=api_key)
        return TavilySearchAPIWrapper()
    except Exception as e:
        print(f"Error initializing Tavily API: {e}")
        raise RuntimeError("Tavily API key not found or invalid.")


async def run_search_queries(
    search_queries: List[Union[str, SearchQuery]],
    num_results: int = 4,
    include_raw_content: bool = False
) -> List[Dict]:

    search_tasks = []
    
    # Get tavily client on demand
    try:
        tavily_search = get_tavily_search()
    except Exception as e:
        print(f"Error initializing Tavily API: {e}")
        return []

    for query in search_queries:
        # Handle both string and SearchQuery objects
        # Just in case LLM fails to generate queries as:
        # class SearchQuery(BaseModel):
        #     search_query: str
        query_str = query.search_query if isinstance(query, SearchQuery) else str(query) # text query

        try:
            # get results from tavily asynchronously (in parallel) for each search query
            search_tasks.append(
                tavily_search.raw_results_async(
                    query=query_str,
                    max_results=num_results,
                    search_depth='advanced',
                    include_answer=False,
                    include_raw_content=include_raw_content
                )
            )
        except Exception as e:
            print(f"Error creating search task for query '{query_str}': {e}")
            continue

    # Execute all searches concurrently and await results
    try:
        if not search_tasks:
            return []
        search_docs = await asyncio.gather(*search_tasks, return_exceptions=True)
        # Filter out any exceptions from the results
        valid_results = [
            doc for doc in search_docs
            if not isinstance(doc, Exception)
        ]
        return valid_results
    except Exception as e:
        print(f"Error during search queries: {e}")
        return []
    
import tiktoken
from typing import List, Dict, Union, Any

def format_search_query_results(
    search_response: Union[Dict[str, Any], List[Any]],
    max_tokens: int = 2500,
    include_raw_content: bool = False
) -> str:
    encoding = tiktoken.encoding_for_model("gpt-4")
    sources_list = []

    # Handle different response formats
    # if search results is a dict
    if isinstance(search_response, dict):
        if 'results' in search_response:
            sources_list.extend(search_response['results'])
        else:
            sources_list.append(search_response)
    # if search results is a list
    elif isinstance(search_response, list):
        for response in search_response:
            if isinstance(response, dict):
                if 'results' in response:
                    sources_list.extend(response['results'])
                else:
                    sources_list.append(response)
            elif isinstance(response, list):
                sources_list.extend(response)

    if not sources_list:
        return "No search results found."

    # Deduplicate by URL and keep unique sources (website urls)
    unique_sources = {}
    for source in sources_list:
        if isinstance(source, dict) and 'url' in source:
            if source['url'] not in unique_sources:
                unique_sources[source['url']] = source

    # Format output
    formatted_text = "Content from web search:\n\n"
    for i, source in enumerate(unique_sources.values(), 1):
        formatted_text += f"Source {source.get('title', 'Untitled')}:\n===\n"
        formatted_text += f"URL: {source['url']}\n===\n"
        formatted_text += f"Most relevant content from source: {source.get('content', 'No content available')}\n===\n"

        if include_raw_content:
            # truncate raw webpage content to a certain number of tokens to prevent exceeding LLM max token window
            raw_content = source.get("raw_content", "")
            if raw_content:
                tokens = encoding.encode(raw_content, disallowed_special=())
                truncated_tokens = tokens[:max_tokens]
                truncated_content = encoding.decode(truncated_tokens)
                formatted_text += f"Raw Content: {truncated_content}\n\n"

    return formatted_text.strip()