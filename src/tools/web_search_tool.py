import json
import subprocess
from typing import Any, Dict

from .base import BaseTool


class WebSearchTool(BaseTool):
    """Search the web using a simple HTTP request to DuckDuckGo."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. "
            "Returns a summary of search results. "
            "Use this when the user asks about current events, weather, news, "
            "or anything that requires up-to-date information."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                }
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> str:
        try:
            # Use curl to query DuckDuckGo instant answer API
            result = subprocess.run(
                [
                    "curl", "-s",
                    f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                return f"Search failed: {result.stderr}"

            data = json.loads(result.stdout)
            parts = []

            # Abstract (main answer)
            if data.get("Abstract"):
                parts.append(f"**{data.get('Heading', 'Result')}**\n{data['Abstract']}")
                if data.get("AbstractURL"):
                    parts.append(f"Source: {data['AbstractURL']}")

            # Answer (direct answer)
            if data.get("Answer"):
                parts.append(f"Answer: {data['Answer']}")

            # Related topics
            related = data.get("RelatedTopics", [])
            if related and not parts:
                for topic in related[:5]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        parts.append(f"- {topic['Text'][:200]}")

            if not parts:
                # Fallback: try a simple curl to a search engine
                return f"No instant answer found for '{query}'. Try rephrasing or ask me to run a more specific search."

            return "\n\n".join(parts)

        except json.JSONDecodeError:
            return "Search returned invalid data."
        except subprocess.TimeoutExpired:
            return "Search timed out."
        except Exception as e:
            return f"Search error: {e}"
