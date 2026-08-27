from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_clients"

    client_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class McpOAuthAuthorization(Base):
    __tablename__ = "mcp_oauth_authorizations"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("mcp_oauth_clients.client_id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(default=True)
    state: Mapped[str | None] = mapped_column(Text)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(160), nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    denied_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class McpOAuthGrant(Base):
    __tablename__ = "mcp_oauth_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("mcp_oauth_clients.client_id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    rotation_counter: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class McpOAuthRefreshReplay(Base):
    __tablename__ = "mcp_oauth_refresh_replays"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("mcp_oauth_grants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
