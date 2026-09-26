"""Optional HTTP façade over the mock mailbox (extra `server`), for demos and manual testing.

The arena itself calls the mailbox in-process; this server exposes the same tools as REST
routes so other agent frameworks can be pointed at a realistic, resettable email backend.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llm_arena.mocks.email import Mailbox


class NewEmail(BaseModel):
    to: list[str]
    subject: str
    body: str


def create_app() -> FastAPI:
    app = FastAPI(title="Arena mock mailbox")
    state = {"box": Mailbox.seeded()}

    def tools() -> dict[str, Any]:
        return {t.name: t.fn for t in state["box"].tools()}

    def call(name: str, **kwargs: Any) -> Any:
        try:
            return tools()[name](**kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/emails")
    def list_emails(folder: str = "inbox", unread_only: bool = False) -> Any:
        return call("list_emails", folder=folder, unread_only=unread_only)

    @app.get("/emails/search")
    def search(q: str = "", sender: str | None = None) -> Any:
        return call("search_emails", query=q, sender=sender)

    @app.get("/emails/{email_id}")
    def read(email_id: int) -> Any:
        return call("read_email", email_id=email_id)

    @app.patch("/emails/{email_id}/read")
    def mark(email_id: int, read: bool = True) -> Any:
        return call("mark_read", email_id=email_id, read=read)

    @app.post("/emails/{email_id}/archive")
    def archive(email_id: int) -> Any:
        return call("archive_email", email_id=email_id)

    @app.post("/send")
    def send(email: NewEmail) -> Any:
        return call("send_email", to=email.to, subject=email.subject, body=email.body)

    @app.delete("/emails/{email_id}")
    def delete(email_id: int) -> Any:
        return call("delete_email", email_id=email_id)

    @app.post("/reset")
    def reset() -> dict[str, str]:
        state["box"] = Mailbox.seeded()
        return {"status": "reset"}

    return app
