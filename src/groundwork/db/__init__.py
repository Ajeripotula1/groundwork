"""
Shared data-access module: schema, migrations, and queries used by the API,
agent, and poller. This is the *only* thing the three deployable units share —
per the architecture rule in CLAUDE.md, they don't call each other directly.

Empty for now — this is where Layer 1 (Data layer) lives.
"""
