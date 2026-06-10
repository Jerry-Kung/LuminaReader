from typing import Literal

from pydantic import BaseModel, Field, model_validator

from lumina.config import get_settings


class SelectionSegment(BaseModel):
    page: int = Field(ge=1)
    text: str
    offset_start: int = Field(ge=0)
    offset_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_offsets(self) -> "SelectionSegment":
        if self.offset_end < self.offset_start:
            raise ValueError("offset_end must be >= offset_start")
        return self


class Selection(BaseModel):
    type: Literal["text", "image"] = "image"
    pdf_id: str | None = None
    page: int = Field(ge=1)
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    dpi: float | None = None
    text: str | None = None
    page_end: int | None = Field(default=None, ge=1)
    segments: list[SelectionSegment] | None = None

    @model_validator(mode="after")
    def _check_discriminator(self) -> "Selection":
        if self.type == "image":
            for name, val in [
                ("x", self.x),
                ("y", self.y),
                ("w", self.w),
                ("h", self.h),
                ("dpi", self.dpi),
            ]:
                if val is None:
                    raise ValueError(f"selection.{name} is required when type='image'")
                if name in {"w", "h", "dpi"} and val <= 0:
                    raise ValueError(f"selection.{name} must be > 0")
            for name, val in [
                ("text", self.text),
                ("page_end", self.page_end),
                ("segments", self.segments),
            ]:
                if val is not None:
                    raise ValueError(f"selection.{name} must be None when type='image'")
        else:
            if not self.text:
                raise ValueError("selection.text is required and non-empty when type='text'")
            max_chars = get_settings().selection_text_max_chars
            if len(self.text) > max_chars:
                raise ValueError(
                    f"selection.text exceeds LUMINA_SELECTION_TEXT_MAX_CHARS "
                    f"({len(self.text)} > {max_chars})"
                )
            if self.page_end is None:
                raise ValueError("selection.page_end is required when type='text'")
            if self.page_end < self.page:
                raise ValueError("selection.page_end must be >= page")
            if not self.segments:
                raise ValueError("selection.segments must be non-empty when type='text'")
            for name, val in [
                ("x", self.x),
                ("y", self.y),
                ("w", self.w),
                ("h", self.h),
                ("dpi", self.dpi),
            ]:
                if val is not None:
                    raise ValueError(f"selection.{name} must be None when type='text'")
        return self


class ImagePayload(BaseModel):
    mime: str
    data: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
