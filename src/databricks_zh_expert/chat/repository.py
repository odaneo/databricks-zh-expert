from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.db.models import ChatSession, Message


class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_session(self, title: str) -> ChatSession:
        session = ChatSession(title=title)
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, limit: int, offset: int) -> list[ChatSession]:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间。")
        if offset < 0:
            raise ValueError("offset 不能小于 0。")

        result = await self.db.scalars(
            select(ChatSession)
            .order_by(
                ChatSession.updated_at.desc(),
                ChatSession.created_at.desc(),
                ChatSession.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def get_session(self, session_id: UUID) -> ChatSession | None:
        result = await self.db.scalars(select(ChatSession).where(ChatSession.id == session_id))
        return result.one_or_none()

    async def list_messages(
        self,
        session_id: UUID,
        limit: int = 100,
    ) -> list[Message]:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间。")

        result = await self.db.scalars(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        return list(result.all())
