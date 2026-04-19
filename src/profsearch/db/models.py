"""SQLAlchemy ORM models for the ProfSearch pipeline."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class University(TimestampMixin, Base):
    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(128))
    qs_rank_2026: Mapped[int | None] = mapped_column(Integer)
    qs_score: Mapped[float | None] = mapped_column(Float)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    openalex_id: Mapped[str | None] = mapped_column(String(128))
    ror_id: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    department_sources: Mapped[list["DepartmentSource"]] = relationship(back_populates="university", cascade="all, delete-orphan")
    faculty_candidates: Mapped[list["FacultyCandidate"]] = relationship(back_populates="university")
    professors: Mapped[list["Professor"]] = relationship(back_populates="university")


class DepartmentSource(Base):
    __tablename__ = "department_sources"
    __table_args__ = (UniqueConstraint("university_id", "department_type", "roster_url", name="uq_department_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), nullable=False)
    department_type: Mapped[str] = mapped_column(String(64), nullable=False)
    roster_url: Mapped[str] = mapped_column(Text, nullable=False)
    parser_hint: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    university: Mapped["University"] = relationship(back_populates="department_sources")
    faculty_candidates: Mapped[list["FacultyCandidate"]] = relationship(back_populates="department_source")


class FacultyCandidate(TimestampMixin, Base):
    __tablename__ = "faculty_candidates"
    __table_args__ = (
        UniqueConstraint(
            "department_source_id",
            "normalized_name",
            "profile_url",
            name="uq_faculty_candidate_identity",
        ),
        Index("ix_candidate_uni", "university_id"),
        Index("ix_candidate_source_status", "department_source_id", "scrape_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), nullable=False)
    department_source_id: Mapped[int] = mapped_column(ForeignKey("department_sources.id"), nullable=False)
    department_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    profile_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_snippet: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    scrape_status: Mapped[str] = mapped_column(String(32), default="captured", nullable=False)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    university: Mapped["University"] = relationship(back_populates="faculty_candidates")
    department_source: Mapped["DepartmentSource"] = relationship(back_populates="faculty_candidates")
    professor: Mapped["Professor | None"] = relationship(back_populates="candidate", uselist=False)


class Professor(TimestampMixin, Base):
    __tablename__ = "professors"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_professor_candidate"),
        Index("ix_professor_verif_dedup", "verification_status", "duplicate_of_professor_id"),
        Index("ix_professor_uni_dept", "university_id", "department_type"),
        Index("ix_professor_norm_name", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("faculty_candidates.id"), nullable=False)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), nullable=False)
    department_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    title_normalized: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    profile_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_snippet: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    duplicate_of_professor_id: Mapped[int | None] = mapped_column(ForeignKey("professors.id"))
    duplicate_reason: Mapped[str | None] = mapped_column(String(64))
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    university: Mapped["University"] = relationship(back_populates="professors")
    candidate: Mapped["FacultyCandidate"] = relationship(back_populates="professor")
    author_match: Mapped["OpenAlexAuthorMatch | None"] = relationship(back_populates="professor", uselist=False)
    works: Mapped[list["ProfessorWork"]] = relationship(back_populates="professor")
    grants: Mapped[list["Grant"]] = relationship(back_populates="professor")
    duplicate_of: Mapped["Professor | None"] = relationship(remote_side="Professor.id")


class OpenAlexAuthorMatch(Base):
    __tablename__ = "openalex_author_matches"
    __table_args__ = (Index("ix_oam_status", "match_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("professors.id"), unique=True, nullable=False)
    openalex_author_id: Mapped[str | None] = mapped_column(String(128))
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    professor: Mapped["Professor"] = relationship(back_populates="author_match")


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (Index("ix_work_year", "publication_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    openalex_work_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[str | None] = mapped_column(String(32))
    doi: Mapped[str | None] = mapped_column(String(255))
    cited_by_count: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(64))
    topics_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    professors: Mapped[list["ProfessorWork"]] = relationship(back_populates="work")
    embedding: Mapped["WorkEmbedding | None"] = relationship(back_populates="work", uselist=False)


class ProfessorWork(Base):
    __tablename__ = "professor_works"
    __table_args__ = (Index("ix_profwork_work", "work_id"),)

    professor_id: Mapped[int] = mapped_column(ForeignKey("professors.id"), primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), primary_key=True)
    authorship_position: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    is_corresponding: Mapped[bool | None] = mapped_column(Boolean)

    professor: Mapped["Professor"] = relationship(back_populates="works")
    work: Mapped["Work"] = relationship(back_populates="professors")


class WorkEmbedding(Base):
    __tablename__ = "work_embedding_store"

    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), primary_key=True)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="hash")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    work: Mapped["Work"] = relationship(back_populates="embedding")


class Grant(TimestampMixin, Base):
    __tablename__ = "grants"
    __table_args__ = (
        UniqueConstraint("source", "grant_id", name="uq_grant_source_id"),
        Index("ix_grant_prof", "professor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("professors.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # "nih" or "nsf"
    grant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    pi_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[float | None] = mapped_column(Float)
    start_date: Mapped[str | None] = mapped_column(String(32))
    end_date: Mapped[str | None] = mapped_column(String(32))
    raw_json: Mapped[str | None] = mapped_column(Text)

    professor: Mapped["Professor"] = relationship(back_populates="grants")


class PipelineState(Base):
    __tablename__ = "pipeline_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_started", nullable=False)
    checkpoint_json: Mapped[str | None] = mapped_column(Text)
    total_items: Mapped[int | None] = mapped_column(Integer)
    processed_items: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
