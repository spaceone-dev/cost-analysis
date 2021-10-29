import functools
from typing import List
from spaceone.api.cost_analysis.v1 import budget_pb2
from spaceone.core.pygrpc.message_type import *
from spaceone.core import utils
from spaceone.cost_analysis.model.budget_model import Budget, PlannedLimit, MonthlyCost, Notification

__all__ = ['BudgetInfo', 'BudgetsInfo']


def PlannedLimitsInfo(planned_limit_vos: List[PlannedLimit]):
    if planned_limit_vos is None:
        planned_limit_vos = []

    planned_limits_info = []

    for vo in planned_limit_vos:
        info = {
            'date': vo.date,
            'limit': vo.limit
        }

        planned_limits_info.append(budget_pb2.PlannedLimit(**info))

    return planned_limits_info


def MonthlyBudgetCostsInfo(monthly_cost_vos: List[MonthlyCost]):
    if monthly_cost_vos is None:
        monthly_cost_vos = []

    monthly_costs_info = []

    for vo in monthly_cost_vos:
        info = {
            'date': vo.date,
            'usd_cost': vo.usd_cost
        }

        monthly_costs_info.append(budget_pb2.MonthlyBudgetCost(**info))

    return monthly_costs_info


def BudgetNotificationsInfo(notification_vos: List[Notification]):
    if notification_vos is None:
        notification_vos = []

    notifications_info = []

    for vo in notification_vos:
        info = {
            'threshold': vo.threshold,
            'unit': vo.unit,
            'notification_type': vo.notification_type
        }

        notifications_info.append(budget_pb2.BudgetNotification(**info))

    return notifications_info


def BudgetInfo(budget_vo: Budget, minimal=False):
    info = {
        'budget_id': budget_vo.budget_id,
        'name': budget_vo.name,
        'limit': budget_vo.limit,
        'total_usd_cost': budget_vo.total_usd_cost,
        'project_id': budget_vo.project_id,
        'project_group_id': budget_vo.project_group_id,
    }

    if not minimal:
        info.update({
            'planned_limits': PlannedLimitsInfo(budget_vo.planned_limits),
            'monthly_costs': MonthlyBudgetCostsInfo(budget_vo.monthly_costs),
            'cost_types': change_struct_type(budget_vo.cost_types.to_dict()) if budget_vo.cost_types else None,
            'time_unit': budget_vo.time_unit,
            'start': utils.date_to_string(budget_vo.start),
            'end': utils.date_to_string(budget_vo.end),
            'notifications': BudgetNotificationsInfo(budget_vo.notifications),
            'tags': change_struct_type(budget_vo.tags),
            'domain_id': budget_vo.domain_id,
            'created_at': utils.datetime_to_iso8601(budget_vo.created_at),
            'updated_at': utils.datetime_to_iso8601(budget_vo.updated_at)
        })

    return budget_pb2.BudgetInfo(**info)


def BudgetsInfo(budget_vos, total_count, **kwargs):
    return budget_pb2.BudgetsInfo(results=list(
        map(functools.partial(BudgetInfo, **kwargs), budget_vos)), total_count=total_count)
