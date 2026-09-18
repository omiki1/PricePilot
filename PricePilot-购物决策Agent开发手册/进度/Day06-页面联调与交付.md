# Day 6：页面联调与交付

[上一阶段](Day05-收藏历史与降价提醒.md) · [返回看板](../03-进度看板.md) · [完整验收](../验收/01-验收用例与演示脚本.md)

## 今天只解决什么

让用户完整走一遍需求到收藏提醒；把正常状态、部分失败和真实数据边界清楚展示出来。

## 前置与阅读

前五阶段核心用例已通过。读 [API 与 SSE](../app/web/chat_router/接口与SSE协议.md)、[页面说明](../app/html/页面与交互说明.md)、[参考图](../参考图/01-流程与页面草图.md)。

## 未来要写的文件

shopping.html；chat_router.py 事件与快照接口；watch_router.py 页面联调；default_page_router.py；main.py 静态资源路径；端到端验证与项目运行说明。

## 按这个顺序实施

1. 做输入区和进度条，先让阶段事件正确显示。
2. 用 report_ready 渲染卡片、价格明细和比较表；金额不从自然语言解析。
3. 加澄清输入、商品图片、普通/联盟链接、证据展开、刷新报价和收藏弹层。
4. 对齐等待、无结果、部分来源失败、过期价、评论为空、运行失败等状态。
5. 验证断线重连只恢复订阅，重复 event_id 不重复渲染，终态后关闭连接。
6. 接收藏/阈值/暂停/删除，显示上次检查与通知状态。
7. 手机宽度和桌面宽度各走一遍；整理运行步骤、依赖版本、数据源状态与已知限制。

## 演示必须包括

一次正常查询；一次同款误匹配被拦截；一次未知会员优惠；一次来源失败降级；一次测试降价提醒（仅演示或已获准配置）。不能只展示一条预设成功路径。

## 验收清单

- [ ] 价格卡内规格、条件、来源、时间齐全。
- [ ] 演示标记持续可见；真实来源覆盖范围清楚。
- [ ] 不会出现重复报告、永远加载或串会话。
- [ ] 用户能理解首选理由与未确认项。
- [ ] 阈值明确按付款金额，返现单列。
- [ ] 手机下表格可滚动或改为卡片，数字和按钮不截断。
- [ ] 端到端用例有实际结果，而不是只打勾。

## 最终交付物

可启动项目、环境与版本记录、数据来源能力清单、通过/失败用例记录、真实接入状态、演示脚本、下一阶段待办。确认 M6、M7、M8 分别是否达到，不用“全部完成”掩盖尚未接通的平台。
## V2 图片与购买链接验收

商品卡显示获准的 API 图片 URL；图片失败显示占位。推广链接只在获准时优先使用，页面披露可能获得佣金，排序不使用佣金字段。跨币种卡片分组，价格不在浏览器重算。

## 参考代码：服务端选择商品跳转地址（模块参考）

目标：Reporter 使用的 card_presenter.py。allowed_hosts 必须由平台配置精确提供，既覆盖正常商品域名也覆盖已获准推广域名；短链重定向归属由适配器验证，不以这段 URL 语法检查代替。

```python
from urllib.parse import urlparse


def safe_https_url(raw: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(raw)
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError("商品链接不属于允许的HTTPS来源")
    return raw

def choose_purchase_url(product_url: str, affiliate_url: str | None,
                        affiliate_approved: bool, allowed_hosts: set[str]) -> str:
    normal = safe_https_url(product_url, allowed_hosts)
    if affiliate_approved and affiliate_url:
        return safe_https_url(affiliate_url, allowed_hosts)
    return normal

assert choose_purchase_url(
    "https://example.com/demo/a", None, False, {"example.com"}
) == "https://example.com/demo/a"
```

还要验证链接指向对应商品，而不只是域名正确。该断言使用保留示例域名，无真实购买或推广操作。
