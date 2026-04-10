from tavily import AsyncTavilyClient
import asyncio
import tiktoken
from typing import Dict, Any, List, Union


async def run_search_queries(
    search_queries: List[str],
    api_key: str,
    num_results: int = 4,
    include_raw_content: bool = False
) -> List[Dict]:
    """각 쿼리로 웹을 병렬 검색하고 결과 목록을 반환한다."""

    if not api_key:
        print("Warning: Tavily API key not provided")
        return []

    client = AsyncTavilyClient(api_key=api_key)

    search_tasks = [
        client.search(
            query=str(query),
            max_results=num_results,
            search_depth="advanced",
            include_answer=False,
            include_raw_content=include_raw_content,
        )
        for query in search_queries
    ]

    if not search_tasks:
        return []

    try:
        search_docs = await asyncio.gather(*search_tasks, return_exceptions=True)
        return [doc for doc in search_docs if not isinstance(doc, Exception)]
    except Exception as e:
        print(f"Error during search queries: {e}")
        return []


def format_search_query_results(
    search_response: Union[Dict[str, Any], List[Any]],
    max_tokens: int = 2500,
    include_raw_content: bool = False
) -> str:
    encoding = tiktoken.encoding_for_model("gpt-4o")
    sources_list = []

    # Handle different response formats
    if isinstance(search_response, dict):
        if "results" in search_response:
            sources_list.extend(search_response["results"])
        else:
            sources_list.append(search_response)
    elif isinstance(search_response, list):
        for response in search_response:
            if isinstance(response, dict):
                if "results" in response:
                    sources_list.extend(response["results"])
                else:
                    sources_list.append(response)
            elif isinstance(response, list):
                sources_list.extend(response)

    if not sources_list:
        return "No search results found."

    # Deduplicate by URL
    unique_sources = {}
    for source in sources_list:
        if isinstance(source, dict) and "url" in source:
            if source["url"] not in unique_sources:
                unique_sources[source["url"]] = source

    formatted_text = "Content from web search:\n\n"
    for source in unique_sources.values():
        formatted_text += f"Source {source.get('title', 'Untitled')}:\n===\n"
        formatted_text += f"URL: {source['url']}\n===\n"
        formatted_text += f"Most relevant content from source: {source.get('content', 'No content available')}\n===\n"

        if include_raw_content:
            raw_content = source.get("raw_content", "")
            if raw_content:
                tokens = encoding.encode(raw_content, disallowed_special=())
                truncated_content = encoding.decode(tokens[:max_tokens])
                formatted_text += f"Raw Content: {truncated_content}\n\n"

    return formatted_text.strip()
