from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _password_bytes_len(v: str) -> str:
    # bcrypt 只认前 72 字节（中文每字 3 字节），直接按字节限制，避免超长被静默截断。
    if len(v.encode("utf-8")) > 72:
        raise ValueError("密码过长（最多 72 字节，约 24 个汉字）")
    return v


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_bytes(cls, v: str) -> str:
        return _password_bytes_len(v)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str | None = None
    is_admin: bool
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("password")
    @classmethod
    def _check_bytes(cls, v: str) -> str:
        return _password_bytes_len(v)


class AdminUpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    is_admin: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_bytes(cls, v: str) -> str:
        return _password_bytes_len(v)
