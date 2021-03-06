import deep

from zope.interface import alsoProvides
from zope.component import getUtility

import plone.api

from plone.registry.interfaces import IRegistry
from plone.protect.interfaces import IDisableCSRFProtection

from Products.Five.browser import BrowserView
from Products.PlonePAS.utils import cleanId
from Products.CMFCore.utils import getToolByName

from pcp.spmtsync.browser import utils
from pcp.spmtsync.browser import config


logger = utils.getLogger('var/log/spmtsync.log')


class SPMTSyncView(BrowserView):
    """Enable import of services from SPMT"""

    def __init__(self, context, request):
        super(SPMTSyncView, self).__init__(context, request)
        self._objs_original = set()
        self._objs_touched = set()

    def prepare_data(self, values, additional_org, email2puid, logger):

        logger.debug(values)

        fields = values.copy()

        title = fields['name'].encode('utf8')
        scl = fields['service_complete_link']['related']['href']
        identifiers = [{'type': 'spmt_uid',
                        'value': fields['uuid']},
                       ]

        fields['title'] = title
        fields['description'] = fields['description_external']
        if 'localhost' in scl:
            registry = getUtility(IRegistry)
            SPMT_BASE = registry['pcp.spmtsync.baseurl']
            scl = scl.replace('localhost', SPMT_BASE)
        fields['service_complete_link'] = scl
        fields['identifiers'] = identifiers
        # link contacts
        contact_info = fields['contact_information']
        if contact_info is not None:
            contact_url = fields['contact_information']['links']['self']
            # first map exceptions
            contact_data = utils.getDataFromSPMT(contact_url)
            try:
                contact_email = contact_data[
                    'external_contact_information']['email']
            except TypeError:
                contact_email = 'noreply@nowhere.org'
            email = config.creg2dp_email.get(contact_email, contact_email)
            # then look up corresponding UID
            contact_uid = email2puid.get(email, None)
            if contact_uid is None:
                logger.warning("'%s' not found - no contact set for '%s'"
                               % (contact_email, title))
            else:
                fields['contact'] = contact_uid
        # same for the service owner
        try:
            owner_email = fields['service_owner']['email']
        except TypeError:
            owner_email = "noreply@nowhere.org"
        o_email = config.creg2dp_email.get(owner_email, owner_email)
        owner_uid = email2puid.get(o_email, None)
        if owner_uid is None:
            logger.warning("'%s' not found - no service owner set for '%s'"
                           % (owner_email, title))
        else:
            fields['service_owner'] = owner_uid

        return fields.copy()

    def flatten_links(self, data):
        """Unpack and inline the embedded links"""
        for field in config.link_fields:
            link = data[field]['related']['href']
            data[field] = link
        details_link = data['links']['self']
        data['links'] = details_link
        return data

    def resolveDependencies(self, data):
        """Resolve dependencies by looking up the UIDs of the respective
        services. It is assumed that the services are there and can be
        looked up by name in the target folder."""

        site = plone.api.portal.get()
        deps = data['dependencies_list']['services']
        if not deps:
            data['dependencies'] = []
        else:
            dependencies = []
            for dep in deps:
                name = dep['service']['name']
                try:
                    uid = self.context[cleanId(name)].UID()
                    dependencies.append(uid)
                except KeyError:  # can happen on first pass
                    pass
            data['dependencies'] = dependencies
        return data

    def update_object(self, obj, data):
        """ Update `obj` with data dict using Archetypes edit() method.
            We preserve the original `data` dictionary in order to check
            during later updates for changed data in order to avoid
            unneccessary copy of the same object in portal_repository.
        """

        last_saved_data = getattr(obj, '_last_saved_data', None)

        if last_saved_data != data:

            diff = deep.diff(last_saved_data, data)
            if diff:
                logger.info('Diff: {}'.format(diff.print_full()))

            obj.edit(**data)
            obj.reindexObject()
            obj._last_saved_data = data

            portal_repo = plone.api.portal.get_tool('portal_repository')
            portal_repo.save(obj=obj, comment='Synchronization from SPMT')

            logger.info(
                "Updated {}/{} in the 'catalog' folder".format(obj.portal_type, obj.getId()))
        else:
            logger.debug('Up2date {}/{}'.format(obj.portal_type, obj.getId()))

    def check_and_create_object(self, container, portal_type, obj_id):
        """ Check if `container` contains an object with ID `obj_id`.
            If not, create it and return it.
        """
        if obj_id not in container.objectIds():
            obj = plone.api.content.create(
                type=portal_type,
                container=container,
                id=obj_id)
            logger.info('Adding {}/{} to "{}/{}/{}"'.format(portal_type, obj_id,
                                                            container.portal_type, container.absolute_url(1), container.Title()))

        obj = container[obj_id]

        self._objs_touched.add('/'.join(obj.getPhysicalPath()))

        if plone.api.content.get_state(obj) != 'internally_published':
            plone.api.content.transition(obj=obj, to_state='internally_published')
            obj.reindexObject()
        return obj

    def addImplementationDetails(self, impl, data, logger):
        """Adding implementation details to a service component implementation"""
        logger.debug(
            "addImplemenationDetails called with this data: '%s'" % data)
        id = cleanId('version-' + data['version'])
        details = self.check_and_create_object(
            impl, 'ServiceComponentImplementationDetails', id)

        data['title'] = 'Version ' + data['version']
        data['description'] = 'Implementation details of ' + \
            impl.Title() + ': version ' + data['version']
        data['identifiers'] = [{'type': 'spmt_uid',
                                'value': data['uuid']},
                               ]
        raw_config_data = data['configuration_parameters']
        if raw_config_data is not None:
            config_items = raw_config_data.splitlines()
            keys = [item.split()[0] for item in config_items]
            data['configuration_parameters'] = keys
        else:
            data['configuration_parameters'] = []

        self.update_object(details, data)

    def addImplementation(self, component, data, logger):
        """Adding an implementation to a service component"""
        logger.debug("addImplemenation called with this data: '%s'" % data)
        id = cleanId(data['name'])
        implementation = self.check_and_create_object(
            component, 'ServiceComponentImplementation', id)

        data['title'] = component.Title() + ' implementation: ' + data['name']
        data['identifiers'] = [{'type': 'spmt_uid',
                                'value': data['uuid']},
                               ]

        self.update_object(implementation, data)

        details_data = utils.getDataFromSPMT(
            data['component_implementation_details_link']['related']['href'])
        details = details_data['service_component_implementation_details_list'][
            'service_component_implementation_details']
        if not details:
            logger.info("No implemenation details found for '%s'" %
                        data['title'])
            return
        for detail in details:
            self.addImplementationDetails(implementation, detail, logger)

    def addComponent(self, service, data, logger):
        """Adding a service component to 'service' described by 'data'"""
        logger.debug("addComponent called with this data: '%s'" % data)
        id = cleanId(data['name'])
        component = self.check_and_create_object(
            service, 'ServiceComponent', id)

        data['title'] = "Service component '%s'" % data['name']
        data['identifiers'] = [{'type': 'spmt_uid',
                                'value': data['uuid']},
                               ]

        self.update_object(component, data)

        implementations_data = utils.getDataFromSPMT(
            data['service_component_implementations_link']['related']['href'])
        # print "#############\n", implementations_data
        if not implementations_data:
            logger.info("No implemenations_data found for '%s'" % data['title'])
            return
        implementations = implementations_data[
            'service_component_implementations_list']['service_component_implementations']
        if not implementations:
            logger.info("No implemenations found for '%s'" % data['title'])
            return
        for implementation in implementations:
            self.addImplementation(component, implementation, logger)

    def addDetails(self, parent, data, logger):
        """Adding service details"""

        details = self.check_and_create_object(
            parent, 'Service Details', 'details')

        data = self.flatten_links(data)
        data = self.resolveDependencies(data)
        data['identifiers'] = [{'type': 'spmt_uid',
                                'value': data['uuid']},
                               ]

        self.update_object(details, data)

        # adding service components if any
        full_data = utils.getDataFromSPMT(data['links']) or {}
        scl = full_data.get('service_components_list', None)
        if scl is None:
            logger.debug('No service components found for %s' % parent.Title())
            return None
        for sc in scl['service_components']:
            self.addComponent(parent, sc['component'], logger)

    def sync(self, force=False):
        """
        Main method to be called to sync content from SPMT
        """

        alsoProvides(self.request, IDisableCSRFProtection)

        site = plone.api.portal.get()
        target_folder = self.context
        spmt_services = utils.getServiceData()
        email2puid = utils.email2puid(site)

        # collect all subobjects
        catalog = plone.api.portal.get_tool('portal_catalog')
        for brain in catalog(path='/'.join(target_folder.getPhysicalPath())):
            self._objs_original.add(brain.getPath())

        if force:
            logger.debug(
                'Fresh import - removing all existing entries (force=True)')
            plone.api.content.delete(objects=self.context.contentValues())

        logger.debug("Iterating over the service data")

        for entry in spmt_services:
            shortname = entry['name']
            id = cleanId(shortname)
            if id == 'test':
                continue
            if id is None:
                logger.warning("Couldn't generate id for ", values)
                continue

            service = self.check_and_create_object(
                target_folder, 'Service', id)

            # retrieve data to extended rather than overwrite
            additional = service.getAdditional()
            data = self.prepare_data(entry, additional, email2puid, logger)
            self.update_object(service, data)

        # second loop so dependencies in 'details' can be resolved

        for entry in spmt_services:
            shortname = entry['name']
            id = cleanId(shortname)
            if id == 'test':
                continue
            try:
                service = target_folder[id]
                data = entry['service_details_list']['service_details'][0]
                # we assume there is at most one
                self.addDetails(service, data, logger)
            except IndexError:
                pass

        # compared touch objects against old obj state and
        # make untouched objects (outdated) private
        # RR (2019-05-14): why did we introduce this?
        untouched_objs = self._objs_original - self._objs_touched
        for path in untouched_objs:
            # options are defined in DPMT not SPMT
            if 'options' in path:
                continue
            obj = self.context.restrictedTraverse(path)
            if obj != target_folder:
                state = plone.api.content.get_state(obj=obj)
                if state != 'private':
                    plone.api.content.transition(obj=obj, to_state='private')

        return 'DONE'
