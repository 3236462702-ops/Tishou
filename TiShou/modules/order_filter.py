# -*- coding: utf-8 -*-
"""
订单筛选模块（完整版）
==================
遵守全局约束，提供订单的多维度筛选能力。

功能：
  1. 金额区间、接驾距离(最大10km)、订单里程(最低20km)
  2. 区域黑白名单、订单类型多选
  3. 单价过滤(默认1-8元/公里，金额÷里程计算)
  4. 定位加载省市 / 全国手动选择
  5. 自动下拉刷新(固定/随机双模式)
  6. 点击延迟(固定/随机双模式)
  7. 全部条件满足才判定为可抢订单
  8. 参数持久化、区间重置、完整异常处理
"""

import sys
import os
import json
import time
import threading
import random
import re
from datetime import datetime
from typing import Optional, Callable, List, Dict, Any, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    safe_int, safe_float, safe_bool, safe_str,
    ensure_dir,
)


# ============================================================
# 常量定义
# ============================================================

# ---- 金额区间（元） ----
DEFAULT_MIN_PRICE = 0.0
DEFAULT_MAX_PRICE = 999999.0

# ---- 接驾距离（km），最大 10km ----
DEFAULT_MIN_PICKUP_DIST = 0.0
DEFAULT_MAX_PICKUP_DIST = 10.0

# ---- 订单里程（km），最低 20km ----
DEFAULT_MIN_ORDER_DIST = 20.0
DEFAULT_MAX_ORDER_DIST = 999999.0

# ---- 单价过滤（元/km），默认 1-8 元/公里 ----
DEFAULT_MIN_UNIT_PRICE = 1.0
DEFAULT_MAX_UNIT_PRICE = 8.0

# ---- 订单类型（必须与约束定义一致） ----
ORDER_TYPES = [
    {"key": "fast", "name": "快车"},
    {"key": "express", "name": "特快"},
    {"key": "special_offer", "name": "特惠"},
    {"key": "long_distance", "name": "长途特惠"},
    {"key": "small_item", "name": "小件"},
    {"key": "carpool", "name": "拼车"},
]

# ---- 刷新模式 ----
class RefreshMode:
    """刷新模式常量"""

    FIXED = "fixed"          # 固定间隔
    RANDOM = "random"        # 随机间隔


# ---- 点击延迟模式 ----
class ClickMode:
    """点击延迟模式常量"""

    FIXED = "fixed"          # 固定延迟
    RANDOM = "random"        # 随机延迟


# ---- 默认值 ----
DEFAULT_REFRESH_FIXED_MIN = 1.0
DEFAULT_REFRESH_FIXED_MAX = 10.0
DEFAULT_REFRESH_RANDOM_MIN = 2.0
DEFAULT_REFRESH_RANDOM_MAX = 5.0
DEFAULT_CLICK_FIXED_MS = 1000       # 1 秒
DEFAULT_CLICK_RANDOM_MIN_MS = 500   # 0.5 秒
DEFAULT_CLICK_RANDOM_MAX_MS = 5000  # 5 秒

# ---- 区域数据 ----
# 内置中国省市数据（免费、免注册、无授权）
# 当定位成功时自动匹配省市；定位失败时供用户手动选择全国
PROVINCES = [
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省",
    "黑龙江省", "江苏省", "浙江省", "安徽省",
    "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省",
    "甘肃省", "青海省", "台湾省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区",
    "香港特别行政区", "澳门特别行政区",
]

CITIES_BY_PROVINCE = {
    "北京市": ["东城区", "西城区", "朝阳区", "海淀区", "丰台区", "石景山区",
               "通州区", "大兴区", "房山区", "门头沟区", "昌平区", "顺义区",
               "平谷区", "怀柔区", "密云区", "延庆区"],
    "天津市": ["和平区", "河东区", "河西区", "南开区", "河北区", "红桥区",
               "东丽区", "西青区", "津南区", "北辰区", "武清区", "宝坻区",
               "滨海新区", "宁河区", "静海区", "蓟州区"],
    "上海市": ["黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区",
               "杨浦区", "闵行区", "宝山区", "嘉定区", "浦东新区",
               "金山区", "松江区", "青浦区", "奉贤区", "崇明区"],
    "重庆市": ["渝中区", "江北区", "南岸区", "沙坪坝区", "九龙坡区", "大渡口区",
               "北碚区", "渝北区", "巴南区", "万州区", "涪陵区", "黔江区",
               "长寿区", "江津区", "合川区", "永川区", "南川区",
               "璧山区", "铜梁区", "潼南区", "荣昌区", "开州区",
               "梁平区", "武隆区", "城口县", "丰都县", "垫江县",
               "忠县", "云阳县", "奉节县", "巫山县", "巫溪县",
               "石柱土家族自治县", "秀山土家族苗族自治县",
               "酉阳土家族苗族自治县", "彭水苗族土家族自治县"],
    "河北省": ["石家庄市", "唐山市", "秦皇岛市", "邯郸市", "邢台市", "保定市",
               "张家口市", "承德市", "沧州市", "廊坊市", "衡水市"],
    "山西省": ["太原市", "大同市", "阳泉市", "长治市", "晋城市", "朔州市",
               "晋中市", "运城市", "忻州市", "临汾市", "吕梁市"],
    "辽宁省": ["沈阳市", "大连市", "鞍山市", "抚顺市", "本溪市", "丹东市",
               "锦州市", "营口市", "阜新市", "辽阳市", "盘锦市",
               "铁岭市", "朝阳市", "葫芦岛市"],
    "吉林省": ["长春市", "吉林市", "四平市", "辽源市", "通化市", "白山市",
               "松原市", "白城市", "延边朝鲜族自治州"],
    "黑龙江省": ["哈尔滨市", "齐齐哈尔市", "鸡西市", "鹤岗市", "双鸭山市",
                 "大庆市", "伊春市", "佳木斯市", "七台河市", "牡丹江市",
                 "黑河市", "绥化市", "大兴安岭地区"],
    "江苏省": ["南京市", "无锡市", "徐州市", "常州市", "苏州市", "南通市",
               "连云港市", "淮安市", "盐城市", "扬州市", "镇江市",
               "泰州市", "宿迁市"],
    "浙江省": ["杭州市", "宁波市", "温州市", "嘉兴市", "湖州市", "绍兴市",
               "金华市", "衢州市", "舟山市", "台州市", "丽水市"],
    "安徽省": ["合肥市", "芜湖市", "蚌埠市", "淮南市", "马鞍山市", "淮北市",
               "铜陵市", "安庆市", "黄山市", "滁州市", "阜阳市",
               "宿州市", "六安市", "亳州市", "池州市", "宣城市"],
    "福建省": ["福州市", "厦门市", "莆田市", "三明市", "泉州市", "漳州市",
               "南平市", "龙岩市", "宁德市"],
    "江西省": ["南昌市", "景德镇市", "萍乡市", "九江市", "新余市", "鹰潭市",
               "赣州市", "吉安市", "宜春市", "抚州市", "上饶市"],
    "山东省": ["济南市", "青岛市", "淄博市", "枣庄市", "东营市", "烟台市",
               "潍坊市", "济宁市", "泰安市", "威海市", "日照市",
               "临沂市", "德州市", "聊城市", "滨州市", "菏泽市"],
    "河南省": ["郑州市", "开封市", "洛阳市", "平顶山市", "安阳市", "鹤壁市",
               "新乡市", "焦作市", "濮阳市", "许昌市", "漯河市",
               "三门峡市", "南阳市", "商丘市", "信阳市", "周口市", "驻马店市"],
    "湖北省": ["武汉市", "黄石市", "十堰市", "宜昌市", "襄阳市", "鄂州市",
               "荆门市", "孝感市", "荆州市", "黄冈市", "咸宁市",
               "随州市", "恩施土家族苗族自治州"],
    "湖南省": ["长沙市", "株洲市", "湘潭市", "衡阳市", "邵阳市", "岳阳市",
               "常德市", "张家界市", "益阳市", "郴州市", "永州市",
               "怀化市", "娄底市", "湘西土家族苗族自治州"],
    "广东省": ["广州市", "韶关市", "深圳市", "珠海市", "汕头市", "佛山市",
               "江门市", "湛江市", "茂名市", "肇庆市", "惠州市",
               "梅州市", "汕尾市", "河源市", "阳江市", "清远市",
               "东莞市", "中山市", "潮州市", "揭阳市", "云浮市"],
    "海南省": ["海口市", "三亚市", "三沙市", "儋州市", "五指山市",
               "琼海市", "文昌市", "万宁市", "东方市"],
    "四川省": ["成都市", "自贡市", "攀枝花市", "泸州市", "德阳市", "绵阳市",
               "广元市", "遂宁市", "内江市", "乐山市", "南充市",
               "眉山市", "宜宾市", "广安市", "达州市", "雅安市",
               "巴中市", "资阳市", "阿坝藏族羌族自治州",
               "甘孜藏族自治州", "凉山彝族自治州"],
    "贵州省": ["贵阳市", "六盘水市", "遵义市", "安顺市", "毕节市",
               "铜仁市", "黔西南布依族苗族自治州",
               "黔东南苗族侗族自治州", "黔南布依族苗族自治州"],
    "云南省": ["昆明市", "曲靖市", "玉溪市", "保山市", "昭通市", "丽江市",
               "普洱市", "临沧市", "楚雄彝族自治州",
               "红河哈尼族彝族自治州", "文山壮族苗族自治州",
               "西双版纳傣族自治州", "大理白族自治州",
               "德宏傣族景颇族自治州", "怒江傈僳族自治州",
               "迪庆藏族自治州"],
    "陕西省": ["西安市", "铜川市", "宝鸡市", "咸阳市", "渭南市", "延安市",
               "汉中市", "榆林市", "安康市", "商洛市"],
    "甘肃省": ["兰州市", "嘉峪关市", "金昌市", "白银市", "天水市", "武威市",
               "张掖市", "平凉市", "酒泉市", "庆阳市", "定西市",
               "陇南市", "临夏回族自治州", "甘南藏族自治州"],
    "青海省": ["西宁市", "海东市", "海北藏族自治州", "黄南藏族自治州",
               "海南藏族自治州", "果洛藏族自治州", "玉树藏族自治州",
               "海西蒙古族藏族自治州"],
    "台湾省": ["台北市", "高雄市", "台中市", "台南市", "新北市",
               "基隆市", "新竹市", "嘉义市"],
    "内蒙古自治区": ["呼和浩特市", "包头市", "乌海市", "赤峰市", "通辽市",
                    "鄂尔多斯市", "呼伦贝尔市", "巴彦淖尔市", "乌兰察布市",
                    "兴安盟", "锡林郭勒盟", "阿拉善盟"],
    "广西壮族自治区": ["南宁市", "柳州市", "桂林市", "梧州市", "北海市",
                      "防城港市", "钦州市", "贵港市", "玉林市", "百色市",
                      "贺州市", "河池市", "来宾市", "崇左市"],
    "西藏自治区": ["拉萨市", "日喀则市", "昌都市", "林芝市", "山南市",
                   "那曲市", "阿里地区"],
    "宁夏回族自治区": ["银川市", "石嘴山市", "吴忠市", "固原市", "中卫市"],
    "新疆维吾尔自治区": ["乌鲁木齐市", "克拉玛依市", "吐鲁番市", "哈密市",
                        "昌吉回族自治州", "博尔塔拉蒙古自治州",
                        "巴音郭楞蒙古自治州", "阿克苏地区",
                        "克孜勒苏柯尔克孜自治州", "喀什地区",
                        "和田地区", "伊犁哈萨克自治州",
                        "塔城地区", "阿勒泰地区"],
    "香港特别行政区": ["中西区", "湾仔区", "东区", "南区", "油尖旺区",
                      "深水埗区", "九龙城区", "黄大仙区", "观塘区",
                      "荃湾区", "屯门区", "元朗区", "北区",
                      "大埔区", "西贡区", "沙田区", "离岛区"],
    "澳门特别行政区": ["花地玛堂区", "圣安多尼堂区", "大堂区",
                      "望德堂区", "风顺堂区", "氹仔", "路环"],
}


# ============================================================
# 区域管理器
# ============================================================

class RegionManager:
    """
    区域管理器
    =========
    管理省市区域数据，支持：
      - 自动定位加载省市（通过免费公共 API）
      - 定位失败手动选择全国
      - 区域黑白名单
      - 全选/反选/清空
    """

    def __init__(self):
        """初始化区域管理器"""
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()
        self._listener: Optional[Callable] = None

        # ---- 区域数据 ----
        self._provinces: List[str] = list(PROVINCES)
        self._cities_by_province: Dict[str, List[str]] = dict(CITIES_BY_PROVINCE)

        # ---- 当前选中的省份和城市 ----
        self._current_province: str = ""
        self._current_city: str = ""
        self._location_ok: bool = False  # 定位是否成功

        # ---- 区域白名单 / 黑名单 ----
        # 白名单模式：只接白名单中的区域订单
        # 黑名单模式：不接黑名单中的区域订单
        self._use_whitelist: bool = True
        self._region_whitelist: List[str] = []   # ["北京市/朝阳区", ...]
        self._region_blacklist: List[str] = []

    # ============================================================
    # 省市数据
    # ============================================================

    def get_provinces(self) -> List[str]:
        """获取省份列表"""
        return list(self._provinces)

    def get_cities(self, province: str) -> List[str]:
        """获取某省份的城市列表"""
        return list(self._cities_by_province.get(province, []))

    def get_all_cities(self) -> List[str]:
        """获取所有城市（扁平化）"""
        all_cities = []
        for cities in self._cities_by_province.values():
            all_cities.extend(cities)
        return all_cities

    def is_valid_region(self, province: str, city: str = "") -> bool:
        """验证省市是否有效"""
        if province not in self._provinces:
            return False
        if city and city not in self._cities_by_province.get(province, []):
            return False
        return True

    # ============================================================
    # 定位
    # ============================================================

    @ExceptionUtil.safe_call(default_return=False, log_level="warning")
    def auto_locate(self) -> bool:
        """
        自动获取当前定位信息（省市）

        通过免费公共 IP 定位 API 获取当前位置，
        定位成功自动设置省市，失败返回 False。

        :return: True=定位成功
        """
        try:
            import requests

            # 使用 ip-api.com 免费 IP 定位（免注册、无授权）
            resp = requests.get(
                "http://ip-api.com/json/?fields=status,regionName,city",
                timeout=5,
            )
            if resp.status_code != 200:
                self._logger.warning("IP定位API响应异常")
                return False

            data = resp.json()
            if data.get("status") != "success":
                self._logger.warning("IP定位失败")
                return False

            region_name = data.get("regionName", "")
            city = data.get("city", "")

            if not region_name:
                self._logger.warning("定位未获取到省份信息")
                return False

            # 省份名称匹配（regionName 可能是 "Beijing" 或 "北京市"）
            matched_province = self._match_province(region_name)
            if not matched_province:
                self._logger.warning(f"无法匹配省份: {region_name}")
                return False

            # 城市名称匹配
            matched_city = self._match_city(matched_province, city) if city else ""

            self._current_province = matched_province
            self._current_city = matched_city
            self._location_ok = True

            self._logger.info(
                f"定位成功: {matched_province} {matched_city}"
            )
            self._notify_changed()
            return True

        except ImportError:
            self._logger.warning("requests 未安装，无法定位")
            return False
        except requests.RequestException as e:
            self._logger.warning(f"定位请求失败: {e}")
            return False
        except Exception as e:
            self._logger.warning(f"定位异常: {e}")
            return False

    def _match_province(self, name: str) -> str:
        """将 API 返回的地名匹配到内置省份列表"""
        name = name.strip()

        # 直接匹配
        if name in self._provinces:
            return name

        # 去掉"省""市""自治区"后缀匹配
        for suffix in ["省", "市", "壮族自治区", "回族自治区",
                       "维吾尔自治区", "自治区", "特别行政区"]:
            if name.endswith(suffix):
                base = name[:-len(suffix)]
                for p in self._provinces:
                    if base in p:
                        return p
                return base + ("省" if base not in ["北京", "天津", "上海", "重庆"] else "市")

        # 英文名匹配
        en_map = {
            "Beijing": "北京市", "Tianjin": "天津市", "Shanghai": "上海市",
            "Chongqing": "重庆市", "Hebei": "河北省", "Shanxi": "山西省",
            "Liaoning": "辽宁省", "Jilin": "吉林省", "Heilongjiang": "黑龙江省",
            "Jiangsu": "江苏省", "Zhejiang": "浙江省", "Anhui": "安徽省",
            "Fujian": "福建省", "Jiangxi": "江西省", "Shandong": "山东省",
            "Henan": "河南省", "Hubei": "湖北省", "Hunan": "湖南省",
            "Guangdong": "广东省", "Hainan": "海南省", "Sichuan": "四川省",
            "Guizhou": "贵州省", "Yunnan": "云南省", "Shaanxi": "陕西省",
            "Gansu": "甘肃省", "Qinghai": "青海省", "Taiwan": "台湾省",
            "Inner Mongolia": "内蒙古自治区", "Guangxi": "广西壮族自治区",
            "Tibet": "西藏自治区", "Ningxia": "宁夏回族自治区",
            "Xinjiang": "新疆维吾尔自治区",
            "Hong Kong": "香港特别行政区", "Macau": "澳门特别行政区",
        }
        if name in en_map:
            return en_map[name]

        # 拼音匹配
        for p in self._provinces:
            if name.lower() in p.lower():
                return p

        return ""

    def _match_city(self, province: str, city_name: str) -> str:
        """将城市名匹配到内置城市列表"""
        city_name = city_name.strip()

        cities = self._cities_by_province.get(province, [])

        # 直接匹配
        if city_name in cities:
            return city_name

        # 去掉"市"后缀匹配
        if city_name.endswith("市"):
            base = city_name[:-1]
            for c in cities:
                if base in c:
                    return c

        # 包含匹配
        for c in cities:
            if city_name.lower() in c.lower():
                return c

        # 英文匹配
        for c in cities:
            if city_name.lower() == c.replace("市", "").lower():
                return c

        return cities[0] if cities else ""

    # ============================================================
    # 定位状态
    # ============================================================

    def is_location_ok(self) -> bool:
        """定位是否成功"""
        return self._location_ok

    def get_current_province(self) -> str:
        """获取当前定位省份"""
        return self._current_province

    def get_current_city(self) -> str:
        """获取当前定位城市"""
        return self._current_city

    def set_manual_location(self, province: str, city: str = ""):
        """
        手动设置省市（定位失败时使用）

        :param province: 省份
        :param city: 城市（可选）
        """
        try:
            if province in self._provinces:
                self._current_province = province
                self._current_city = city if city in self._cities_by_province.get(province, []) else ""
                self._location_ok = True
                self._logger.info(f"手动设置定位: {province} {city}")
                self._notify_changed()
        except Exception as e:
            self._logger.error(f"手动设置定位异常: {e}")

    def reset_location(self):
        """重置定位"""
        self._current_province = ""
        self._current_city = ""
        self._location_ok = False
        self._notify_changed()

    # ============================================================
    # 黑白名单管理
    # ============================================================

    def set_mode(self, use_whitelist: bool):
        """
        设置区域模式
        :param use_whitelist: True=白名单模式, False=黑名单模式
        """
        self._use_whitelist = use_whitelist

    def is_whitelist_mode(self) -> bool:
        """是否为白名单模式"""
        return self._use_whitelist

    def get_region_list(self) -> List[str]:
        """获取当前模式下的区域列表"""
        return list(self._region_whitelist if self._use_whitelist else self._region_blacklist)

    def add_region(self, region: str):
        """
        添加区域到当前模式列表
        :param region: 区域格式 "省份/城市"
        """
        try:
            target = self._region_whitelist if self._use_whitelist else self._region_blacklist
            if region not in target:
                target.append(region)
                self._logger.debug(f"添加区域: {region}")
                self._notify_changed()
        except Exception as e:
            self._logger.error(f"添加区域异常: {e}")

    def remove_region(self, region: str):
        """
        从当前模式列表移除区域
        :param region: 区域格式 "省份/城市"
        """
        try:
            target = self._region_whitelist if self._use_whitelist else self._region_blacklist
            if region in target:
                target.remove(region)
                self._logger.debug(f"移除区域: {region}")
                self._notify_changed()
        except Exception as e:
            self._logger.error(f"移除区域异常: {e}")

    def select_all_regions(self):
        """全选所有区域"""
        try:
            target = self._region_whitelist if self._use_whitelist else self._region_blacklist
            target.clear()
            for province, cities in self._cities_by_province.items():
                for city in cities:
                    target.append(f"{province}/{city}")
            self._notify_changed()
        except Exception as e:
            self._logger.error(f"全选区域异常: {e}")

    def invert_regions(self):
        """反选区域"""
        try:
            target = self._region_whitelist if self._use_whitelist else self._region_blacklist
            # 收集所有区域
            all_regions = set()
            for province, cities in self._cities_by_province.items():
                for city in cities:
                    all_regions.add(f"{province}/{city}")

            current_set = set(target)
            new_set = all_regions - current_set
            target.clear()
            target.extend(sorted(new_set))
            self._notify_changed()
        except Exception as e:
            self._logger.error(f"反选区域异常: {e}")

    def clear_regions(self):
        """清空区域列表"""
        try:
            target = self._region_whitelist if self._use_whitelist else self._region_blacklist
            target.clear()
            self._notify_changed()
        except Exception as e:
            self._logger.error(f"清空区域异常: {e}")

    def is_region_allowed(self, province: str, city: str = "") -> bool:
        """
        判断某区域是否允许接单

        :param province: 省份
        :param city: 城市
        :return: True=允许
        """
        region_str = f"{province}/{city}" if city else province

        if self._use_whitelist:
            # 白名单模式：必须在白名单中
            return region_str in self._region_whitelist
        else:
            # 黑名单模式：不能出现在黑名单中
            return region_str not in self._region_blacklist

    # ============================================================
    # 变更通知
    # ============================================================

    def set_on_changed(self, callback: Optional[Callable]):
        """设置变更回调"""
        self._listener = callback

    def _notify_changed(self):
        """通知变更"""
        try:
            if self._listener:
                self._listener()
        except Exception:
            pass


# ============================================================
# 订单筛选器
# ============================================================

class OrderFilter:
    """
    订单筛选器
    =========
    根据配置的筛选条件判断订单是否可抢。
    所有条件必须全部满足（AND 逻辑）才判定为可抢订单。

    筛选维度：
      - 金额区间
      - 接驾距离（最大 10km）
      - 订单里程（最低 20km）
      - 区域黑白名单
      - 订单类型多选
      - 单价过滤（默认 1-8 元/km）
    """

    def __init__(self):
        """初始化订单筛选器"""
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()
        self._region_mgr = RegionManager()

        # ---- 金额区间 ----
        self._min_price: float = safe_float(
            self._config.get("order_filter.min_price"), DEFAULT_MIN_PRICE
        )
        self._max_price: float = safe_float(
            self._config.get("order_filter.max_price"), DEFAULT_MAX_PRICE
        )

        # ---- 接驾距离（km），最大 10km ----
        self._min_pickup_dist: float = safe_float(
            self._config.get("order_filter.min_pickup_dist"), DEFAULT_MIN_PICKUP_DIST
        )
        self._max_pickup_dist: float = safe_float(
            self._config.get("order_filter.max_pickup_dist"), DEFAULT_MAX_PICKUP_DIST
        )

        # ---- 订单里程（km），最低 20km ----
        self._min_order_dist: float = safe_float(
            self._config.get("order_filter.min_order_dist"), DEFAULT_MIN_ORDER_DIST
        )
        self._max_order_dist: float = safe_float(
            self._config.get("order_filter.max_order_dist"), DEFAULT_MAX_ORDER_DIST
        )

        # ---- 单价过滤（元/km） ----
        self._min_unit_price: float = safe_float(
            self._config.get("order_filter.min_unit_price"), DEFAULT_MIN_UNIT_PRICE
        )
        self._max_unit_price: float = safe_float(
            self._config.get("order_filter.max_unit_price"), DEFAULT_MAX_UNIT_PRICE
        )

        # ---- 订单类型（多选） ----
        saved_types = self._config.get("order_filter.order_types", [])
        self._order_types: List[str] = (
            saved_types if isinstance(saved_types, list) and saved_types
            else [t["key"] for t in ORDER_TYPES]  # 默认全部选中
        )

        # ---- 区域配置 ----
        saved_regions = self._config.get("order_filter.region_whitelist", [])
        if isinstance(saved_regions, list):
            self._region_mgr._region_whitelist = list(saved_regions)
        saved_blacklist = self._config.get("order_filter.region_blacklist", [])
        if isinstance(saved_blacklist, list):
            self._region_mgr._region_blacklist = list(saved_blacklist)
        self._region_mgr._use_whitelist = safe_bool(
            self._config.get("order_filter.use_whitelist"), True
        )

        # ---- 刷新模式 ----
        self._refresh_mode: str = self._config.get(
            "order_filter.refresh_mode", RefreshMode.FIXED
        )
        self._refresh_fixed_min: float = safe_float(
            self._config.get("order_filter.refresh_fixed_min"), DEFAULT_REFRESH_FIXED_MIN
        )
        self._refresh_fixed_max: float = safe_float(
            self._config.get("order_filter.refresh_fixed_max"), DEFAULT_REFRESH_FIXED_MAX
        )
        self._refresh_random_min: float = safe_float(
            self._config.get("order_filter.refresh_random_min"), DEFAULT_REFRESH_RANDOM_MIN
        )
        self._refresh_random_max: float = safe_float(
            self._config.get("order_filter.refresh_random_max"), DEFAULT_REFRESH_RANDOM_MAX
        )

        # ---- 点击延迟 ----
        self._click_mode: str = self._config.get(
            "order_filter.click_mode", ClickMode.FIXED
        )
        self._click_fixed_ms: int = safe_int(
            self._config.get("order_filter.click_fixed_ms"), DEFAULT_CLICK_FIXED_MS
        )
        self._click_random_min_ms: int = safe_int(
            self._config.get("order_filter.click_random_min_ms"), DEFAULT_CLICK_RANDOM_MIN_MS
        )
        self._click_random_max_ms: int = safe_int(
            self._config.get("order_filter.click_random_max_ms"), DEFAULT_CLICK_RANDOM_MAX_MS
        )

        self._logger.info("订单筛选器初始化完成")

    # ============================================================
    # 核心判定
    # ============================================================

    def should_grab(self, order_info: dict) -> Tuple[bool, str]:
        """
        判断是否应该抢此订单（全部条件满足才可抢）

        :param order_info: 订单信息字典，支持字段：
            {
                "price": float,           # 订单金额（元）
                "pickup_distance": float,  # 接驾距离（km）
                "order_distance": float,   # 订单里程（km）
                "unit_price": float,       # 单价（元/km），如不提供则自动计算
                "order_type": str,         # 订单类型 key
                "province": str,           # 出发地省份
                "city": str,               # 出发地城市
                "text": str,               # 原始 OCR 文本（关键词匹配）
            }
        :return: (True, "全部条件通过") 或 (False, "失败原因")
        """
        try:
            # ---- 1. 金额区间判断 ----
            price = safe_float(order_info.get("price", 0))
            if price == 0:
                return False, "金额为空"

            if price < self._min_price:
                return False, f"金额低于下限: {price} < {self._min_price}"
            if price > self._max_price:
                return False, f"金额高于上限: {price} > {self._max_price}"

            # ---- 2. 接驾距离判断（最大 10km） ----
            pickup_dist = safe_float(order_info.get("pickup_distance", -1))
            if pickup_dist >= 0:
                if pickup_dist < self._min_pickup_dist:
                    return False, f"接驾距离低于下限: {pickup_dist} < {self._min_pickup_dist}"
                if pickup_dist > self._max_pickup_dist:
                    return False, f"接驾距离超过上限: {pickup_dist} > {self._max_pickup_dist}"

            # ---- 3. 订单里程判断（最低 20km） ----
            order_dist = safe_float(order_info.get("order_distance", -1))
            if order_dist >= 0:
                if order_dist < self._min_order_dist:
                    return False, f"订单里程低于下限: {order_dist} < {self._min_order_dist}"
                if order_dist > self._max_order_dist:
                    return False, f"订单里程超过上限: {order_dist} > {self._max_order_dist}"

            # ---- 4. 单价过滤（元/km） ----
            unit_price = safe_float(order_info.get("unit_price", -1))
            if unit_price < 0 and order_dist > 0 and price > 0:
                # 自动计算单价：金额 ÷ 里程
                unit_price = price / order_dist

            if unit_price >= 0:
                if unit_price < self._min_unit_price:
                    return False, f"单价低于下限: {unit_price:.2f} < {self._min_unit_price}"
                if unit_price > self._max_unit_price:
                    return False, f"单价高于上限: {unit_price:.2f} > {self._max_unit_price}"

            # ---- 5. 订单类型判断 ----
            order_type = safe_str(order_info.get("order_type", ""))
            if order_type and self._order_types:
                if order_type not in self._order_types:
                    return False, f"订单类型不在选中列表: {order_type}"

            # ---- 6. 区域黑白名单判断 ----
            province = safe_str(order_info.get("province", ""))
            city = safe_str(order_info.get("city", ""))
            if province and not self._region_mgr.is_region_allowed(province, city):
                return False, f"区域不允许: {province}/{city}"

            return True, "全部条件通过"

        except Exception as e:
            self._logger.error(f"订单筛选异常: {e}")
            return False, f"筛选异常: {e}"

    # ============================================================
    # 筛选参数管理
    # ============================================================

    # ---- 金额区间 ----

    def set_price_range(self, min_val: float, max_val: float):
        """设置金额区间"""
        try:
            self._min_price = max(0.0, min_val)
            self._max_price = max(self._min_price, max_val)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置金额区间异常: {e}")

    def get_price_range(self) -> Tuple[float, float]:
        """获取金额区间"""
        return (self._min_price, self._max_price)

    def reset_price_range(self):
        """重置金额区间为默认"""
        self.set_price_range(DEFAULT_MIN_PRICE, DEFAULT_MAX_PRICE)

    # ---- 接驾距离 ----

    def set_pickup_distance_range(self, min_val: float, max_val: float):
        """设置接驾距离区间（max 不超过 10km）"""
        try:
            self._min_pickup_dist = max(0.0, min_val)
            self._max_pickup_dist = min(max(self._min_pickup_dist, max_val), 10.0)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置接驾距离异常: {e}")

    def get_pickup_distance_range(self) -> Tuple[float, float]:
        """获取接驾距离区间"""
        return (self._min_pickup_dist, self._max_pickup_dist)

    def reset_pickup_distance_range(self):
        """重置接驾距离为默认"""
        self.set_pickup_distance_range(DEFAULT_MIN_PICKUP_DIST, DEFAULT_MAX_PICKUP_DIST)

    # ---- 订单里程 ----

    def set_order_distance_range(self, min_val: float, max_val: float):
        """设置订单里程区间（min 最低 20km）"""
        try:
            self._min_order_dist = max(DEFAULT_MIN_ORDER_DIST, min_val)
            self._max_order_dist = max(self._min_order_dist, max_val)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置订单里程异常: {e}")

    def get_order_distance_range(self) -> Tuple[float, float]:
        """获取订单里程区间"""
        return (self._min_order_dist, self._max_order_dist)

    def reset_order_distance_range(self):
        """重置订单里程为默认"""
        self.set_order_distance_range(DEFAULT_MIN_ORDER_DIST, DEFAULT_MAX_ORDER_DIST)

    # ---- 单价过滤 ----

    def set_unit_price_range(self, min_val: float, max_val: float):
        """设置单价区间（元/km）"""
        try:
            self._min_unit_price = max(0.0, min_val)
            self._max_unit_price = max(self._min_unit_price, max_val)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置单价区间异常: {e}")

    def get_unit_price_range(self) -> Tuple[float, float]:
        """获取单价区间"""
        return (self._min_unit_price, self._max_unit_price)

    def reset_unit_price_range(self):
        """重置单价为默认 1-8 元/km"""
        self.set_unit_price_range(DEFAULT_MIN_UNIT_PRICE, DEFAULT_MAX_UNIT_PRICE)

    # ---- 订单类型 ----

    def set_order_types(self, types: List[str]):
        """设置选中的订单类型"""
        try:
            valid_keys = {t["key"] for t in ORDER_TYPES}
            self._order_types = [t for t in types if t in valid_keys]
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置订单类型异常: {e}")

    def get_order_types(self) -> List[str]:
        """获取选中的订单类型"""
        return list(self._order_types)

    def toggle_order_type(self, type_key: str) -> bool:
        """
        切换订单类型的选中状态
        :param type_key: 订单类型 key
        :return: 切换后的状态
        """
        if type_key in self._order_types:
            self._order_types.remove(type_key)
            result = False
        else:
            self._order_types.append(type_key)
            result = True
        self._save_params()
        return result

    def reset_order_types(self):
        """重置订单类型为全选"""
        self._order_types = [t["key"] for t in ORDER_TYPES]
        self._save_params()

    # ---- 区域 ----

    def get_region_manager(self) -> RegionManager:
        """获取区域管理器"""
        return self._region_mgr

    def save_region_config(self):
        """持久化区域配置"""
        try:
            self._config.set("order_filter.region_whitelist", self._region_mgr._region_whitelist)
            self._config.set("order_filter.region_blacklist", self._region_mgr._region_blacklist)
            self._config.set("order_filter.use_whitelist", self._region_mgr._use_whitelist)
        except Exception as e:
            self._logger.error(f"保存区域配置异常: {e}")

    # ============================================================
    # 刷新模式
    # ============================================================

    def set_refresh_mode(self, mode: str):
        """
        设置刷新模式
        :param mode: RefreshMode.FIXED 或 RefreshMode.RANDOM
        """
        if mode in (RefreshMode.FIXED, RefreshMode.RANDOM):
            self._refresh_mode = mode
            self._save_params()

    def get_refresh_mode(self) -> str:
        """获取刷新模式"""
        return self._refresh_mode

    def set_refresh_fixed_range(self, min_val: float, max_val: float):
        """设置固定刷新间隔（1-10 秒）"""
        try:
            self._refresh_fixed_min = max(1.0, min_val)
            self._refresh_fixed_max = min(max(self._refresh_fixed_min, max_val), 10.0)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置固定刷新间隔异常: {e}")

    def get_refresh_fixed_range(self) -> Tuple[float, float]:
        """获取固定刷新间隔"""
        return (self._refresh_fixed_min, self._refresh_fixed_max)

    def set_refresh_random_range(self, min_val: float, max_val: float):
        """设置随机刷新间隔（2-5 秒）"""
        try:
            self._refresh_random_min = max(2.0, min_val)
            self._refresh_random_max = min(max(self._refresh_random_min, max_val), 5.0)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置随机刷新间隔异常: {e}")

    def get_refresh_random_range(self) -> Tuple[float, float]:
        """获取随机刷新间隔"""
        return (self._refresh_random_min, self._refresh_random_max)

    def get_refresh_interval(self) -> float:
        """
        获取当前模式下的刷新间隔（秒）

        :return: 本次要等待的秒数
        """
        if self._refresh_mode == RefreshMode.FIXED:
            return self._refresh_fixed_min
        else:
            return random.uniform(self._refresh_random_min, self._refresh_random_max)

    # ============================================================
    # 点击延迟
    # ============================================================

    def set_click_mode(self, mode: str):
        """
        设置点击延迟模式
        :param mode: ClickMode.FIXED 或 ClickMode.RANDOM
        """
        if mode in (ClickMode.FIXED, ClickMode.RANDOM):
            self._click_mode = mode
            self._save_params()

    def get_click_mode(self) -> str:
        """获取点击延迟模式"""
        return self._click_mode

    def set_click_fixed_ms(self, ms: int):
        """设置固定点击延迟（500ms - 5s）"""
        try:
            self._click_fixed_ms = max(500, min(ms, 5000))
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置固定点击延迟异常: {e}")

    def get_click_fixed_ms(self) -> int:
        """获取固定点击延迟（毫秒）"""
        return self._click_fixed_ms

    def set_click_random_range_ms(self, min_ms: int, max_ms: int):
        """设置随机点击延迟范围（500ms - 5s）"""
        try:
            self._click_random_min_ms = max(500, min_ms)
            self._click_random_max_ms = min(max(self._click_random_min_ms, max_ms), 5000)
            self._save_params()
        except Exception as e:
            self._logger.error(f"设置随机点击延迟异常: {e}")

    def get_click_random_range_ms(self) -> Tuple[int, int]:
        """获取随机点击延迟范围"""
        return (self._click_random_min_ms, self._click_random_max_ms)

    def get_click_delay_ms(self) -> int:
        """
        获取当前模式下的点击延迟（毫秒）

        :return: 本次要等待的毫秒数
        """
        if self._click_mode == ClickMode.FIXED:
            return self._click_fixed_ms
        else:
            return random.randint(self._click_random_min_ms, self._click_random_max_ms)

    # ============================================================
    # 区间重置
    # ============================================================

    def reset_refresh_to_default(self):
        """重置刷新模式为默认（固定模式，1-10秒）"""
        try:
            self._refresh_mode = RefreshMode.FIXED
            self._refresh_fixed_min = DEFAULT_REFRESH_FIXED_MIN
            self._refresh_fixed_max = DEFAULT_REFRESH_FIXED_MAX
            self._refresh_random_min = DEFAULT_REFRESH_RANDOM_MIN
            self._refresh_random_max = DEFAULT_REFRESH_RANDOM_MAX
            self._save_params()
        except Exception as e:
            self._logger.error(f"重置刷新参数异常: {e}")

    def reset_click_to_default(self):
        """重置点击延迟为默认（固定模式，1000ms）"""
        try:
            self._click_mode = ClickMode.FIXED
            self._click_fixed_ms = DEFAULT_CLICK_FIXED_MS
            self._click_random_min_ms = DEFAULT_CLICK_RANDOM_MIN_MS
            self._click_random_max_ms = DEFAULT_CLICK_RANDOM_MAX_MS
            self._save_params()
        except Exception as e:
            self._logger.error(f"重置点击参数异常: {e}")

    def reset_all_to_default(self):
        """一键重置所有筛选参数为默认值"""
        try:
            self.reset_price_range()
            self.reset_pickup_distance_range()
            self.reset_order_distance_range()
            self.reset_unit_price_range()
            self.reset_order_types()
            self.reset_refresh_to_default()
            self.reset_click_to_default()
            self._region_mgr.clear_regions()
            self._logger.info("所有筛选参数已重置为默认值")
        except Exception as e:
            self._logger.error(f"重置所有参数异常: {e}")

    # ============================================================
    # 持久化
    # ============================================================

    def _save_params(self):
        """持久化所有筛选参数到 config.json"""
        try:
            self._config.set("order_filter.min_price", self._min_price)
            self._config.set("order_filter.max_price", self._max_price)
            self._config.set("order_filter.min_pickup_dist", self._min_pickup_dist)
            self._config.set("order_filter.max_pickup_dist", self._max_pickup_dist)
            self._config.set("order_filter.min_order_dist", self._min_order_dist)
            self._config.set("order_filter.max_order_dist", self._max_order_dist)
            self._config.set("order_filter.min_unit_price", self._min_unit_price)
            self._config.set("order_filter.max_unit_price", self._max_unit_price)
            self._config.set("order_filter.order_types", self._order_types)
            self._config.set("order_filter.refresh_mode", self._refresh_mode)
            self._config.set("order_filter.refresh_fixed_min", self._refresh_fixed_min)
            self._config.set("order_filter.refresh_fixed_max", self._refresh_fixed_max)
            self._config.set("order_filter.refresh_random_min", self._refresh_random_min)
            self._config.set("order_filter.refresh_random_max", self._refresh_random_max)
            self._config.set("order_filter.click_mode", self._click_mode)
            self._config.set("order_filter.click_fixed_ms", self._click_fixed_ms)
            self._config.set("order_filter.click_random_min_ms", self._click_random_min_ms)
            self._config.set("order_filter.click_random_max_ms", self._click_random_max_ms)
            self.save_region_config()
        except Exception as e:
            self._logger.error(f"持久化参数异常: {e}")

    # ============================================================
    # 状态查询
    # ============================================================

    def get_all_params(self) -> dict:
        """
        获取所有筛选参数（供 UI 展示）

        :return: 完整参数字典
        """
        return {
            "price_range": [self._min_price, self._max_price],
            "pickup_distance_range": [self._min_pickup_dist, self._max_pickup_dist],
            "order_distance_range": [self._min_order_dist, self._max_order_dist],
            "unit_price_range": [self._min_unit_price, self._max_unit_price],
            "order_types": list(self._order_types),
            "order_type_options": ORDER_TYPES,
            "use_whitelist": self._region_mgr._use_whitelist,
            "region_count": len(self._region_mgr.get_region_list()),
            "refresh_mode": self._refresh_mode,
            "refresh_fixed_range": [self._refresh_fixed_min, self._refresh_fixed_max],
            "refresh_random_range": [self._refresh_random_min, self._refresh_random_max],
            "click_mode": self._click_mode,
            "click_fixed_ms": self._click_fixed_ms,
            "click_random_range_ms": [self._click_random_min_ms, self._click_random_max_ms],
        }


# ============================================================
# 单例
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_order_filter() -> OrderFilter:
    """
    获取订单筛选器单例
    :return: OrderFilter 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = OrderFilter()
    return _instance


def get_region_manager() -> RegionManager:
    """
    获取区域管理器（从订单筛选器中获取）
    :return: RegionManager 实例
    """
    return get_order_filter().get_region_manager()


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_order_filter(on_locate_error: Optional[Callable[[str], None]] = None) -> dict:
    """
    初始化订单筛选模块（程序入口调用）

    自动尝试定位，定位失败弹窗让用户手动选择。
    加载持久化的筛选参数。

    :param on_locate_error: 定位失败回调（弹窗用）
    :return: 当前所有筛选参数
    """
    try:
        filt = get_order_filter()
        region = filt.get_region_manager()

        # 尝试自动定位（后台）
        def _try_locate():
            success = region.auto_locate()
            if not success:
                if on_locate_error:
                    on_locate_error("定位失败，请手动选择省市")

        locate_thread = threading.Thread(target=_try_locate, daemon=True)
        locate_thread.start()

        params = filt.get_all_params()
        LogManager.get_logger("app").info(
            f"订单筛选模块初始化完成, "
            f"price={params['price_range']}, "
            f"pickup_dist={params['pickup_distance_range']}, "
            f"order_dist={params['order_distance_range']}"
        )
        return params
    except Exception as e:
        LogManager.get_logger("error").error(f"初始化订单筛选异常: {e}")
        if on_locate_error:
            try:
                on_locate_error(f"初始化筛选模块失败: {e}")
            except Exception:
                pass
        return {}


def should_grab_ui(order_info: dict) -> Tuple[bool, str]:
    """
    UI 层判断订单是否可抢
    :param order_info: 订单信息
    :return: (是否可抢, 原因)
    """
    try:
        filt = get_order_filter()
        return filt.should_grab(order_info)
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 抢单判定异常: {e}")
        return False, f"判定异常: {e}"


def get_filter_params_ui() -> dict:
    """UI 层获取所有筛选参数"""
    try:
        return get_order_filter().get_all_params()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取参数异常: {e}")
        return {}


def set_price_range_ui(min_val: float, max_val: float):
    """UI 层设置金额区间"""
    get_order_filter().set_price_range(min_val, max_val)


def set_pickup_distance_ui(min_val: float, max_val: float):
    """UI 层设置接驾距离"""
    get_order_filter().set_pickup_distance_range(min_val, max_val)


def set_order_distance_ui(min_val: float, max_val: float):
    """UI 层设置订单里程"""
    get_order_filter().set_order_distance_range(min_val, max_val)


def set_unit_price_ui(min_val: float, max_val: float):
    """UI 层设置单价"""
    get_order_filter().set_unit_price_range(min_val, max_val)


def toggle_order_type_ui(type_key: str) -> bool:
    """UI 层切换订单类型"""
    return get_order_filter().toggle_order_type(type_key)


def set_order_types_ui(types: List[str]):
    """UI 层设置订单类型列表"""
    get_order_filter().set_order_types(types)


def set_refresh_mode_ui(mode: str):
    """UI 层设置刷新模式"""
    get_order_filter().set_refresh_mode(mode)


def set_refresh_fixed_ui(min_val: float, max_val: float):
    """UI 层设置固定刷新间隔"""
    get_order_filter().set_refresh_fixed_range(min_val, max_val)


def set_refresh_random_ui(min_val: float, max_val: float):
    """UI 层设置随机刷新间隔"""
    get_order_filter().set_refresh_random_range(min_val, max_val)


def set_click_mode_ui(mode: str):
    """UI 层设置点击延迟模式"""
    get_order_filter().set_click_mode(mode)


def set_click_fixed_ui(ms: int):
    """UI 层设置固定点击延迟"""
    get_order_filter().set_click_fixed_ms(ms)


def set_click_random_ui(min_ms: int, max_ms: int):
    """UI 层设置随机点击延迟"""
    get_order_filter().set_click_random_range_ms(min_ms, max_ms)


def reset_filter_ui():
    """UI 层重置所有筛选参数"""
    get_order_filter().reset_all_to_default()


def get_refresh_interval_ui() -> float:
    """UI 层获取刷新间隔"""
    return get_order_filter().get_refresh_interval()


def get_click_delay_ui() -> int:
    """UI 层获取点击延迟"""
    return get_order_filter().get_click_delay_ms()


# ---- 区域操作 ----

def auto_locate_ui(on_error: Optional[Callable[[str], None]] = None) -> bool:
    """
    UI 层自动定位
    :param on_error: 失败回调
    :return: True=成功
    """
    try:
        region = get_region_manager()
        success = region.auto_locate()
        if not success and on_error:
            on_error("定位失败，请手动选择省市")
        return success
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 定位异常: {e}")
        if on_error:
            on_error(f"定位异常: {e}")
        return False


def get_provinces_ui() -> List[str]:
    """UI 层获取省份列表"""
    try:
        return get_region_manager().get_provinces()
    except Exception:
        return []


def get_cities_ui(province: str) -> List[str]:
    """UI 层获取城市列表"""
    try:
        return get_region_manager().get_cities(province)
    except Exception:
        return []


def set_manual_location_ui(province: str, city: str = ""):
    """UI 层手动设置定位"""
    get_region_manager().set_manual_location(province, city)


def is_location_ok_ui() -> bool:
    """UI 层查询定位状态"""
    return get_region_manager().is_location_ok()


def get_current_location_ui() -> Tuple[str, str]:
    """UI 层获取当前定位"""
    mgr = get_region_manager()
    return (mgr.get_current_province(), mgr.get_current_city())


def add_region_ui(region: str):
    """UI 层添加区域"""
    get_region_manager().add_region(region)
    get_order_filter().save_region_config()


def remove_region_ui(region: str):
    """UI 层移除区域"""
    get_region_manager().remove_region(region)
    get_order_filter().save_region_config()


def select_all_regions_ui():
    """UI 层全选区域"""
    get_region_manager().select_all_regions()
    get_order_filter().save_region_config()


def invert_regions_ui():
    """UI 层反选区域"""
    get_region_manager().invert_regions()
    get_order_filter().save_region_config()


def clear_regions_ui():
    """UI 层清空区域"""
    get_region_manager().clear_regions()
    get_order_filter().save_region_config()


def set_region_mode_ui(use_whitelist: bool):
    """UI 层设置区域模式（白名单/黑名单）"""
    get_region_manager().set_mode(use_whitelist)
    get_order_filter().save_region_config()


def is_region_allowed_ui(province: str, city: str = "") -> bool:
    """UI 层查询区域是否允许"""
    return get_region_manager().is_region_allowed(province, city)