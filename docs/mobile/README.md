# WebView、扫码与 NFC 接入

个人版和团队版均可嵌入 App WebView：

```text
https://example.com/component-warehouse/personal/?embed=1
https://example.com/component-warehouse/team/?embed=1
```

嵌入模式会隐藏网页端顶栏和底部导航，保留安全区间距，并通过
`window.ComponentWarehouseBridge` 提供统一桥接接口。

## Web Bridge

网页向原生端发送 JSON 消息，`source` 固定为
`component-warehouse-web`，协议版本为 `1.0`。支持 React Native
`postMessage`、Android 注入对象、iOS `WKScriptMessageHandler` 和同源 iframe。

原生端可调用：

- `receiveAuthSession(session)`：注入 Component Warehouse Account V1 会话。
- `receiveScan({ value })` 或 `receiveScan({ values })`：回传一个或多个扫码结果。
- `receiveNfc(payload)`：回传 NFC 内容。
- `navigate(path)`：切换个人版或团队版内部页面。
- `openAccountSettings()`：打开账号设置抽屉。

网页端会发送：

- `web.ready`
- `navigation.changed`
- `scan.request`
- `nfc.request`

## 能力与批量解析 API

```text
GET  /component-warehouse/api/mobile/v1/capabilities
POST /component-warehouse/api/mobile/v1/personal/resolve-batch
POST /component-warehouse/api/mobile/v1/team/libraries/{libraryId}/resolve-batch
```

批量解析最多接受 50 个值，支持器件 ID、立创 ID、个人版二维码 URL 和
团队版二维码 URL。个人和团队批量解析均要求登录；团队接口还会校验成员身份。

网页扫码优先使用浏览器 `BarcodeDetector`，可在同一画面识别多个二维码；不支持
该能力时自动使用 ZXing 连续识别并累积去重。由于浏览器权限限制，启动相机必须由
用户点击触发，并要求 HTTPS 或受信任的 App WebView 环境。
