"""
Mock API 层 - 模拟美团各业务线接口
所有数据为虚构演示数据，不包含任何真实用户信息
"""
from __future__ import annotations

import json
import uuid
import random
from datetime import datetime
from typing import Callable, Optional, TypedDict, cast


# 类型定义
class Location(TypedDict, total=False):
    city: str
    district: str
    lat: float
    lng: float
    name: str


class ActivityItem(TypedDict):
    poi_id: str
    name: str
    type: str
    address: str
    distance_km: float
    rating: float
    price_per_person: float
    duration_hours: float
    open_hours: str
    tags: list[str]
    available: bool
    hot: bool


class RestaurantItem(TypedDict):
    poi_id: str
    name: str
    cuisine: str
    address: str
    distance_km: float
    rating: float
    avg_spend: float
    tags: list[str]
    child_friendly: bool
    pet_friendly: bool
    diet_options: list[str]


class StepItem(TypedDict, total=False):
    name: str
    start: str
    duration_min: float


class POIItem(TypedDict, total=False):
    name: str
    distance_km: float


class OrderItem(TypedDict, total=False):
    price: float
    qty: int


# ──────────────────────────────────────────────
# 用户上下文
# ──────────────────────────────────────────────

def get_user_context(user_id: str) -> dict[str, object]:
    """获取用户位置与历史偏好（Mock）"""
    return {
        "user_id": user_id,
        "location": {"city": "北京", "district": "朝阳区", "lat": 39.9042, "lng": 116.4074},
        "preferences": {
            "cuisine": ["川菜", "日料"],
            "avg_spend_per_person": 120,
            "max_travel_distance_km": 10,
        },
        "membership": "黄金会员",
    }


# ──────────────────────────────────────────────
# 活动/POI 搜索
# ──────────────────────────────────────────────

_ACTIVITY_DB: dict[str, list[ActivityItem]] = {
    "亲子": [
        {"poi_id": "act_001", "name": "欢乐水魔方亲子乐园", "type": "亲子乐园",
         "address": "朝阳区望京", "distance_km": 3.2, "rating": 4.8,
         "price_per_person": 88, "duration_hours": 2.5,
         "open_hours": "09:00-20:00", "tags": ["室内", "亲子", "儿童友好"],
         "available": True, "hot": True},
        {"poi_id": "act_002", "name": "北京自然博物馆", "type": "博物馆",
         "address": "东城区天桥南大街", "distance_km": 7.1, "rating": 4.6,
         "price_per_person": 30, "duration_hours": 2.0,
         "open_hours": "09:00-17:00", "tags": ["科普", "亲子", "免费停车"],
         "available": True, "hot": False},
        {"poi_id": "act_003", "name": "朝阳公园儿童游乐场", "type": "公园",
         "address": "朝阳区朝阳公园路", "distance_km": 2.8, "rating": 4.4,
         "price_per_person": 15, "duration_hours": 2.0,
         "open_hours": "06:00-21:00", "tags": ["户外", "亲子", "无需预约"],
         "available": True, "hot": False},
    ],
    "朋友": [
        {"poi_id": "act_004", "name": "密室逃脱·量子迷局", "type": "密室",
         "address": "朝阳区三里屯", "distance_km": 4.5, "rating": 4.9,
         "price_per_person": 168, "duration_hours": 1.5,
         "open_hours": "10:00-22:00", "tags": ["团建", "刺激", "4-6人"],
         "available": True, "hot": True},
        {"poi_id": "act_005", "name": "网球公园（室内场）", "type": "运动",
         "address": "朝阳区奥林匹克公园", "distance_km": 5.9, "rating": 4.5,
         "price_per_person": 80, "duration_hours": 2.0,
         "open_hours": "08:00-22:00", "tags": ["运动", "户外", "朋友"],
         "available": True, "hot": False},
        {"poi_id": "act_006", "name": "当代唐人艺术中心展览", "type": "展览",
         "address": "朝阳区798艺术区", "distance_km": 6.3, "rating": 4.7,
         "price_per_person": 0, "duration_hours": 1.5,
         "open_hours": "11:00-19:00", "tags": ["艺术", "免费", "拍照"],
         "available": True, "hot": True},
    ],
    "情侣": [
        {"poi_id": "act_007", "name": "北京planetarium天文馆", "type": "展馆",
         "address": "西城区西直门外", "distance_km": 8.2, "rating": 4.6,
         "price_per_person": 50, "duration_hours": 2.0,
         "open_hours": "09:30-16:30", "tags": ["浪漫", "科技", "情侣"],
         "available": True, "hot": False},
        {"poi_id": "act_008", "name": "什刹海摇橹船", "type": "游船",
         "address": "西城区什刹海", "distance_km": 7.5, "rating": 4.8,
         "price_per_person": 60, "duration_hours": 1.0,
         "open_hours": "09:00-18:00", "tags": ["浪漫", "户外", "拍照"],
         "available": True, "hot": True},
    ],
}


def search_activities(group_type: str, _location: Location, _time_slot: str,
                      max_distance_km: float = 10.0) -> dict[str, object]:
    """搜索活动/POI（Mock）"""
    results = _ACTIVITY_DB.get(group_type, _ACTIVITY_DB["朋友"])
    filtered = [a for a in results if a.get("distance_km", 0) <= max_distance_km]
    filtered.sort(key=lambda x: (-x.get("rating", 0), x.get("distance_km", 0)))
    return {"status": "ok", "total": len(filtered), "items": filtered}


# ──────────────────────────────────────────────
# 餐厅搜索
# ──────────────────────────────────────────────

_RESTAURANT_DB: list[RestaurantItem] = [
    {"poi_id": "rst_001", "name": "大董烤鸭（朝阳店）", "cuisine": "北京菜",
     "address": "朝阳区团结湖北四条", "distance_km": 4.1, "rating": 4.9,
     "avg_spend": 280, "tags": ["招牌烤鸭", "儿童椅", "情侣推荐"],
     "child_friendly": True, "pet_friendly": False, "diet_options": ["清淡可选"]},
    {"poi_id": "rst_002", "name": "海底捞（三里屯店）", "cuisine": "火锅",
     "address": "朝阳区三里屯路19号", "distance_km": 4.5, "rating": 4.7,
     "avg_spend": 150, "tags": ["儿童游乐区", "等位娱乐", "24小时"],
     "child_friendly": True, "pet_friendly": False, "diet_options": ["清淡锅底", "素食"]},
    {"poi_id": "rst_003", "name": "胡同口老北京炸酱面", "cuisine": "面食",
     "address": "东城区南锣鼓巷", "distance_km": 6.8, "rating": 4.6,
     "avg_spend": 60, "tags": ["地道京味", "快速出餐", "拍照打卡"],
     "child_friendly": True, "pet_friendly": False, "diet_options": []},
    {"poi_id": "rst_004", "name": "源味居私房菜（健康轻食）", "cuisine": "私房菜",
     "address": "朝阳区工体北路", "distance_km": 3.9, "rating": 4.5,
     "avg_spend": 120, "tags": ["低脂健康", "减肥友好", "私密环境"],
     "child_friendly": False, "pet_friendly": False, "diet_options": ["低卡", "无糖", "轻食套餐"]},
    {"poi_id": "rst_005", "name": "太二酸菜鱼（悠唐店）", "cuisine": "川菜",
     "address": "朝阳区悠唐购物中心", "distance_km": 3.3, "rating": 4.6,
     "avg_spend": 90, "tags": ["网红", "酸菜鱼", "年轻人爱"],
     "child_friendly": True, "pet_friendly": False, "diet_options": ["微辣可选"]},
    {"poi_id": "rst_006", "name": "绿野轻食家庭餐厅", "cuisine": "轻食",
     "address": "朝阳区望京SOHO", "distance_km": 3.5, "rating": 4.6,
     "avg_spend": 98, "tags": ["低卡健康", "儿童餐", "宠物友好"],
     "child_friendly": True, "pet_friendly": True, "diet_options": ["低卡", "儿童套餐", "无麸质"]},
    {"poi_id": "rst_007", "name": "柴犬宠物营地餐厅", "cuisine": "西餐",
     "address": "朝阳区朝阳公园周边", "distance_km": 4.0, "rating": 4.8,
     "avg_spend": 130, "tags": ["宠物友好", "户外草坪", "氛围感"],
     "child_friendly": True, "pet_friendly": True, "diet_options": []},
]


def search_restaurants(_location: Location, _party_size: int,
                       diet_preference: Optional[str] = None,
                       child_friendly: bool = False,
                       pet_friendly: bool = False,
                       max_distance_km: float = 10.0) -> dict[str, object]:
    """搜索餐厅（Mock）"""
    results: list[RestaurantItem] = _RESTAURANT_DB.copy()
    if child_friendly:
        results = [r for r in results if r.get("child_friendly", False)]
    if pet_friendly:
        results = [r for r in results if r.get("pet_friendly", False)]
    if diet_preference:
        results = [r for r in results
                   if any(diet_preference in opt for opt in r.get("diet_options", []))]
    results = [r for r in results if r.get("distance_km", 0.0) <= max_distance_km]
    results.sort(key=lambda x: -x.get("rating", 0.0))
    return {"status": "ok", "total": len(results), "items": results[:4]}


# ──────────────────────────────────────────────
# 可用性检查
# ──────────────────────────────────────────────

_AVAILABILITY_STATE: dict[str, dict[str, object]] = {
    "rst_001": {"seats_available": True, "wait_count": 0, "next_slot": "17:00"},
    "rst_002": {"seats_available": False, "wait_count": 12, "next_slot": "18:30"},
    "rst_003": {"seats_available": True, "wait_count": 3, "next_slot": "16:30"},
    "rst_004": {"seats_available": True, "wait_count": 0, "next_slot": "17:30"},
    "rst_005": {"seats_available": True, "wait_count": 5, "next_slot": "17:00"},
    "rst_006": {"seats_available": True, "wait_count": 0, "next_slot": "17:00"},
    "act_001": {"tickets_available": True, "remaining": 42},
    "act_002": {"tickets_available": True, "remaining": 100},
    "act_003": {"tickets_available": True, "remaining": 999},
    "act_004": {"tickets_available": True, "remaining": 2},
    "act_005": {"tickets_available": True, "remaining": 8},
    "act_006": {"tickets_available": True, "remaining": 999},
}


def check_availability(poi_id: str, party_size: int, desired_time: str) -> dict[str, object]:
    """检查餐厅/景点可用性（Mock）"""
    state = _AVAILABILITY_STATE.get(poi_id, {"seats_available": True, "wait_count": 0})
    return {"status": "ok", "poi_id": poi_id, "desired_time": desired_time,
            "party_size": party_size, **state}


def take_queue_number(poi_id: str, _party_size: int) -> dict[str, object]:
    """在线取号（Mock）"""
    state = _AVAILABILITY_STATE.get(poi_id, {"wait_count": 0})
    wait_time = cast(int, state.get("wait_count", 0)) * 4
    return {
        "status": "success",
        "poi_id": poi_id,
        "queue_number": f"A{random.randint(100, 999)}",
        "ahead_tables": state["wait_count"],
        "estimated_wait_minutes": wait_time,
        "message": f"取号成功！前方还有 {state['wait_count']} 桌，预计等待 {wait_time} 分钟",
    }


def monitor_weather(_location: Location) -> dict[str, object]:
    """监控天气突变（Mock）"""
    # 模拟 20 分钟后有暴雨
    return {
        "status": "alert",
        "event": "heavy_rain",
        "time_to_event_minutes": 20,
        "message": "检测到目标区域 20 分钟后将有强降雨",
    }


def check_time_conflict(steps: list[StepItem], window_hours: float) -> dict[str, object]:
    """
    检查多个行程步骤是否存在时间冲突（Mock）。
    steps: [{"name": str, "start": "HH:MM", "duration_min": float}, ...]
    window_hours: 用户可用的总时间窗口（小时）
    """
    def to_min(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    conflicts: list[str] = []
    prev_end: Optional[int] = None
    prev_name: Optional[str] = None

    for step in steps:
        start_min = to_min(step.get("start", "00:00"))
        end_min = start_min + int(step.get("duration_min", 60))
        if prev_end is not None and start_min < prev_end:
            overlap = prev_end - start_min
            conflicts.append(
                f"[{prev_name}] 结束时间与 [{step.get('name', '未知')}] 开始时间重叠 {overlap} 分钟"
            )
        prev_end = end_min
        prev_name = step.get("name", "")

    # 检查是否超出时间窗口
    if steps:
        first_start = to_min(steps[0].get("start", "00:00"))
        last_end = to_min(steps[-1].get("start", "00:00")) + int(steps[-1].get("duration_min", 60))
        total_used_min = last_end - first_start
        window_min = int(window_hours * 60)
        if total_used_min > window_min:
            conflicts.append(
                f"总行程 {total_used_min} 分钟超出可用窗口 {window_min} 分钟"
            )

    if conflicts:
        return {
            "status": "ok",
            "conflict": True,
            "conflicts": conflicts,
            "message": "；".join(conflicts),
            "suggestion": "建议缩短活动时长或选择更近距离的POI",
        }
    return {"status": "ok", "conflict": False, "message": "时间安排无冲突"}


# ──────────────────────────────────────────────
# 路线估算
# ──────────────────────────────────────────────

def estimate_route(poi_sequence: list[POIItem], start_location: Location) -> dict[str, object]:
    """估算路线耗时与距离（Mock）"""
    segments: list[dict[str, object]] = []
    total_minutes = 0
    current: dict[str, object] = dict(start_location)

    for poi in poi_sequence:
        dist = poi.get("distance_km", 3.0)
        drive_min = int(dist * 4 + random.randint(3, 8))  # 模拟拥堵
        poi_name = poi.get("name", "未知POI")
        segments.append({
            "from": current.get("name", "出发地"),
            "to": poi_name,
            "distance_km": dist,
            "drive_minutes": drive_min,
            "mode": "自驾/打车",
        })
        total_minutes += drive_min
        current = dict(poi)

    return {
        "status": "ok",
        "segments": segments,
        "total_travel_minutes": total_minutes,
        "estimated_cost_rmb": round(total_minutes / 10 * 3, 1),
    }


# ──────────────────────────────────────────────
# 预订与下单
# ──────────────────────────────────────────────

def create_reservation(poi_id: str, poi_name: str, time_slot: str,
                       party_size: int, contact: str) -> dict[str, object]:
    """创建预订（Mock）"""
    order_no = f"MT{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    return {
        "status": "success",
        "order_no": order_no,
        "poi_id": poi_id,
        "poi_name": poi_name,
        "reserved_time": time_slot,
        "party_size": party_size,
        "contact": contact,
        "message": f"预订成功！请于 {time_slot} 前5分钟到场，凭订单号 {order_no} 取票/入座",
    }


def place_order(items: list[OrderItem], delivery_address: str) -> dict[str, object]:
    """下单（外卖/商品，Mock）"""
    order_no = f"OD{datetime.now().strftime('%H%M%S')}{random.randint(100,999)}"
    total = sum(item.get("price", 0) * item.get("qty", 1) for item in items)
    return {
        "status": "success",
        "order_no": order_no,
        "items": items,
        "total_rmb": total,
        "delivery_address": delivery_address,
        "estimated_delivery": "30-45分钟",
    }


# ──────────────────────────────────────────────
# 分享
# ──────────────────────────────────────────────

def share_plan(_plan_summary: str, contacts: list[str]) -> dict[str, object]:
    """生成分享链接并发送（Mock）"""
    share_id = f"plan_{random.randint(10000,99999)}"
    share_url = f"https://mt.com/plan/{share_id}"
    return {
        "status": "success",
        "share_url": share_url,
        "share_id": share_id,
        "sent_to": contacts,
        "message": f"计划已发送给 {', '.join(contacts)}，链接: {share_url}",
    }


# ──────────────────────────────────────────────
# 工具注册表（供 Agent 使用）
# ──────────────────────────────────────────────

TOOLS: dict[str, Callable[..., dict[str, object]]] = {
    "get_user_context": get_user_context,
    "search_activities": search_activities,
    "search_restaurants": search_restaurants,
    "check_availability": check_availability,
    "take_queue_number": take_queue_number,
    "monitor_weather": monitor_weather,
    "check_time_conflict": check_time_conflict,
    "estimate_route": estimate_route,
    "create_reservation": create_reservation,
    "place_order": place_order,
    "share_plan": share_plan,
}

TOOL_SCHEMAS = [
    {
        "name": "get_user_context",
        "description": "获取用户当前位置和历史偏好",
        "parameters": {"user_id": "str"},
    },
    {
        "name": "search_activities",
        "description": "根据群体类型、位置搜索适合的活动/景点/POI",
        "parameters": {"group_type": "str(亲子/朋友/情侣)", "location": "dict",
                       "time_slot": "str", "max_distance_km": "float"},
    },
    {
        "name": "search_restaurants",
        "description": "搜索附近餐厅，支持亲子/宠物友好、饮食偏好过滤",
        "parameters": {"location": "dict", "party_size": "int",
                       "diet_preference": "Optional[str]", "child_friendly": "bool",
                       "pet_friendly": "bool"},
    },
    {
        "name": "check_availability",
        "description": "检查特定餐厅/景点在指定时间的可用座位/票量",
        "parameters": {"poi_id": "str", "party_size": "int", "desired_time": "str"},
    },
    {
        "name": "take_queue_number",
        "description": "在线提取餐厅的排号",
        "parameters": {"poi_id": "str", "party_size": "int"},
    },
    {
        "name": "monitor_weather",
        "description": "主动感知天气变化",
        "parameters": {"location": "dict"},
    },
    {
        "name": "check_time_conflict",
        "description": "检查多个行程步骤是否存在时间重叠或超出用户时间窗口",
        "parameters": {
            "steps": "list[{name:str, start:str(HH:MM), duration_min:float}]",
            "window_hours": "float",
        },
    },
    {
        "name": "estimate_route",
        "description": "估算多个POI串联的行驶时间和距离",
        "parameters": {"poi_sequence": "list[dict]", "start_location": "dict"},
    },
    {
        "name": "create_reservation",
        "description": "为餐厅/景点创建预订",
        "parameters": {"poi_id": "str", "poi_name": "str", "time_slot": "str",
                       "party_size": "int", "contact": "str"},
    },
    {
        "name": "place_order",
        "description": "下单购买商品（蛋糕/鲜花/外卖等）",
        "parameters": {"items": "list[dict]", "delivery_address": "str"},
    },
    {
        "name": "share_plan",
        "description": "生成计划分享链接并发送给指定联系人",
        "parameters": {"plan_summary": "str", "contacts": "list[str]"},
    },
]


if __name__ == "__main__":
    # 快速验证
    ctx = get_user_context("user_demo")
    print("用户上下文:", json.dumps(ctx, ensure_ascii=False, indent=2))

    loc = cast(Location, ctx["location"])
    acts = search_activities("亲子", loc, "下午", max_distance_km=10)
    print(f"\n亲子活动搜索结果（{acts['total']}条）:")
    for a in cast(list[ActivityItem], acts.get("items", [])):
        print(f"  - {a['name']} | ⭐{a['rating']} | ¥{a['price_per_person']}/人 | {a['distance_km']}km")

    avail = check_availability("rst_002", 3, "17:30")
    print(f"\n海底捞可用性: 有位={avail.get('seats_available')}, 排队={avail.get('wait_count')}桌")

    rsv = create_reservation("act_001", "欢乐水魔方亲子乐园", "14:30", 3, "13800000000")
    print(f"\n预订结果: {rsv['message']}")
