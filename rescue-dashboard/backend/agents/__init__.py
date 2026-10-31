"""AI agents for the Rescue Control Room (LangChain + LangGraph).

Every agent only SUGGESTS. A human officer approves every action, every AI output is
labelled "AI suggestion (<provider>)", and if the AI is missing or fails the system
falls back to the rule-based logic that already exists, so rescue never stops.
"""
