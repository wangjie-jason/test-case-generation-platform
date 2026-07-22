"""飞书接入服务：URL 解析 → 目标 obj_token → 拉取 blocks → 转 Markdown。

覆盖三种链接形式：
    1. /wiki/{node_token}?...  — 知识库节点（先 resolve 到真正的对象）
    2. /docx/{document_id}     — 新版云文档（直接拉 blocks）
    3. /docs/{doc_token}       — 旧版云文档（走 doc/v2 raw_content，不支持表格结构化）

拉不到、类型不支持、鉴权失败均抛 FeishuImportError，路由层统一转成 HTTP 400。
本模块只做"读"，不缓存 token，因为 tenant_access_token 有 2 小时有效期，
低频调用（用户手动点导入）没必要做缓存。真正高频再引入。
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class FeishuImportError(Exception):
    """所有飞书导入相关的用户可见错误。"""


# ── 链接解析 ─────────────────────────────────────────────

@dataclass
class FeishuTarget:
    kind: str  # "wiki" | "docx" | "doc"
    token: str


_URL_PATTERNS = {
    "wiki": re.compile(r"/wiki/([A-Za-z0-9]+)"),
    "docx": re.compile(r"/docx/([A-Za-z0-9]+)"),
    "doc": re.compile(r"/docs?/([A-Za-z0-9]+)"),
}


def parse_feishu_url(url: str) -> FeishuTarget:
    """从飞书分享链接抽出类型和 token。"""
    if not url or "://" not in url:
        raise FeishuImportError("链接格式不正确，请粘贴完整的飞书文档 URL")
    parsed = urlparse(url.strip())
    host = parsed.hostname or ""
    if "feishu" not in host and "larksuite" not in host:
        raise FeishuImportError("仅支持飞书 / Lark 域名下的文档链接")
    for kind, pat in _URL_PATTERNS.items():
        m = pat.search(parsed.path)
        if m:
            return FeishuTarget(kind=kind, token=m.group(1))
    raise FeishuImportError("无法识别链接类型，仅支持 /wiki/、/docx/、/docs/ 三种路径")


# ── HTTP 客户端 ─────────────────────────────────────────

class _FeishuClient:
    def __init__(self):
        if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
            raise FeishuImportError("后端未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
        self.base = settings.FEISHU_OPEN_API_BASE.rstrip("/")
        self._token: str | None = None

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        r = await client.post(
            f"{self.base}/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.FEISHU_APP_ID, "app_secret": settings.FEISHU_APP_SECRET},
        )
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            raise FeishuImportError(f"获取飞书 access_token 失败：{data.get('msg', r.text)}")
        self._token = data["tenant_access_token"]
        return self._token

    async def get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._get_token(client)
            r = await client.get(
                f"{self.base}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
            data = r.json()
            if r.status_code != 200 or data.get("code") != 0:
                # 常见错误码：99991663=应用无权限；1254002=文档不存在；1254003=无权访问。
                msg = data.get("msg") or r.text
                if data.get("code") in (99991663, 1254003, 91404):
                    raise FeishuImportError(f"飞书应用没有该文档的访问权限（{msg}），请让文档所有者把应用加为可查看成员")
                raise FeishuImportError(f"调用飞书接口失败：{msg}")
            return data.get("data", {})


# ── Wiki 节点 → 具体对象 ─────────────────────────────────

async def resolve_wiki_node(client: _FeishuClient, node_token: str) -> tuple[str, str, str]:
    """Wiki 节点是"壳"，真正的内容承载在挂载对象上。返回 (obj_type, obj_token, title)。"""
    data = await client.get("/wiki/v2/spaces/get_node", params={"token": node_token})
    node = data.get("node") or {}
    obj_type = node.get("obj_type")
    obj_token = node.get("obj_token")
    title = node.get("title") or "未命名"
    if not obj_type or not obj_token:
        raise FeishuImportError("Wiki 节点解析失败，未拿到 obj_type / obj_token")
    return obj_type, obj_token, title


# ── Docx blocks 抓取 & 转 Markdown ───────────────────────

async def fetch_docx_document(client: _FeishuClient, document_id: str) -> tuple[str, list[dict]]:
    """拉一份 docx 的标题与所有 block（自动分页）。"""
    meta = await client.get(f"/docx/v1/documents/{document_id}")
    title = (meta.get("document") or {}).get("title") or "未命名"

    blocks: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        data = await client.get(f"/docx/v1/documents/{document_id}/blocks", params=params)
        blocks.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return title, blocks


def blocks_to_markdown(blocks: list[dict]) -> str:
    """把飞书 Docx block 树拼成 Markdown。

    支持：标题(3~11)、段落(2)、无序列表(12)、有序列表(13)、代码块(14)、引用(15)、待办(17)、
    分割线(22)、表格(31)+表格单元格(32)、图片(27，占位符不下载)。表格转成 GFM，合并单元格用文本兜底。
    未识别的 block_type 记 debug 日志后跳过，防止一处不认识就整篇报错。
    """
    by_id = {b["block_id"]: b for b in blocks}
    children_of: dict[str, list[dict]] = defaultdict(list)
    root: dict | None = None
    for b in blocks:
        parent = b.get("parent_id")
        if parent:
            children_of[parent].append(b)
        # block_type == 1 是文档根节点
        if b.get("block_type") == 1:
            root = b

    def render_text_elements(elements: list[dict]) -> str:
        out = []
        for el in elements or []:
            run = el.get("text_run")
            if run:
                out.append(run.get("content", ""))
        return "".join(out)

    def render_block_content(b: dict) -> str:
        for key in ("text", "heading1", "heading2", "heading3", "heading4", "heading5",
                    "heading6", "heading7", "heading8", "heading9",
                    "bullet", "ordered", "code", "quote", "todo"):
            payload = b.get(key)
            if payload and isinstance(payload, dict) and "elements" in payload:
                return render_text_elements(payload["elements"])
        return ""

    def cell_to_text(cell_block: dict) -> str:
        parts: list[str] = []
        for child in children_of.get(cell_block["block_id"], []):
            parts.append(render_recursive(child).strip())
        text = " ".join(p for p in parts if p)
        # GFM 表格里 | 会破坏结构，换行会折行——统一转义。
        return text.replace("|", "\\|").replace("\n", " ")

    def render_recursive(b: dict) -> str:
        t = b.get("block_type")
        if t == 1:
            return "\n\n".join(render_recursive(c) for c in children_of.get(b["block_id"], []))
        if t == 2:
            return render_block_content(b)
        if t in range(3, 12):
            level = t - 2
            return "#" * level + " " + render_block_content(b)
        if t == 12:
            return "- " + render_block_content(b)
        if t == 13:
            return "1. " + render_block_content(b)
        if t == 14:
            return "```\n" + render_block_content(b) + "\n```"
        if t == 15:
            return "> " + render_block_content(b)
        if t == 17:
            done = (b.get("todo") or {}).get("style", {}).get("done")
            return ("- [x] " if done else "- [ ] ") + render_block_content(b)
        if t == 22:
            return "---"
        if t == 31:
            table = b.get("table") or {}
            prop = table.get("property") or {}
            rows = prop.get("row_size") or 0
            cols = prop.get("column_size") or 0
            cell_ids: list[str] = table.get("cells") or []
            if not rows or not cols or len(cell_ids) < rows * cols:
                return ""
            grid: list[list[str]] = []
            for r in range(rows):
                row_texts = []
                for c in range(cols):
                    cid = cell_ids[r * cols + c]
                    cell = by_id.get(cid)
                    row_texts.append(cell_to_text(cell) if cell else "")
                grid.append(row_texts)
            return _grid_to_gfm(grid)
        if t == 32:
            # 表格单元格：正常情况下由父表格控制渲染，兜底返回空避免"孤儿"复制内容。
            return ""
        if t == 27:
            # 图片：不下载、不做多模态识别；若有 caption 则展示，否则用统一占位符。
            # 这样 raw_text 里能看出这里有一张图，RAG 检索时又不至于被大段无意义内容干扰。
            img = b.get("image") or {}
            caption_elements = img.get("image_caption") or img.get("caption") or []
            caption_text = render_text_elements(caption_elements).strip()
            return f"[图片：{caption_text}]" if caption_text else "[图片]"
        logger.debug("未识别的飞书 block_type=%s，跳过自身内容仅递归子块", t)
        return "\n\n".join(render_recursive(c) for c in children_of.get(b["block_id"], []))

    if not root:
        candidates = [b for b in blocks if not b.get("parent_id")]
        if not candidates:
            return ""
        return "\n\n".join(render_recursive(b) for b in candidates)
    return render_recursive(root)


def _grid_to_gfm(grid: list[list[str]]) -> str:
    if not grid or not grid[0]:
        return ""
    header = grid[0]
    sep = ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ── 旧版 /docs/ 兜底（无表格结构化） ─────────────────────

async def fetch_legacy_doc(client: _FeishuClient, doc_token: str) -> tuple[str, str]:
    """旧版 Doc：只能拿纯文本，表格会被拍平。"""
    data = await client.get(f"/doc/v2/{doc_token}/raw_content")
    title = data.get("title") or "未命名"
    content = data.get("content") or ""
    return title, content


# ── 顶层调度 ────────────────────────────────────────────

@dataclass
class FeishuImportResult:
    title: str
    file_format: str
    content: str
    obj_token: str
    image_tokens: list[str]  # docx block_type=27 里的 image.token 列表，用于未来多模态回填


def collect_image_tokens(blocks: list[dict]) -> list[str]:
    """扫一遍 blocks，按文档顺序抽出所有图片 token。同一图片可能出现多次，去重保留首次顺序。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for b in blocks:
        if b.get("block_type") != 27:
            continue
        token = (b.get("image") or {}).get("token")
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


async def import_from_url(url: str) -> FeishuImportResult:
    """给定飞书 URL，返回可直接落库的四元组（含用于去重的 obj_token）。"""
    target = parse_feishu_url(url)
    client = _FeishuClient()

    if target.kind == "wiki":
        obj_type, obj_token, wiki_title = await resolve_wiki_node(client, target.token)
        if obj_type == "docx":
            title, blocks = await fetch_docx_document(client, obj_token)
            return FeishuImportResult(
                title=title or wiki_title, file_format="md",
                content=blocks_to_markdown(blocks), obj_token=obj_token,
                image_tokens=collect_image_tokens(blocks),
            )
        if obj_type == "doc":
            title, content = await fetch_legacy_doc(client, obj_token)
            return FeishuImportResult(
                title=title or wiki_title, file_format="txt", content=content, obj_token=obj_token,
                image_tokens=[],
            )
        raise FeishuImportError(
            f"该 Wiki 节点承载的是「{obj_type}」类型，当前仅支持 docx / 旧版 doc。"
            "若为电子表格或多维表格，请转成 docx 后再导入。"
        )

    if target.kind == "docx":
        title, blocks = await fetch_docx_document(client, target.token)
        return FeishuImportResult(
            title=title, file_format="md", content=blocks_to_markdown(blocks), obj_token=target.token,
            image_tokens=collect_image_tokens(blocks),
        )

    if target.kind == "doc":
        title, content = await fetch_legacy_doc(client, target.token)
        return FeishuImportResult(
            title=title, file_format="txt", content=content, obj_token=target.token,
            image_tokens=[],
        )

    raise FeishuImportError(f"不支持的链接类型：{target.kind}")
