# 制造包导出指南（v1.1.0）

WXY LAB Hardware 的可靠输入是一个 ZIP，至少应包含 Gerber、BOM 和 CPL/Pick-and-Place。位置、旋转和板面以 CPL 为准；普通 Gerber 不承诺能恢复可靠位号。

## 嘉立创 / EasyEDA

导出 Gerber，并同时导出 BOM 和 Pick and Place/CPL。不要重命名为没有扩展名的文件；推荐保留 `BOM.csv`、`PickAndPlace.csv` 和标准 Gerber 扩展名。BOM 位号可以用逗号或空格列出多个位号。

## KiCad

在 PCB 编辑器中导出 Gerber，然后导出“元件位置文件”。CSV 或 `.pos` 均可；位置文件应包含 `Ref`、`PosX`、`PosY`、`Rot`、`Side`，并保留 `Unit = mm/inches` 注释。另行导出包含 Reference、Value、Footprint 和 MPN 的 BOM。

## Altium Designer

生成 Gerber/NC Drill；从装配输出导出 Pick and Place，保留 `Designator`、`Center X`、`Center Y`、`Layer`、`Rotation`；BOM 保留 `Designators`、`Description/Value`、`Footprint`、`Manufacturer Part Number` 和 `Fitted`。

仅有 `.GTL/.GBL/.GTO/.GBO/.GTS/.GBS/.GM1/.G1/.G2` 和 NC Drill 的 OutJob 属于纯制造图层包：系统可以显示真实板图，但会停在“待映射”，不会从丝印猜位号中心。请在同一 ZIP 中加入 BOM/Pick and Place，或在版本预览中补传这两份表格。

## 上传前检查

- ZIP 不超过 200MB，展开后不超过 512MB，最多 500 个条目。
- 不放入其他 ZIP/7z/RAR、符号链接、加密文件或无关账号/订单资料。
- CPL 单位和底面定义应明确；拼板作为一个设计整体上传。
- DNP/Fitted 列语义要明确。系统不会做模糊料号替换。
- 只缺 BOM 或 CPL 时可在预览中补传；补传不会改原始 ZIP，仍永久关联到同一制造版本。

若使用 AI 映射降级，界面会明确标识。AI 只接收表格文件名和完整 BOM/CPL 内容（包括 CPL 坐标），不接收 Gerber、库存、库存库位、成员、团队或账号数据；建议必须由操作者确认。
