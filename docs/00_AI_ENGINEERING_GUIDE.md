AI ENGINEERING GUIDE FOR CINEMIND AI
Rule 1

Always analyze the entire GitHub repository before making architectural decisions.

Rule 2

Read documents in this order:

00_AI_ENGINEERING_GUIDE.md
↓
00_MASTER_PROMPT.md
↓
README.md
↓
docs/
↓
database/
↓
etl/
↓
backend/
↓
recommendation/
↓
frontend/
↓
tests/
Rule 3

Never rewrite architecture without explicit approval.

Rule 4

Assume existing code exists for a reason.

Before changing code:

Understand
↓
Analyze
↓
Explain
↓
Propose
↓
Implement
Rule 5

Always provide:

Current state
Problems
Proposed solution
Impact
Files affected

before modifying code.

Rule 6

Never introduce technologies not listed in the Constitution.

Forbidden:

Spark
Kafka
MongoDB
Celery
TensorFlow
Kubernetes

unless explicitly requested.

Rule 7

IMDb datasets are never committed to Git.

Allowed:

Python
SQL
Docker
Documentation
Tests

Forbidden:

TSV
GZIP
Embeddings
Logs
Caches
Rule 8

Before implementing anything:

Can this be reused?
Can this be simplified?
Does it follow SRP?
Does it scale?
Rule 9

All code must include:

Type hints
Structured logging
Exception handling
Docstrings
Rule 10

Performance targets:

RAM:
<2 GB

API:
<200 ms

Recommendations:
<300 ms

ETL:
50k rows/sec
Rule 11

Never load IMDb into memory.

Always:

Stream
Validate
Transform
Batch
Rule 12

AI assistants must never:

Rename folders.
Move files.
Delete code.
Change schema.
Change architecture.

without approval.

Rule 13

If uncertain:

STOP
↓
Explain uncertainty
↓
Provide options
↓
Wait

Never guess.

Rule 14

Development order:

Database
ETL
Embeddings
Recommendations
Backend
Frontend
Deployment
Monitoring
Rule 15

Every pull request should answer:

Why?
What?
Impact?
Risk?
Rollback?
Rule 16

Always preserve:

IMDb IDs
TMDb IDs
Database integrity
Normalization
Performance
Rule 17

Preferred engineering principles:

SOLID
DRY
KISS
YAGNI
SRP
Rule 18

Never optimize prematurely.

Priority:

Correctness
Maintainability
Scalability
Performance
Rule 19

Before writing code, analyze:

Existing classes
Existing interfaces
Existing utilities
Existing patterns

Reuse first.

Rule 20

CineMind AI is:

Portfolio Project
Interview Project
Production Project
Open Source Project
Potential Startup

Every decision must improve at least one of these.

Final Directive
Read:
1. AI Engineering Guide
2. Constitution of CineMind AI
3. GitHub Repository

Analyze before coding.

Think before changing.

Never violate the constitutions.

Prefer simplicity over complexity.

Produce production-grade software.