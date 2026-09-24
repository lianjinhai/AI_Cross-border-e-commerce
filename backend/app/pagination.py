"""分页参数统一约束。

**为什么需要这个模块**（审计 #10 / DEBT-27）：

1. **无上限会拉全表**：`page_size` 原本无上界，调用方传 `page_size=10**9`
   会把整张表读进内存再序列化，是廉价 DoS 面。
2. **静默截断比报错更危险**：调用方拿 `page_size=500` 做「集合比对」时，
   若实际数据 501 条，返回的第一页看起来完全正常，**漏掉的那条不会被发现**。
   实测：测试库 `orders` 恰好 500 条，与硬编码的 `page_size=500` 相等——
   一旦 seed 增加订单数，跨租户隔离比对就会静默失效（假绿）。
3. **快速失败优于静默错误**：超出上限直接返回 422，让调用方立刻发现并改成分页遍历，
   而不是拿到一份「看起来对」的残缺数据。

上限取 200 的依据：覆盖全部前端用法（最大 200，见 `views/Refunds.vue`），
并与既有 `limit` 类参数的上限（`ai.py` / `listings.py` / `admin.py` 的 200）保持一致。

用法::

    from ..pagination import PageNum, PageSize

    @router.get("")
    def list_x(page_num: int = PageNum, page_size: int = PageSize, ...):
        ...
"""
from fastapi import Query

MAX_PAGE_SIZE = 200

PageNum = Query(1, ge=1, description="页码，从 1 开始")
PageSize = Query(20, ge=1, le=MAX_PAGE_SIZE,
                 description=f"每页条数，上限 {MAX_PAGE_SIZE}（超出返回 422，避免静默截断）")
