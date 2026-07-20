"""Database models.

Tables are new-named (characters, chat_messages, log_events) — the old
Gradio-era `profiles`/`conversations` tables are abandoned in place and
harmless; delete data/companion.db to fully clean up.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    server = Column(String, nullable=True)
    level = Column(Integer, nullable=True)
    class_str = Column(String, nullable=True)   # e.g. "Monk/Paladin/Druid"
    race = Column(String, nullable=True)
    zone = Column(String, nullable=True)
    playstyle = Column(String, nullable=True)   # solo_dps, group_dps, tank, ...
    aa_available = Column(Integer, nullable=True)  # unspent AA points (user-set; +1 per gain)
    spell_slots = Column(Integer, nullable=True)   # spell slots unlocked via AAs (user-set)
    pet_slots = Column(Integer, nullable=True)     # pet equipment slots (user-set, varies by class)
    pet_classes = Column(String, nullable=True)    # pet's equip class(es), e.g. "Warrior" or "WAR/RNG"
    owned_aas = Column(JSON, nullable=True)        # /alternateadv list roster (survives restarts)
    aa_synced = Column(String, nullable=True)      # iso stamp of that listing
    pet_owners = Column(JSON, nullable=True)       # pet -> owner map from leader lines
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chat_messages = relationship("ChatMessageRow", back_populates="character",
                                 cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "server": self.server,
            "level": self.level, "class_str": self.class_str, "race": self.race,
            "zone": self.zone, "playstyle": self.playstyle,
            "aa_available": self.aa_available, "spell_slots": self.spell_slots,
            "pet_slots": self.pet_slots,
            "pet_classes": self.pet_classes,
        }


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    role = Column(String, nullable=False)      # "user" | "assistant"
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    character = relationship("Character", back_populates="chat_messages")

    def to_dict(self):
        return {"role": self.role, "content": self.content,
                "created_at": self.created_at.isoformat()}


class LogEventRow(Base):
    """Persisted notable events (zone/level/kill/death/aa/loot/skill) —
    per-hit combat spam stays in the in-memory ledger only."""
    __tablename__ = "log_events"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    ts = Column(DateTime, nullable=False, index=True)
