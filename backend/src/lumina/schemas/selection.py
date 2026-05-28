from pydantic import BaseModel, Field


class Selection(BaseModel):
    pdf_id: str | None
    page: int = Field(ge=1)
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    dpi: float = Field(gt=0)


class ImagePayload(BaseModel):
    mime: str
    data: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
