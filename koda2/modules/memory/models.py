"""Database models for the memory and user-profile system."""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import relationship

from koda2.database import Base


class UserProfile(Base):
    """Long-term user profile with preferences and context."""

    __tablename__ = "user_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(256), default="")
    email = Column(String(256), default="")
    phone = Column(String(64), default="")
    timezone = Column(String(64), default="UTC")
    language = Column(String(16), default="en")
    preferences = Column(SQLiteJSON, default=dict)
    habits = Column(SQLiteJSON, default=dict)
    important_dates = Column(SQLiteJSON, default=dict)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC))

    conversations = relationship("Conversation", back_populates="profile", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="profile", cascade="all, delete-orphan")


class Contact(Base):
    """Contact relationships linked to a user profile."""

    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id = Column(String(36), ForeignKey("user_profiles.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    email = Column(String(256), default="")
    phone = Column(String(64), default="")
    company = Column(String(256), default="")
    relationship_type = Column(String(64), default="")
    notes = Column(Text, default="")
    birthday = Column(String(16), default="")
    metadata_ = Column("metadata", SQLiteJSON, default=dict)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC))

    profile = relationship("UserProfile", back_populates="contacts")


class Conversation(Base):
    """Conversation history entries."""

    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id = Column(String(36), ForeignKey("user_profiles.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    channel = Column(String(64), default="api")
    tokens_used = Column(Integer, default=0)
    model = Column(String(128), default="")
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), index=True)

    profile = relationship("UserProfile", back_populates="conversations")


class MemoryEntry(Base):
    """Structured memory entries for searchable facts."""

    __tablename__ = "memory_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(128), nullable=False, index=True)
    category = Column(String(64), nullable=False, index=True)
    content = Column(Text, nullable=False)
    importance = Column(Float, default=0.5)
    source = Column(String(128), default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC))
