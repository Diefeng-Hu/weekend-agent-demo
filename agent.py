"""
美团「周末管家」Agent 核心逻辑
基于 ReAct（Reason-Act-Observe）循环实现多轮规划
支持并行工具调用、动态时间分配、3类异常自动处理
"""
import re
import json
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, TypedDict, Union, cast
from .mock_api import TOOLS


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class UserIntent:
    raw_text: str
    group_type: str = "朋友"          # 亲子 / 朋友 / 情侣
    party_size: int = 2
    duration_hours: float = 4.0
    start_time: str = "14:00"
    has_child: bool = False
    child_age: Optional[int] = None
    diet_note: Optional[str] = None   # 减肥/素食/辣/等
    max_distance_km: float = 10.0
    budget_per_person: Optional[float] = None  # 人均预算上限
    contact_names: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    step_type: str   # activity / restaurant / transit
    poi_id: str
    poi_name: str
    start_time: str
    end_time: str
    address: str
    price_per_person: float
    notes: str = ""
    order_no: Optional[str] = None
    booking_failed: bool = False  # 标记该步骤预订是否失败


@dataclass
class WeekendPlan:
    intent: UserIntent
    steps: list[PlanStep] = field(default_factory=list)
    total_cost_per_person: float = 0.0
    share_url: Optional[str] = None
    status: str = "draft"  # draft / confirmed / executed / partial
    generation_seconds: float = 0.0  # 方案生成耗时


class _ActivityItem(TypedDict):
    poi_id: str
    name: str
    duration_hours: float
    address: str
    price_per_person: float
    tags: list[str]
    hot: bool


class _RestaurantItem(TypedDict):
    poi_id: str
    name: str
    address: str
    avg_spend: float
    rating: float
    tags: list[str]


class _RouteSeg(TypedDict, total=False):
    to: str
    drive_minutes: int


class _RouteInfo(TypedDict, total=False):
    segments: list[_RouteSeg]
    total_travel_minutes: int


# ──────────────────────────────────────────────
# 意图解析（规则 + 关键词，实际可换 LLM）
# ──────────────────────────────────────────────

def parse_intent(user_input: str) -> UserIntent:
    intent = UserIntent(raw_text=user_input)
    text = user_input.lower()

    # 群体类型
    if any(k in text for k in ["孩子", "宝宝", "小朋友", "亲子", "儿童"]):
        intent.group_type = "亲子"
        intent.has_child = True
        # 扩展至 1-12 岁，使用 re 精确提取
        age_match = re.search(r'(\d{1,2})\s*岁', user_input)
        if age_match:
            intent.child_age = int(age_match.group(1))
    elif any(k in text for k in ["男朋友", "女朋友", "男友", "女友", "老公", "老婆", "情侣", "约会"]):
        intent.group_type = "情侣"
    else:
        intent.group_type = "朋友"

    # 人数（扩展到 6 人）
    size_map = [("两", 2), ("三", 3), ("四", 4), ("五", 5), ("六", 6),
                ("2个", 2), ("3个", 3), ("4个", 4), ("5个", 5), ("6个", 6),
                ("2人", 2), ("3人", 3), ("4人", 4), ("5人", 5), ("6人", 6)]
    for keyword, size in size_map:
        if keyword in text:
            intent.party_size = size
            break

    # 时长偏好
    hours_match = re.search(r'(\d+)\s*小时', text)
    if hours_match:
        intent.duration_hours = float(hours_match.group(1))
    elif "半天" in text:
        intent.duration_hours = 4.0
    elif "整天" in text or "一天" in text:
        intent.duration_hours = 8.0

    # 饮食偏好
    if "减肥" in text or "轻食" in text or "低卡" in text:
        intent.diet_note = "低卡"
    elif "素食" in text or "素的" in text:
        intent.diet_note = "素食"

    # 距离偏好
    if "别太远" in text or "附近" in text or "不远" in text:
        intent.max_distance_km = 8.0

    # 预算解析
    budget_match = re.search(r'预算\s*(\d+)', user_input)
    if budget_match:
        intent.budget_per_person = float(budget_match.group(1))
    elif any(k in text for k in ["便宜", "实惠", "不贵", "省钱"]):
        intent.budget_per_person = 100.0

    return intent


# ──────────────────────────────────────────────
# 工具调用执行器（支持计时与超时记录）
# ──────────────────────────────────────────────

class ToolExecutor:
    TOOL_TIMEOUT_WARN_SEC: float = 3.0  # 超过此阈值记为慢调用

    def __init__(self, verbose: bool = True):
        self.verbose: bool = verbose
        self.call_log: list[dict[str, object]] = []

    def call(self, tool_name: str, **kwargs: object) -> dict[str, object]:
        if self.verbose:
            print(f"  [Tool] {tool_name}({', '.join(f'{k}={repr(v)[:40]}' for k,v in kwargs.items())})")
        fn = TOOLS.get(tool_name)
        if not fn:
            return {"status": "error", "message": f"未知工具: {tool_name}"}
        t0 = time.perf_counter()
        result = fn(**kwargs)
        elapsed = time.perf_counter() - t0
        self.call_log.append({"tool": tool_name, "args": kwargs, "result": result, "elapsed_s": round(elapsed, 3)})
        if self.verbose:
            slow_tag = " ⚠️ SLOW" if elapsed > self.TOOL_TIMEOUT_WARN_SEC else ""
            print(f"  [Obs]  → {json.dumps(result, ensure_ascii=False)[:120]}...  ({elapsed*1000:.0f}ms{slow_tag})")
        return result


# ──────────────────────────────────────────────
# 核心 Agent（ReAct 循环）
# ──────────────────────────────────────────────

class WeekendPlannerAgent:
    MAX_ROUNDS: int = 10

    def __init__(self, user_id: str = "demo_user", verbose: bool = True):
        self.user_id: str = user_id
        self.executor: ToolExecutor = ToolExecutor(verbose=verbose)
        self.verbose: bool = verbose

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    # ── 规划阶段 ──────────────────────────────

    def plan(self, user_input: str, alt_index: int = 0) -> WeekendPlan:
        """
        规划周末方案。
        alt_index: 0 = 首选方案，1 = 备选方案（跳过第一个结果）
        """
        plan_start = time.perf_counter()

        self._log(f"\n{'='*60}")
        self._log(f"[User] {user_input}")
        self._log('='*60)

        # Step 1: 解析意图
        intent = parse_intent(user_input)
        reason_msg = (f"\n[Reason] 解析意图: 群体={intent.group_type}, 人数={intent.party_size}, "
                      f"时长={intent.duration_hours}h, 儿童={intent.has_child}, "
                      f"饮食={intent.diet_note}, 预算={intent.budget_per_person}")
        self._log(reason_msg)

        plan = WeekendPlan(intent=intent)

        # Step 2: 获取用户上下文
        self._log("\n[Reason] 获取用户位置与偏好")
        ctx = self.executor.call("get_user_context", user_id=self.user_id)
        location = cast(dict[str, object], ctx["location"])

        # ── Step 3+5: 并行搜索活动 & 餐厅 ──────────────
        self._log(f"\n[Reason] 【并行】同时搜索活动与餐厅，节省规划时间")
        acts_result_holder: dict[str, dict[str, object]] = {}
        rst_result_holder: dict[str, dict[str, object]] = {}

        def _search_acts():
            acts_result_holder["data"] = self.executor.call(
                "search_activities",
                group_type=intent.group_type,
                location=location,
                time_slot=intent.start_time,
                max_distance_km=intent.max_distance_km,
            )

        def _search_rsts():
            rst_result_holder["data"] = self.executor.call(
                "search_restaurants",
                location=location,
                party_size=intent.party_size,
                diet_preference=intent.diet_note,
                child_friendly=intent.has_child,
                max_distance_km=intent.max_distance_km,
            )

        t_act = threading.Thread(target=_search_acts)
        t_rst = threading.Thread(target=_search_rsts)
        t_act.start(); t_rst.start()
        t_act.join(); t_rst.join()

        activities: list[_ActivityItem] = cast(list[_ActivityItem], acts_result_holder["data"].get("items", []))
        restaurants: list[_RestaurantItem] = cast(list[_RestaurantItem], rst_result_holder["data"].get("items", []))

        # 按预算过滤活动
        if intent.budget_per_person is not None:
            activities = [a for a in activities
                          if a["price_per_person"] <= intent.budget_per_person * 0.6]
            self._log(f"[Reason] 按预算 ¥{intent.budget_per_person} 过滤后剩余 {len(activities)} 个活动")

        # 活动无结果时放宽距离（异常类型1：结果为空 / 距离过滤过严）
        if not activities:
            self._log("[Reason] ⚠️ [Exception-Empty] 无活动结果，放宽距离限制至15km")
            fallback = self.executor.call(
                "search_activities",
                group_type=intent.group_type,
                location=location,
                time_slot=intent.start_time,
                max_distance_km=15.0,
            )
            activities = cast(list[_ActivityItem], fallback.get("items", []))

        candidate_acts: list[_ActivityItem] = activities[alt_index:] if len(activities) > alt_index else activities
        chosen_activity: Optional[_ActivityItem] = candidate_acts[0] if candidate_acts else None

        # Step 4: 检查活动票务可用性（异常类型2：无票 no_ticket）
        if chosen_activity:
            self._log(f"\n[Reason] 检查 [{chosen_activity['name']}] 可用性")
            avail = self.executor.call(
                "check_availability",
                poi_id=chosen_activity["poi_id"],
                party_size=intent.party_size,
                desired_time=intent.start_time,
            )
            if not cast(bool, avail.get("tickets_available", True)):
                self._log("[Reason] ⚠️ [Exception-NoTicket] 票已售罄，换备选活动")
                chosen_activity = candidate_acts[1] if len(candidate_acts) > 1 else None

        # 按预算过滤餐厅
        if intent.budget_per_person is not None:
            restaurants = [r for r in restaurants
                           if r["avg_spend"] <= intent.budget_per_person * 0.7]
            self._log(f"[Reason] 按预算过滤后剩余 {len(restaurants)} 家餐厅")

        # Step 6: 检查餐厅座位可用性（异常类型3：无座 no_seat；含排队>5桌自动换备选）
        chosen_restaurant: Optional[_RestaurantItem] = None
        dinner_time = self._calc_time(intent.start_time,
                                      chosen_activity["duration_hours"] + 0.5 if chosen_activity else 1.5)
        for rst in restaurants[:3]:
            self._log(f"\n[Reason] 检查餐厅 [{rst['name']}] {dinner_time} 时段")
            avail = self.executor.call(
                "check_availability",
                poi_id=rst["poi_id"],
                party_size=intent.party_size,
                desired_time=dinner_time,
            )
            wait: int = cast(int, avail.get("wait_count", 0))
            has_seat: bool = cast(bool, avail.get("seats_available", True))
            if has_seat and wait <= 5:
                chosen_restaurant = rst
                self._log(f"[Reason] 选定餐厅: {rst['name']}（排队{wait}桌）")
                break
            else:
                self._log(f"[Reason] ⚠️ [Exception-NoSeat] {rst['name']} 排队{wait}桌，换备选")

        # Step 7: 估算路线（动态时间分配）
        poi_sequence: list[Union[_ActivityItem, _RestaurantItem]] = []
        if chosen_activity:
            poi_sequence.append(chosen_activity)
        if chosen_restaurant:
            poi_sequence.append(chosen_restaurant)

        route: _RouteInfo = {"segments": [], "total_travel_minutes": 0}
        if poi_sequence:
            self._log("\n[Reason] 估算完整路线，动态调整用餐时间")
            route_result = self.executor.call(
                "estimate_route",
                poi_sequence=poi_sequence,
                start_location={"name": "家", **location},
            )
            route = cast(_RouteInfo, cast(object, route_result))
            # 动态时间分配：用真实交通时间修正餐饮开始时间
            if chosen_activity and chosen_restaurant and route.get("segments"):
                transit_to_rst_min = 0
                for seg in route.get("segments", []):
                    if seg.get("to", "") == chosen_restaurant["name"]:
                        transit_to_rst_min: int = seg.get("drive_minutes", 0)
                act_end = self._calc_time(intent.start_time, chosen_activity["duration_hours"])
                dynamic_dinner = self._calc_time(act_end, transit_to_rst_min / 60.0)
                if dynamic_dinner > dinner_time:
                    log_msg = (f"[Reason] 动态时间分配：交通{transit_to_rst_min}min，"
                               f"用餐时间从 {dinner_time} 顺延至 {dynamic_dinner}")
                    self._log(log_msg)
                    dinner_time = dynamic_dinner

        # Step 7.5: 时间窗口冲突检测（异常类型4：时间冲突 time_conflict）
        if chosen_activity and chosen_restaurant:
            total_estimated_min: float = (chosen_activity["duration_hours"] * 60
                                   + route.get("total_travel_minutes", 0)
                                   + 90)  # 90min 用餐
            available_min = intent.duration_hours * 60
            if total_estimated_min > available_min:
                conflict_log = (f"[Reason] ⚠️ [Exception-TimeConflict] 预估总时长 "
                               f"{total_estimated_min:.0f}min 超出窗口 {available_min:.0f}min，"
                               f"压缩活动环节或缩短用餐时长")
                self._log(conflict_log)
                # 检查时间冲突并获取调整建议
                conflict_check = self.executor.call(
                    "check_time_conflict",
                    steps=[
                        {"name": chosen_activity["name"], "start": intent.start_time,
                         "duration_min": chosen_activity["duration_hours"] * 60},
                        {"name": chosen_restaurant["name"], "start": dinner_time,
                         "duration_min": 90},
                    ],
                    window_hours=intent.duration_hours,
                )
                if cast(bool, conflict_check.get("conflict", False)):
                    conflict_msg = (f"[Reason] 冲突详情: {conflict_check.get('message', '')}，"
                                   f"建议: {conflict_check.get('suggestion', '缩短活动时长')}")
                    self._log(conflict_msg)

        # Step 8: 天气预警检测
        self._log("\n[Reason] 检查目标区域天气")
        weather = self.executor.call("monitor_weather", location=location)
        if weather.get("status") == "alert":
            weather_msg = (f"[Reason] ⚠️ [WeatherAlert] {weather['message']}，"
                           f"优先选择室内场所")
            self._log(weather_msg)
            # 天气预警时降级：优先室内活动
            if chosen_activity and "户外" in chosen_activity.get("tags", []):
                indoor_acts = [a for a in activities
                               if "室内" in a.get("tags", []) and a["poi_id"] != chosen_activity["poi_id"]]
                if indoor_acts:
                    self._log(f"[Reason] 天气降级：{chosen_activity['name']} → {indoor_acts[0]['name']}")
                    chosen_activity = indoor_acts[0]

        # Step 9: 合成方案
        plan = self._build_plan(intent, chosen_activity, chosen_restaurant,
                                dinner_time, route)

        plan.generation_seconds = round(time.perf_counter() - plan_start, 2)
        generation_msg = (f"\n[Reason] 方案合成完成，共 {len(plan.steps)} 个环节，"
                         f"耗时 {plan.generation_seconds}s（目标≤30s）")
        self._log(generation_msg)
        self._print_plan(plan)
        return plan

    # ── 执行阶段 ──────────────────────────────

    def execute(self, plan: WeekendPlan, contact: str = "13800000000",
                share_contacts: Optional[list[str]] = None) -> WeekendPlan:
        self._log(f"\n{'='*60}")
        self._log("[执行] 开始预订所有环节...")

        failed_steps: list[str] = []

        for step in plan.steps:
            if step.step_type in ("activity", "restaurant"):
                self._log(f"\n[Act] 预订 [{step.poi_name}] @ {step.start_time}")
                result = self.executor.call(
                    "create_reservation",
                    poi_id=step.poi_id,
                    poi_name=step.poi_name,
                    time_slot=step.start_time,
                    party_size=plan.intent.party_size,
                    contact=contact,
                )
                if result.get("status") == "success":
                    step.order_no = cast(Optional[str], result.get("order_no"))
                    self._log(f"  ✓ 订单号: {step.order_no}")
                else:
                    step.booking_failed = True
                    failed_steps.append(step.poi_name)
                    self._log(f"  ✗ 预订失败: {result.get('message', '未知错误')}")

        # 分享计划
        if share_contacts:
            summary = self._format_share_text(plan)
            share_result = self.executor.call(
                "share_plan",
                plan_summary=summary,
                contacts=share_contacts,
            )
            plan.share_url = cast(Optional[str], share_result.get("share_url"))

        plan.status = "partial" if failed_steps else "executed"
        if failed_steps:
            self._log(f"\n[Warning] 以下环节预订失败: {', '.join(failed_steps)}")
        self._log(f"\n{'='*60}")
        self._log(f"[完成] 状态: {plan.status}，分享链接: {plan.share_url or '无'}")
        return plan

    # ── 辅助方法 ──────────────────────────────

    @staticmethod
    def _calc_time(base: str, add_hours: float) -> str:
        h, m = map(int, base.split(":"))
        total_min = h * 60 + m + int(add_hours * 60)
        total_min %= 1440  # 处理跨日（24*60=1440）
        return f"{total_min // 60:02d}:{total_min % 60:02d}"

    def _build_plan(self, intent: UserIntent, activity: Optional[_ActivityItem],
                    restaurant: Optional[_RestaurantItem], dinner_time: str,
                    route: _RouteInfo) -> WeekendPlan:
        plan = WeekendPlan(intent=intent)
        current_time = intent.start_time

        if activity:
            end_act = self._calc_time(current_time, activity["duration_hours"])
            plan.steps.append(PlanStep(
                step_type="activity",
                poi_id=activity["poi_id"],
                poi_name=activity["name"],
                start_time=current_time,
                end_time=end_act,
                address=activity["address"],
                price_per_person=activity["price_per_person"],
                notes=(f"{'🔥热门 ' if activity.get('hot') else ''}"
                       f"{'| '.join(activity.get('tags', [])[:2])}"),
            ))
            # 动态计算交通时间
            transit_min = 30  # 默认30min
            for seg in route.get("segments", []):
                if restaurant and seg.get("to", "") == restaurant["name"]:
                    transit_min: int = seg.get("drive_minutes", 30)
            current_time = self._calc_time(end_act, transit_min / 60.0)

        if restaurant:
            # 使用 max(dinner_time, current_time) 确保时间线连续
            actual_dinner = dinner_time if dinner_time >= current_time else current_time
            end_rst = self._calc_time(actual_dinner, 1.5)
            plan.steps.append(PlanStep(
                step_type="restaurant",
                poi_id=restaurant["poi_id"],
                poi_name=restaurant["name"],
                start_time=actual_dinner,
                end_time=end_rst,
                address=restaurant["address"],
                price_per_person=restaurant["avg_spend"],
                notes=f"⭐{restaurant['rating']} | {'、'.join(restaurant.get('tags', [])[:2])}",
            ))

        # 计算人均消费
        plan.total_cost_per_person = sum(s.price_per_person for s in plan.steps)
        return plan

    def _print_plan(self, plan: WeekendPlan):
        self._log(f"\n{'─'*60}")
        self._log(f"📋 周末计划（{plan.intent.group_type}，{plan.intent.party_size}人）")
        if plan.intent.budget_per_person:
            self._log(f"💰 预算上限: ¥{plan.intent.budget_per_person}/人")
        self._log(f"{'─'*60}")
        for step in plan.steps:
            icon = "🎯" if step.step_type == "activity" else "🍽️"
            self._log(f"{icon} [{step.start_time}-{step.end_time}] {step.poi_name}")
            self._log(f"   📍 {step.address}")
            self._log(f"   💰 ¥{step.price_per_person}/人  {step.notes}")
        self._log(f"{'─'*60}")
        self._log(f"💵 人均约 ¥{plan.total_cost_per_person:.0f}")
        self._log(f"⏱️  生成耗时 {plan.generation_seconds}s")

    def _format_share_text(self, plan: WeekendPlan) -> str:
        lines = [f"今天的计划 🎉（{plan.intent.group_type}，{plan.intent.party_size}人）"]
        for step in plan.steps:
            status = " ✓" if step.order_no else (" ✗预订失败" if step.booking_failed else "")
            lines.append(f"• {step.start_time} {step.poi_name} — {step.address}{status}")
        lines.append(f"人均约 ¥{plan.total_cost_per_person:.0f}，期待！")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    agent = WeekendPlannerAgent(user_id="user_xm", verbose=True)

    # 场景1：亲子（含预算限制）
    plan = agent.plan("今天下午空的，想带老婆孩子出去玩几小时，别离家太远，孩子5岁，老婆最近在减肥，预算300")
    _ = agent.execute(plan, contact="13800138001", share_contacts=["老婆"])

    print("\n" + "="*60 + "\n")

    # 场景2：朋友群体
    plan2 = agent.plan("总共4个人2男2女，下午想一起出去玩，吃顿好的")
    _ = agent.execute(plan2, contact="13800138002", share_contacts=["张三", "李四", "王五"])

    print("\n" + "="*60 + "\n")

    # 场景3：情侣备选方案
    plan3 = agent.plan("情侣约会，浪漫一点", alt_index=1)
    _ = agent.execute(plan3, contact="13800138003")
