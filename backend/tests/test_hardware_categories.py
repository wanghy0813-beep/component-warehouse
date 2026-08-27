from app.services.hardware_categories import CATEGORY_NAMES, classify_hardware_category


def test_17_zone_catalog_is_complete_and_ordered():
    assert len(CATEGORY_NAMES) == 17
    assert CATEGORY_NAMES[0] == "贴片电阻"
    assert CATEGORY_NAMES[-1] == "结构/工具/电池"


def test_deterministic_classification_resolves_ambiguous_power_and_module_parts():
    assert classify_hardware_category("5mΩ 3W 2512 电流采样电阻")[0] == "直插/采样电阻"
    assert classify_hardware_category("47uF 63V 直插铝电解电容")[0] == "电解/固态"
    assert classify_hardware_category("CH224A ESSOP-10 USB PD 受电协议芯片")[0] == "电源IC"
    assert classify_hardware_category("ESP32-C3-MINI-1-N4 Wi-Fi BLE 模组")[0] == "模块/开发板/显示"
    assert classify_hardware_category("1.54 英寸 TFT LCD ST7789 裸屏")[0] == "模块/开发板/显示"
    assert classify_hardware_category("PT1000 A级两线制温度传感器")[0] == "传感器"
    assert classify_hardware_category("USB4105 Type-C 母座 connector")[0] == "USB/XT/线束"
