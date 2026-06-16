"""SmartRemote — a dumb, deterministic job dispatcher for a single-GPU server.

Jobs arrive as Markdown files (YAML frontmatter = routing contract, body =
instructions). The dispatcher ingests them, serializes GPU work behind a lock,
runs each job in its own workspace, and bridges human-in-the-loop questions to a
Hermes Agent messaging gateway (WhatsApp/email) so a job can park instead of block.

The orchestrator contains NO model calls — intelligence lives inside runners.
"""

__version__ = "0.1.0"
