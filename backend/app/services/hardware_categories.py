from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class HardwareCategory:
    zone: int
    name: str
    prefix: str
    color: str
    summary: str

    @property
    def location(self) -> str:
        return f"{self.zone:02d} {self.name}"


HARDWARE_CATEGORIES = (
    HardwareCategory(1, "贴片电阻", "RES", "#DBEAFE", "普通 SMD 电阻"),
    HardwareCategory(2, "直插/采样电阻", "RSP", "#BFDBFE", "插件、电位器、mΩ 采样/分流电阻"),
    HardwareCategory(3, "MLCC", "MLC", "#DCFCE7", "陶瓷电容"),
    HardwareCategory(4, "电解/固态", "ELC", "#BBF7D0", "贴片或直插电解、固态电容"),
    HardwareCategory(5, "电感/晶振", "MAG", "#FEF3C7", "电感、磁珠、晶体和振荡器"),
    HardwareCategory(6, "二极管/保护", "DPR", "#FCE7F3", "二极管、LED、TVS/ESD 和保险丝"),
    HardwareCategory(7, "BJT/MOS", "TRS", "#FFE4E6", "双极型晶体管和 MOSFET"),
    HardwareCategory(8, "电源IC", "PWR", "#FFEDD5", "LDO、DC-DC、PD、充电和电池管理裸芯片"),
    HardwareCategory(9, "模拟IC", "ANA", "#EDE9FE", "运放、比较器、基准、电流和功率检测芯片"),
    HardwareCategory(10, "数字/接口IC", "DIG", "#E0E7FF", "逻辑、通信接口、MCU、驱动和隔离芯片"),
    HardwareCategory(11, "传感器", "SEN", "#D9F99D", "温湿度、压力、光学、运动和其他传感器"),
    HardwareCategory(12, "排针/排母", "HDR", "#CCFBF1", "排针、排母、牛角座和 IDC"),
    HardwareCategory(13, "PH/XH/ZH/MX", "W2B", "#99F6E4", "PH/XH/ZH/MX/KF 板线连接器"),
    HardwareCategory(14, "USB/XT/线束", "CON", "#F5F5F4", "USB、XT、DC、接线端子和线束"),
    HardwareCategory(15, "开关/机电", "MEC", "#FAE8FF", "开关、蜂鸣器、风扇和电机"),
    HardwareCategory(16, "模块/开发板/显示", "MOD", "#FDE68A", "开发板、功能/通信模块和显示屏"),
    HardwareCategory(17, "结构/工具/电池", "UTL", "#E7E5E4", "结构件、工具、电池、充电器和设备"),
)

CATEGORY_BY_NAME = {item.name: item for item in HARDWARE_CATEGORIES}
CATEGORY_NAMES = tuple(item.name for item in HARDWARE_CATEGORIES)


def _haystack(values: Iterable[object]) -> str:
    return " ".join(str(value or "") for value in values).casefold()


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_hardware_category(*values: object) -> tuple[str | None, str | None]:
    """Classify inventory into the physical 17-zone standard.

    Rules are deliberately deterministic so imports, pasted LCSC rows, desktop
    writes and AI-assisted flows all choose the same physical bin.
    """
    text = _haystack(values)
    if not text.strip():
        return None, None

    # Finished boards/modules/displays take precedence over their on-board ICs.
    if _has(text, r"开发板|核心板|评估板|模组|模块|module|devkit|display|显示屏|显示模块|液晶屏|oled|tft|lcd|屏幕|数码管模块"):
        return "模块/开发板/显示", "检测到成品模块、开发板或显示器件"

    # Connector families are intentionally resolved before generic IC/interface words.
    if _has(text, r"排针|排母|牛角座|简牛|idc|pin\s*header|female\s*header"):
        return "排针/排母", "检测到排针、排母或 IDC 连接器"
    if _has(text, r"(?:^|[^a-z0-9])(ph|xh|zh|mx|kf)[-\s]?\d|ph\d|xh\d|zh\d|mx\d|kf\d|杜邦"):
        return "PH/XH/ZH/MX", "检测到板线连接器系列"

    ic_hint = _has(
        text,
        r"\bic\b|芯片|集成电路|soc|mcu|qfn|dfn|sop|ssop|esop|tssop|lqfp|bga|dip[- ]?\d|sot[- ]?23[- ]?\d",
    )
    if ic_hint and _has(
        text,
        r"电源|稳压|降压|升压|buck|boost|ldo|dc[- ]?dc|充电|电池管理|受电协议|快充|power\s*delivery|\bpd\b|pps|epr|pmic|ap64350|xl1509|ip5506|ip6557|ch224",
    ):
        return "电源IC", "检测到电源转换、充电或快充协议裸芯片"
    if ic_hint and _has(text, r"运放|放大器|比较器|基准|电流检测|功率检测|仪表放大|op[- ]?amp|amplifier|comparator|reference|adc|dac"):
        return "模拟IC", "检测到模拟信号链芯片"
    if ic_hint and _has(text, r"逻辑|接口|通信|收发器|隔离|驱动|微控制器|单片机|usb|uart|rs[- ]?485|can|ethernet|i2c|spi|gpio|driver|transceiver|isolator|esp32|stm32"):
        return "数字/接口IC", "检测到数字、通信接口、MCU 或驱动芯片"
    if ic_hint:
        return "数字/接口IC", "检测到未细分的数字/通用集成电路"

    if _has(text, r"传感器|探头|热电偶|pt1000?|温度|湿度|气压|压力|加速度|陀螺|光照|霍尔|sensor|thermocouple"):
        return "传感器", "检测到传感器或测量探头"
    if _has(text, r"mosfet|mos管|场效应|n沟道|p沟道|n-channel|p-channel|三极管|晶体管|\bbjt\b|npn|pnp|igbt"):
        return "BJT/MOS", "检测到 BJT 或 MOSFET"
    if _has(text, r"二极管|肖特基|稳压管|整流|发光二极管|\bled\b|\btvs\b|\besd\b|保险丝|熔断|自恢复|pptc|zener|schottky|rectifier"):
        return "二极管/保护", "检测到二极管、LED 或保护器件"
    if _has(text, r"电感|磁珠|扼流|晶振|晶体|振荡器|inductor|ferrite|crystal|oscillator"):
        return "电感/晶振", "检测到磁性器件或时钟源"
    if _has(text, r"电解|固态电容|铝电容|钽电容|polymer|electrolytic"):
        return "电解/固态", "检测到电解或固态电容"
    if _has(text, r"mlcc|陶瓷电容|瓷片电容|贴片电容|ceramic\s*capacitor"):
        return "MLCC", "检测到陶瓷电容"
    if _has(text, r"电容|capacitor"):
        return "电解/固态" if _has(text, r"插件|直插|径向") else "MLCC", "按电容结构和安装方式分类"
    if _has(text, r"采样电阻|分流电阻|毫欧|m[ωΩ]|电位器|可调电阻|插件电阻|直插电阻|金属膜电阻|水泥电阻|shunt|potentiometer|through[- ]?hole"):
        return "直插/采样电阻", "检测到直插、电位器或低阻采样电阻"
    if _has(text, r"贴片电阻|厚膜电阻|薄膜电阻|\b(?:0201|0402|0603|0805|1206|1210|2010|2512)\b.*电阻|resistor"):
        return "贴片电阻", "检测到普通贴片电阻"

    if _has(text, r"usb|type[- ]?c|usb[- ]?c|xt\d|dc座|dc插座|接线端子|端子台|线束|导线|电源线|转接线|连接线|插头|插座|receptacle|connector|terminal|cable|wire harness"):
        return "USB/XT/线束", "检测到 USB、电源连接器、端子或线束"
    if _has(text, r"开关|按键|按钮|继电器|蜂鸣器|喇叭|风扇|电机|马达|水泵|电磁阀|switch|relay|buzzer|fan|motor|pump"):
        return "开关/机电", "检测到开关或机电执行器"
    if _has(text, r"结构|外壳|螺丝|螺母|铜柱|垫片|支架|散热|工具|烙铁|焊台|镊子|电池|充电器|万用表|示波器|设备|机箱|case|screw|heatsink|battery|charger|tool"):
        return "结构/工具/电池", "检测到结构件、工具、电池或设备"
    return None, None
