"""
FastAPI HTTP layer — a thin wrapper over jobsentinel.db and jobsentinel.agent.
No business logic lives here, and per the architecture rule in CLAUDE.md this
layer never calls Bedrock directly — only the agent core does.

Empty for now — this is where Layer 5 (API layer) lives.
"""
