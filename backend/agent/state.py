from typing import Annotated, TypedDict, List, Optional, Any
from langgraph.graph.message import add_messages

class SuggestionItem(TypedDict, total=False):
    """A single suggestion item."""
    name: str
    category: str  # "spell", "aa", "zone", "gear"
    priority: int  # 1-5, 1=must-have
    reason: str
    synergies: List[str]
    source: str


class ProfileData(TypedDict):
    """User profile information."""
    id: int
    race: str
    primary_class: str
    secondary_class: str
    tertiary_class: Optional[str]
    level: int
    playstyle: str


class AgentState(TypedDict):
    """LangGraph agent state."""
    # Profile
    profile: ProfileData

    # Conversation
    messages: Annotated[List[dict], add_messages]  # LangGraph message list

    # Context
    current_zone: Optional[str]  # From logs
    recent_activity: Optional[str]  # From logs

    # Suggestions
    spell_suggestions: List[SuggestionItem]
    aa_suggestions: List[SuggestionItem]
    zone_suggestions: List[SuggestionItem]
    gear_suggestions: List[SuggestionItem]

    # Metadata
    reasoning: Optional[str]
    sources_cited: List[str]
    error: Optional[str]
