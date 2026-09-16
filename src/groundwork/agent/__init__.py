"""
Strands-based agent core: fit scoring and interview-driven resume/cover-letter
tailoring. Runs locally via CLI (groundwork.agent.cli) before it ever
touches AgentCore Runtime.
"""
from .main import build_agent, build_tools

__all__ = ["build_agent", "build_tools"]