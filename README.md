# CineMind AI

> A production-grade AI-powered movie recommendation platform built with Python, PostgreSQL, FastAPI, Next.js, and Vector Search.



## Overview

CineMind AI is a full-stack movie recommendation platform designed to demonstrate production-grade software engineering practices. It leverages IMDb and TMDb datasets to deliver intelligent recommendations using hybrid ranking, semantic embeddings, and modern search techniques.

The project is built with scalability in mind and is capable of processing millions of records using a memory-efficient streaming ETL pipeline.

## Key Features

* Production-grade streaming ETL pipeline
* IMDb + TMDb integration
* PostgreSQL with `pgvector` and `pg_trgm`
* Semantic movie search
* Hybrid recommendation engine
* Materialized views
* FastAPI backend
* Next.js frontend
* Dockerized deployment
* Structured logging and monitoring
* Type-safe Python code
* CI/CD ready architecture

## Architecture

```text
IMDb
  ↓
TMDb Enrichment
  ↓
ETL Pipeline
  ↓
PostgreSQL
  ↓
Materialized Views
  ↓
Embeddings
  ↓
Recommendation Engine
  ↓
FastAPI
  ↓
Next.js
  ↓
Docker
  ↓
Cloud Deployment
```

## Tech Stack

| Category         | Technologies        |
| ---------------- | ------------------- |
| Language         | Python 3.13         |
| Database         | PostgreSQL 17       |
| Backend          | FastAPI             |
| Frontend         | Next.js, TypeScript |
| Vector Search    | pgvector            |
| Search           | pg_trgm             |
| ORM              | SQLAlchemy          |
| Migrations       | Alembic             |
| Caching          | Redis               |
| Containerization | Docker              |
| Testing          | pytest              |
| CI/CD            | GitHub Actions      |

## Repository Structure

```text
CineMind-AI/
│
├── backend/
├── database/
├── docker/
├── docs/
├── embeddings/
├── etl/
├── frontend/
├── recommendation/
├── requirements/
├── scripts/
├── tests/
└── README.md
```

## ETL Pipeline

The ETL layer follows a streaming architecture to ensure low memory consumption and high throughput.

```text
Extract
↓
Validate
↓
Transform
↓
Load
↓
TMDb Enrichment
↓
Refresh Views
↓
Generate Embeddings
```

### Supported IMDb Datasets

* `title.basics`
* `title.ratings`
* `name.basics`
* `title.principals`
* `title.crew`
* `title.akas`
* `title.episode`

## Recommendation Strategy

CineMind AI uses a hybrid recommendation approach:

| Component           | Weight |
| ------------------- | ------ |
| Semantic Embeddings | 40%    |
| TF-IDF Similarity   | 30%    |
| Genre Similarity    | 20%    |
| Popularity Score    | 10%    |

## Performance Goals

| Metric                 | Target         |
| ---------------------- | -------------- |
| RAM Usage              | < 2 GB         |
| ETL Throughput         | > 50k rows/sec |
| API Latency            | < 200 ms       |
| Search Latency         | < 100 ms       |
| Recommendation Latency | < 300 ms       |
| Supported Titles       | 10M+           |

## Development Roadmap

* [x] Project Architecture
* [x] Database Design
* [x] Streaming ETL Foundation
* [x] PostgreSQL Loader
* [ ] TMDb Enrichment
* [ ] Embedding Generation
* [ ] Recommendation Engine
* [ ] FastAPI Backend
* [ ] Next.js Frontend
* [ ] Docker Deployment
* [ ] CI/CD Pipeline

## Getting Started

### Clone the Repository

```bash
git clone https://github.com/shashishekhar-m/CineMind-AI.git
cd CineMind-AI
```

### Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements/base.txt
```

### Configure Environment

```bash
cp etl/.env.example .env
```

### Run the ETL Pipeline

```bash
python etl/pipeline.py
```

## Engineering Principles

* SOLID
* DRY
* KISS
* YAGNI
* Single Responsibility Principle

## Documentation

Additional documentation can be found in the `docs/` directory:

* The Constitution of CineMind AI
* AI Engineering Guide
* Master Prompt
* Database Design
* ETL Architecture
* API Architecture

## Why This Project?

CineMind AI was built to showcase:

* Production ETL pipelines
* Large-scale data processing
* PostgreSQL optimization
* Vector search
* Recommendation systems
* Backend architecture
* Full-stack development
* Docker and deployment workflows

## Future Enhancements

* Personalized recommendations
* User authentication
* Watchlists
* Analytics dashboard
* Multilingual search
* Voice search
* Mobile application
* Social features
* LLM-powered movie assistant


## Author

**Shashi Shekhar Mahato**


---

> "Build systems that scale, not demos that break."
