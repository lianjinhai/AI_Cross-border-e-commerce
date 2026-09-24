"""反向代理转发头处理（安全边界，集中一处）。

## 为什么需要这个模块

生产部署时应用位于 TLS 终止代理（Caddy / nginx / 云负载均衡）之后，
到达应用的连接来自代理容器，于是：

- ``request.client.host`` 是代理地址，不是真实客户端（审计日志失去意义）；
- ``request.url.scheme`` 恒为 ``http``，生成的回调地址会退化成内网 http。

处理方式是在 ASGI 层采信 ``X-Forwarded-For`` / ``X-Forwarded-Proto``。

## 为什么不用 starlette 的实现

``starlette.middleware.proxy_headers`` 在 starlette 1.x 中**已被移除**。
上一版曾直接 import 它，结果是：一旦开启开关，容器在 import 阶段
``ModuleNotFoundError`` 崩溃——比不修更糟（DEBT-23 实测发现）。

因此这里**复用 uvicorn 的实现**：它在依赖树内、版本受锁文件约束，
且是 uvicorn 自身处理 ``--proxy-headers`` 的同一份代码。

## 为什么不用 uvicorn 的 ``--proxy-headers`` 参数

容器入口是 ``docker-entrypoint.sh`` 转发的命令，加参数要同时改
Dockerfile / compose / 本地启动三处，容易漏改且漏改后**静默失效**。
中间件只依赖配置，一处生效。

## 安全前提（两道闸）

1. ``ERP_TRUST_PROXY_HEADERS=1`` 显式开启，默认关闭；
2. ``ERP_TRUSTED_PROXY_HOSTS`` 限定可信来源，默认 ``127.0.0.1``。

**只开第一道不够**：实测 ``FORWARDED_ALLOW_IPS=*``（等价于信任所有来源）时，
直连应用即可把客户端 IP 伪造成任意值。因此
``docker-compose.tls.yml`` 同时用 ``!reset`` 清空 8000 端口映射，
确保外部无法绕过代理直连。

Docker 部署下代理的源地址是容器网段（不是 127.0.0.1），故
``docker-compose.tls.yml`` 为两服务固定了专用网段并同步配置该变量。
"""
from . import config

__all__ = ["install_proxy_headers_middleware"]


def install_proxy_headers_middleware(app) -> bool:
    """按配置给 ASGI 应用装上转发头中间件。返回是否已启用。

    调用时机：在其它 ``add_middleware`` **之后**调用，使其成为最外层
    （Starlette 的中间件栈是「后加的在最外层」），与 uvicorn 自身
    ``--proxy-headers`` 的布局一致——信任边界应贴在最边缘。

    注意：实测表明调换顺序**结果相同**，因为该中间件是就地修改 ASGI
    ``scope``（内层拿到的都是同一份已修正的 scope）。顺序只影响可读性，
    不影响行为；此处仍按「最外层」组织，避免后来者误解为顺序敏感。
    """
    if not config.settings.trust_proxy_headers:
        return False

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app.add_middleware(ProxyHeadersMiddleware,
                       trusted_hosts=config.settings.trusted_proxy_hosts)
    return True
