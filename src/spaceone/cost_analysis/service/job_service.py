import copy
import logging
import time
from typing import List, Union
from datetime import timedelta, datetime

from spaceone.core.service import *
from spaceone.core.error import *
from spaceone.core import cache, config, utils
from spaceone.cost_analysis.model.job_task_model import JobTask
from spaceone.cost_analysis.model.job_model import Job
from spaceone.cost_analysis.model.data_source_model import DataSource
from spaceone.cost_analysis.manager.cost_manager import CostManager
from spaceone.cost_analysis.manager.job_manager import JobManager
from spaceone.cost_analysis.manager.job_task_manager import JobTaskManager
from spaceone.cost_analysis.manager.data_source_plugin_manager import DataSourcePluginManager
from spaceone.cost_analysis.manager.data_source_manager import DataSourceManager
from spaceone.cost_analysis.manager.secret_manager import SecretManager

_LOGGER = logging.getLogger(__name__)


@authentication_handler
@authorization_handler
@mutation_handler
@event_handler
class JobService(BaseService):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cost_mgr: CostManager = self.locator.get_manager('CostManager')
        self.job_mgr: JobManager = self.locator.get_manager('JobManager')
        self.job_task_mgr: JobTaskManager = self.locator.get_manager('JobTaskManager')

    @transaction
    @check_required(['task_options', 'job_task_id', 'domain_id'])
    def get_cost_data(self, params):
        """Execute task to get cost data

        Args:
            params (dict): {
                'task_options': 'dict',
                'job_task_id': 'str',
                'domain_id': 'str'
            }

        Returns:
            None
        """

        task_options = params['task_options']
        job_task_id = params['job_task_id']
        domain_id = params['domain_id']

        job_task_vo: JobTask = self.job_task_mgr.get_job_task(job_task_id, domain_id)

        job_id = job_task_vo.job_id

        # TODO: Cancel the task if the job is canceled

        data_source_mgr: DataSourceManager = self.locator.get_manager('DataSourceManager')
        ds_plugin_mgr: DataSourcePluginManager = self.locator.get_manager('DataSourcePluginManager')

        self.job_task_mgr.change_in_progress_status(job_task_vo)

        try:
            data_source_vo: DataSource = data_source_mgr.get_data_source(job_task_vo.data_source_id, domain_id)
            plugin_info = data_source_vo.plugin_info.to_dict()

            endpoint, updated_version = ds_plugin_mgr.get_data_source_plugin_endpoint(plugin_info, domain_id)

            secret_id = plugin_info.get('secret_id')
            options = plugin_info.get('options', {})
            schema = plugin_info.get('schema')
            secret_data = self._get_secret_data(secret_id, domain_id)

            ds_plugin_mgr.initialize(endpoint)
            start_dt = datetime.utcnow()

            count = 0
            _LOGGER.debug(f'[get_cost_data] start job ({job_task_id}): {start_dt}')
            for costs_data in ds_plugin_mgr.get_cost_data(options, secret_data, schema, task_options):
                for cost_data in costs_data.get('results', []):
                    count += 1
                    self._create_cost_data(cost_data, job_task_vo)

            end_dt = datetime.utcnow()
            _LOGGER.debug(f'[get_cost_data] end job ({job_task_id}): {end_dt}')
            _LOGGER.debug(f'[get_cost_data] total job time ({job_task_id}): {end_dt - start_dt}')

            self.job_task_mgr.change_success_status(job_task_vo, count)

        except Exception as e:
            self.job_task_mgr.change_error_status(job_task_vo, e)

        self._close_job(job_id, domain_id)

    def _get_secret_data(self, secret_id, domain_id):
        secret_mgr: SecretManager = self.locator.get_manager('SecretManager')
        if secret_id:
            secret_data = secret_mgr.get_secret_data(secret_id, domain_id)
        else:
            secret_data = {}

        return secret_data

    def _create_cost_data(self, cost_data, job_task_vo):
        cost_data['job_id'] = job_task_vo.job_id
        cost_data['data_source_id'] = job_task_vo.data_source_id
        cost_data['domain_id'] = job_task_vo.domain_id
        cost_data['original_currency'] = cost_data.get('currency', 'USD')
        cost_data['original_cost'] = cost_data.get('cost', 0)
        cost_data['billed_at'] = utils.iso8601_to_datetime(cost_data['billed_at'])

        self.cost_mgr.create_cost(cost_data, execute_rollback=False)

    def _close_job(self, job_id, domain_id):
        job_vo: Job = self.job_mgr.get_job(job_id, domain_id)

        if job_vo.remained_tasks == 0:
            if job_vo.status == 'IN_PROGRESS':
                self.job_mgr.change_success_status(job_vo)
                self._update_last_sync_time(job_vo)
                self._delete_changed_cost_data(job_vo)

            elif job_vo.status == 'ERROR':
                self._rollback_cost_data(job_vo)

    def _rollback_cost_data(self, job_vo: Job):
        cost_vos = self.cost_mgr.filter_costs(data_source_id=job_vo.data_source_id, domain_id=job_vo.domain_id,
                                              job_id=job_vo.job_id)

        _LOGGER.debug(f'[_close_job] delete cost data created by job: {job_vo.job_id} (count = {cost_vos.count()})')
        cost_vos.delete()

    def _update_last_sync_time(self, job_vo: Job):
        data_source_mgr: DataSourceManager = self.locator.get_manager('DataSourceManager')
        data_source_vo = data_source_mgr.get_data_source(job_vo.data_source_id, job_vo.domain_id)
        data_source_mgr.update_data_source_by_vo({'last_synchronized_at': job_vo.created_at}, data_source_vo)

    def _delete_changed_cost_data(self, job_vo: Job):
        last_changed_at = job_vo.last_changed_at

        if last_changed_at:
            query = {
                'filter': [
                    {'k': 'billed_at', 'v': last_changed_at, 'o': 'gte'},
                    {'k': 'data_source_id', 'v': job_vo.data_source_id, 'o': 'eq'},
                    {'k': 'domain_id', 'v': job_vo.domain_id, 'o': 'eq'},
                    {'k': 'job_id', 'v': job_vo.job_id, 'o': 'not'},
                ]
            }

            cost_vos, total_count = self.cost_mgr.list_costs(query)
            cost_vos.delete()