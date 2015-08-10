# Copyright 2014
# The Cloudscaling Group, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""RequestContext: context for requests that persist through all of ec2."""

import uuid

from keystoneclient.v2_0 import client as keystone_client
from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
from oslo_utils import timeutils
import six

from ec2api import exception
from ec2api.i18n import _, _LW


ec2_opts = [
    cfg.StrOpt('admin_user',
               help=_("Admin user")),
    cfg.StrOpt('admin_password',
               help=_("Admin password"),
               secret=True),
    cfg.StrOpt('admin_tenant_name',
               help=_("Admin tenant name")),
]

CONF = cfg.CONF
CONF.register_opts(ec2_opts)

LOG = logging.getLogger(__name__)


def generate_request_id():
    return 'req-' + str(uuid.uuid4())


class RequestContext(context.RequestContext):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """

    def __init__(self, user_id, project_id, request_id=None,
                 is_admin=None, remote_address=None,
                 auth_token=None, user_name=None, project_name=None,
                 overwrite=True, service_catalog=None, api_version=None,
                 is_os_admin=None, **kwargs):
        """Parameters

            :param overwrite: Set to False to ensure that the greenthread local
                copy of the index is not overwritten.


            :param kwargs: Extra arguments that might be present, but we ignore
                because they possibly came in from older rpc messages.
        """
        user = kwargs.pop('user', None)
        tenant = kwargs.pop('tenant', None)
        super(RequestContext, self).__init__(
            auth_token=auth_token,
            user=user_id or user,
            tenant=project_id or tenant,
            is_admin=is_admin,
            request_id=request_id,
            resource_uuid=kwargs.pop('resource_uuid', None),
            overwrite=overwrite)
        # oslo_context's RequestContext.to_dict() generates this field, we can
        # safely ignore this as we don't use it.
        kwargs.pop('user_identity', None)
        if kwargs:
            LOG.warning(_LW('Arguments dropped when creating context: %s') %
                        str(kwargs))

        self.user_id = user_id
        self.project_id = project_id
        self.remote_address = remote_address
        timestamp = timeutils.utcnow()
        if isinstance(timestamp, six.string_types):
            timestamp = timeutils.parse_strtime(timestamp)
        self.timestamp = timestamp

        self.service_catalog = service_catalog
        if self.service_catalog is None:
            # if list is empty or none
            self.service_catalog = []

        self.user_name = user_name
        self.project_name = project_name
        self.is_admin = is_admin
        # TODO(ft): call policy.check_is_admin if is_admin is None
        self.is_os_admin = is_os_admin
        self.api_version = api_version

    def to_dict(self):
        values = super(RequestContext, self).to_dict()
        # FIXME(dims): defensive hasattr() checks need to be
        # removed once we figure out why we are seeing stack
        # traces
        values.update({
            'user_id': getattr(self, 'user_id', None),
            'project_id': getattr(self, 'project_id', None),
            'is_admin': getattr(self, 'is_admin', None),
            'remote_address': getattr(self, 'remote_address', None),
            'timestamp': timeutils.strtime(self.timestamp) if hasattr(
                self, 'timestamp') else None,
            'request_id': getattr(self, 'request_id', None),
            'quota_class': getattr(self, 'quota_class', None),
            'user_name': getattr(self, 'user_name', None),
            'service_catalog': getattr(self, 'service_catalog', None),
            'project_name': getattr(self, 'project_name', None),
            'is_os_admin': getattr(self, 'is_os_admin', None),
            'api_version': getattr(self, 'api_version', None),
        })
        return values

    @classmethod
    def from_dict(cls, values):
        return cls(**values)


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def get_os_admin_context():
    """Create a context to interact with OpenStack as an administrator."""
    current_context = context.get_current()
    if (current_context and current_context.is_os_admin):
        return current_context
    # TODO(ft): make an authentification token reusable
    keystone = keystone_client.Client(
        username=CONF.admin_user,
        password=CONF.admin_password,
        tenant_name=CONF.admin_tenant_name,
        auth_url=CONF.keystone_url,
    )
    service_catalog = keystone.service_catalog.get_data()
    return RequestContext(
            keystone.auth_user_id,
            keystone.auth_tenant_id,
            auth_token=keystone.auth_token,
            service_catalog=service_catalog,
            is_os_admin=True)


def require_context(ctxt):
    """Raise exception.AuthFailure()

    if context is not a user or an admin context.
    """
    if not ctxt.is_admin and not is_user_context(ctxt):
        raise exception.AuthFailure()
