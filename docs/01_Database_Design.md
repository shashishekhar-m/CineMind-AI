1. Introduction
2. Database Goals
3. Technology Stack
4. Entity List
5. Table Definitions
6. Relationships
7. Constraints
8. Indexes
9. Future Expansion
10. Naming Convention
<section>
    Introduction
    Purpose

    The CineMind database stores movie information,
    user information,
    recommendation metadata,
    search history,
    and analytics.

    The database is normalized to Third Normal Form (3NF)
    to minimize redundancy while maintaining fast query performance.
</section>

<section>
Technology
Database

PostgreSQL 17

ORM

SQLAlchemy

Migration

Alembic

Language

Python

Encoding

UTF-8

Timezone

UTC
</section>
<section>
Naming Convention

We NEVER use inconsistent names.

Example

Good

movie_id

release_year

runtime_minutes

Bad

movieID

MovieId

Runtime

Run_Time

Everything

snake_case.
</section>
<section>
Section 4
Primary Keys

Every table gets

BIGSERIAL

instead of

SERIAL

Why?

Because IMDb has millions of records.
</section>
<section>
Section 5
Foreign Keys

Every bridge table

movie_genres

movie_people

movie_keywords

movie_languages

will use composite unique constraints so the same relationship cannot be inserted twice.
</section>
<section>
Section 6
Timestamps

Every important table gets

created_at

updated_at

using

TIMESTAMPTZ

instead of

TIMESTAMP

because timezone-aware timestamps are better for production systems.
</section>
<section>
Movies Table

This table deserves its own chapter.

For every column we'll define

Example

movie_id

Type

BIGSERIAL

Nullable

No

Primary Key

Yes

Reason

Internal identifier.

We'll do this for every column.
</section>
<section>
Constraints

Example

IMDb ID

UNIQUE

Movie title

NOT NULL

Adult

DEFAULT FALSE

Popularity

DEFAULT 0

Vote count

CHECK >=0
</section>
<section>
Index Strategy

We'll explain

Why title gets index

Why imdb_id gets UNIQUE

Why release_year gets index

Why popularity gets index

Why movie_id gets clustered
</section>
<section>
Normalization

We'll explain

First Normal Form

Second Normal Form

Third Normal Form
</section>